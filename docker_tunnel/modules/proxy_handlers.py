"""
代理管理命令处理 - 单服务器代理服务
"""
import logging
import json
import time
from telegram import Update
from telegram.ext import CallbackContext
from db.database import session_scope
from db.models import Server, Proxy
from modules.admin import admin_only
from modules.server_handlers import get_server_api_client
from config import GOST_DEFAULT_PROXY_PORT

logger = logging.getLogger(__name__)

# 支持的代理协议
PROXY_PROTOCOLS = {
    'socks5': 'SOCKS5 代理',
    'http': 'HTTP 代理',
    'socks5+tls': 'SOCKS5 + TLS 加密',
    'http+tls': 'HTTP + TLS 加密',
    'ss': 'Shadowsocks',
    'tcp': 'TCP 转发',
    'relay+tls': 'Relay + TLS 中继',
}


def _check_port_conflict(session, server_id: int, port: int) -> str:
    """检查端口冲突，返回错误消息，无冲突返回空字符串"""
    port_dup = session.query(Proxy).filter(
        Proxy.server_id == server_id,
        Proxy.listen_port == port
    ).first()
    if port_dup:
        return f"端口 {port} 已被代理 `{port_dup.name}` 使用"

    from db.models import TunnelNode, Tunnel
    tunnel_node = session.query(TunnelNode).join(Tunnel).filter(
        TunnelNode.server_id == server_id,
        Tunnel.port == port
    ).first()
    if tunnel_node:
        return f"端口 {port} 已被隧道 `{tunnel_node.tunnel.name}` 使用"

    return ""


async def _check_remote_port_conflict(client, port: int) -> str:
    """检查远程 gost 服务上的端口冲突"""
    ok, existing_services = await client.get_services()
    if ok and existing_services:
        svc_list = existing_services if isinstance(existing_services, list) else [existing_services]
        for svc in svc_list:
            svc_addr = svc.get('addr', '')
            svc_port = svc_addr.strip(':').split(':')[-1]
            try:
                if int(svc_port) == port:
                    return f"端口 {port} 已被远程服务 `{svc.get('name', 'unknown')}` 占用"
            except ValueError:
                pass
    return ""


def _find_server(session, identifier):
    """查找服务器，支持名称和 ID"""
    if not identifier:
        return None
    server = session.query(Server).filter(Server.name == identifier).first()
    if not server:
        try:
            server = session.query(Server).filter(Server.id == int(identifier)).first()
        except (ValueError, TypeError):
            pass
    return server


def _get_default_server(session):
    """获取默认服务器：ID 最小且在线的服务器"""
    server = session.query(Server).filter(Server.status == 'online').order_by(Server.id).first()
    if not server:
        server = session.query(Server).order_by(Server.id).first()
    return server


def _parse_create_args(args):
    """
    智能解析 create_proxy 参数
    
    返回 dict: {
        'mode': 'forward' 或 'proxy',
        'proxy_name': str 或 None,
        'server_identifier': str 或 None,
        'target_addr': str (转发模式),
        'listen_port': int 或 None (转发模式),
        'protocol': str (转发模式 tcp/udp 或代理模式协议),
        'port': int (代理模式),
    }
    """
    result = {
        'mode': None,
        'proxy_name': None,
        'server_identifier': None,
        'target_addr': None,
        'listen_port': None,
        'protocol': 'tcp',
        'port': GOST_DEFAULT_PROXY_PORT,
    }

    # 找目标地址（含冒号且不是协议名）
    target_idx = None
    for i, a in enumerate(args):
        if ':' in a and a.lower() not in PROXY_PROTOCOLS:
            target_idx = i
            break

    if target_idx is not None:
        # ===== 端口转发模式 =====
        result['mode'] = 'forward'
        result['target_addr'] = args[target_idx]
        before = args[:target_idx]
        after = args[target_idx + 1:]

        # 解析目标前的参数
        if len(before) == 1:
            if before[0].isdigit():
                result['server_identifier'] = before[0]
            else:
                result['proxy_name'] = before[0]
        elif len(before) >= 2:
            result['proxy_name'] = before[0]
            result['server_identifier'] = before[1]

        # 解析目标后的参数
        if len(after) >= 1:
            try:
                result['listen_port'] = int(after[0])
            except ValueError:
                result['protocol'] = after[0].lower()
        if len(after) >= 2:
            result['protocol'] = after[1].lower()

        # 自动生成名称
        if not result['proxy_name']:
            t = result['target_addr'].replace(':', '_')
            p = f"_{result['listen_port']}" if result['listen_port'] else ""
            result['proxy_name'] = f"fwd_{t}{p}"

    else:
        # ===== 代理服务模式 =====
        # 找协议参数
        proto_idx = None
        for i, a in enumerate(args):
            if a.lower() in PROXY_PROTOCOLS:
                proto_idx = i
                break

        if proto_idx is None:
            return None  # 无法识别

        result['mode'] = 'proxy'
        result['protocol'] = args[proto_idx].lower()
        before = args[:proto_idx]
        after = args[proto_idx + 1:]

        if len(before) == 1:
            if before[0].isdigit():
                result['server_identifier'] = before[0]
            else:
                result['proxy_name'] = before[0]
        elif len(before) >= 2:
            result['proxy_name'] = before[0]
            result['server_identifier'] = before[1]

        # 自动生成名称
        if not result['proxy_name']:
            result['proxy_name'] = f"proxy_{result['protocol']}_{int(time.time()) % 100000}"

        # 解析端口
        if len(after) >= 1:
            try:
                result['port'] = int(after[0])
            except ValueError:
                pass

    return result


@admin_only
async def create_proxy(update: Update, context: CallbackContext):
    """创建代理/转发服务 — 智能参数解析"""
    args = context.args or []

    if not args:
        protocols_list = "\n".join([f"  `{k}` — {v}" for k, v in PROXY_PROTOCOLS.items()])
        await update.message.reply_text(
            "📋 *创建代理/转发*\n\n"
            "🔹 *端口转发*（目标含冒号）:\n"
            "`/create_proxy [名称] [服务器] <目标IP:端口> [本地端口] [tcp|udp]`\n\n"
            "🔹 *代理服务*（协议名）:\n"
            "`/create_proxy [名称] [服务器] <协议> [端口]`\n\n"
            "💡 名称省略→自动生成 | 服务器省略→默认选在线服务器\n\n"
            f"支持协议:\n{protocols_list}\n\n"
            "示例:\n"
            "```\n"
            "# 最简 — 自动命名+自动选服务器\n"
            "/create_proxy 1.0.0.1:53\n"
            "/create_proxy 1.0.0.1:53 10053\n"
            "/create_proxy 1.0.0.1:53 10053 udp\n\n"
            "# 指定服务器(ID或名称)\n"
            "/create_proxy 1 1.0.0.1:53\n\n"
            "# 指定名称\n"
            "/create_proxy dns_fwd 1.0.0.1:53\n\n"
            "# 完整\n"
            "/create_proxy dns_fwd 1 1.0.0.1:53 10053 tcp\n\n"
            "# 代理服务\n"
            "/create_proxy socks5\n"
            "/create_proxy myproxy 1 socks5 1080\n\n"
            "# 迁移到其他服务器\n"
            "/move_proxy <名称> <新服务器>\n"
            "```",
            parse_mode='Markdown'
        )
        return

    # 解析参数
    parsed = _parse_create_args(args)
    if parsed is None:
        await update.message.reply_text(
            "❌ 无法识别参数！请提供目标地址（含冒号）或协议名。\n"
            "示例: `/create_proxy 1.0.0.1:53` 或 `/create_proxy socks5`",
            parse_mode='Markdown'
        )
        return

    proxy_name = parsed['proxy_name']
    server_identifier = parsed['server_identifier']

    with session_scope() as session:
        # 查找服务器
        server = _find_server(session, server_identifier)
        if not server:
            # 尝试默认服务器
            server = _get_default_server(session)
            if not server:
                await update.message.reply_text("❌ 未找到可用服务器！请先添加服务器。")
                return
            if server_identifier:
                # 用户指定了服务器但找不到
                await update.message.reply_text(
                    f"⚠️ 未找到服务器 `{server_identifier}`，自动选择 `{server.name}` (ID:{server.id})",
                    parse_mode='Markdown'
                )

        # 检查代理名是否重复
        existing = session.query(Proxy).filter(
            Proxy.server_id == server.id,
            Proxy.name == proxy_name
        ).first()
        if existing:
            # 名称重复，自动追加后缀
            proxy_name = f"{proxy_name}_{int(time.time()) % 10000}"

        server_id = server.id
        server_ip = server.ip
        server_name = server.name
        client = get_server_api_client(server)

        if parsed['mode'] == 'forward':
            # ====== 端口转发模式 ======
            target_addr = parsed['target_addr']

            # 本地监听端口
            listen_port = parsed['listen_port']
            if listen_port is None:
                try:
                    listen_port = int(target_addr.split(':')[-1])
                except ValueError:
                    await update.message.reply_text("❌ 无法解析目标端口，请指定本地端口！")
                    return

            protocol = parsed['protocol']

            # 端口冲突检查
            err = _check_port_conflict(session, server_id, listen_port)
            if err:
                await update.message.reply_text(f"❌ 端口冲突！{err}", parse_mode='Markdown')
                return

            err = await _check_remote_port_conflict(client, listen_port)
            if err:
                await update.message.reply_text(f"❌ {err}", parse_mode='Markdown')
                return

            # 通过 gost API 创建转发
            success, data = await client.create_forward_service(
                name=proxy_name,
                listen_port=listen_port,
                target_addr=target_addr,
                protocol=protocol
            )

            if success:
                proxy = Proxy(
                    name=proxy_name,
                    server_id=server_id,
                    protocol=f"forward_{protocol}",
                    listen_port=listen_port,
                    config_json=json.dumps({"target": target_addr, "type": "forward"}),
                    is_active=True
                )
                session.add(proxy)

                await update.message.reply_text(
                    f"✅ 端口转发创建成功！\n\n"
                    f"📝 名称: `{proxy_name}`\n"
                    f"🖥 服务器: `{server_name}` ({server_ip})\n"
                    f"🔌 本地端口: `{listen_port}`\n"
                    f"🎯 目标: `{target_addr}`\n"
                    f"📡 协议: `{protocol}`\n\n"
                    f"连接: `{server_ip}:{listen_port}` → `{target_addr}`",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(f"❌ 创建转发失败！\n错误: {data}", parse_mode='Markdown')

        else:
            # ====== 代理服务模式 ======
            protocol = parsed['protocol']
            port = parsed['port']

            if protocol not in PROXY_PROTOCOLS:
                await update.message.reply_text(
                    f"❌ 不支持的协议 `{protocol}`\n支持: {', '.join(PROXY_PROTOCOLS.keys())}",
                    parse_mode='Markdown'
                )
                return

            # 端口冲突检查
            err = _check_port_conflict(session, server_id, port)
            if err:
                await update.message.reply_text(f"❌ 端口冲突！{err}", parse_mode='Markdown')
                return

            err = await _check_remote_port_conflict(client, port)
            if err:
                await update.message.reply_text(f"❌ {err}", parse_mode='Markdown')
                return

            success, data = await client.create_proxy_service(
                name=proxy_name,
                protocol=protocol,
                port=port
            )

            if success:
                proxy = Proxy(
                    name=proxy_name,
                    server_id=server_id,
                    protocol=protocol,
                    listen_port=port,
                    config_json=json.dumps(data) if data else '',
                    is_active=True
                )
                session.add(proxy)

                await update.message.reply_text(
                    f"✅ 代理服务创建成功！\n\n"
                    f"📝 名称: `{proxy_name}`\n"
                    f"🖥 服务器: `{server_name}` ({server_ip})\n"
                    f"📡 协议: `{protocol}`\n"
                    f"🔌 端口: `{port}`\n\n"
                    f"连接信息: `{server_ip}:{port}`",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(f"❌ 创建代理失败！\n错误: {data}", parse_mode='Markdown')


@admin_only
async def move_proxy(update: Update, context: CallbackContext):
    """
    迁移代理/转发到另一台服务器
    
    用法: /move_proxy <代理名称> <新服务器>
    """
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "📋 *迁移代理/转发*\n\n"
            "用法: `/move_proxy <名称或ID> <新服务器>`\n\n"
            "将转发迁移到新服务器（旧服务器上的服务会被删除）\n\n"
            "示例:\n"
            "```\n"
            "/move_proxy dns_fwd 2\n"
            "/move_proxy 1 newserver\n"
            "```",
            parse_mode='Markdown'
        )
        return

    proxy_identifier = args[0]
    new_server_identifier = args[1]

    with session_scope() as session:
        # 查找代理
        proxy = session.query(Proxy).filter(Proxy.name == proxy_identifier).first()
        if not proxy:
            try:
                proxy = session.query(Proxy).filter(Proxy.id == int(proxy_identifier)).first()
            except ValueError:
                pass
        if not proxy:
            await update.message.reply_text(f"❌ 未找到代理 `{proxy_identifier}`", parse_mode='Markdown')
            return

        # 查找新服务器
        new_server = _find_server(session, new_server_identifier)
        if not new_server:
            await update.message.reply_text(f"❌ 未找到服务器 `{new_server_identifier}`", parse_mode='Markdown')
            return

        if new_server.id == proxy.server_id:
            await update.message.reply_text("❌ 新服务器和当前服务器相同！", parse_mode='Markdown')
            return

        old_server = session.query(Server).filter(Server.id == proxy.server_id).first()
        old_server_name = old_server.name if old_server else '未知'
        old_server_ip = old_server.ip if old_server else '未知'

        # 1. 尝试从旧服务器删除（可能失联，忽略错误）
        if old_server:
            try:
                old_client = get_server_api_client(old_server)
                await old_client.delete_service(proxy.name)
            except Exception:
                pass  # 旧服务器失联也继续

        # 2. 在新服务器上创建
        new_client = get_server_api_client(new_server)

        # 端口冲突检查
        err = _check_port_conflict(session, new_server.id, proxy.listen_port)
        if err:
            await update.message.reply_text(f"❌ 新服务器端口冲突！{err}", parse_mode='Markdown')
            return

        if proxy.protocol.startswith('forward_'):
            # 转发模式
            try:
                config = json.loads(proxy.config_json) if proxy.config_json else {}
                target_addr = config.get('target', '')
                fwd_protocol = proxy.protocol.replace('forward_', '')
            except:
                await update.message.reply_text("❌ 无法解析转发配置！")
                return

            success, data = await new_client.create_forward_service(
                name=proxy.name,
                listen_port=proxy.listen_port,
                target_addr=target_addr,
                protocol=fwd_protocol
            )
        else:
            # 代理模式
            success, data = await new_client.create_proxy_service(
                name=proxy.name,
                protocol=proxy.protocol,
                port=proxy.listen_port
            )

        if success:
            # 更新数据库
            proxy.server_id = new_server.id
            proxy.is_active = True

            if proxy.protocol.startswith('forward_'):
                config = json.loads(proxy.config_json) if proxy.config_json else {}
                await update.message.reply_text(
                    f"✅ 转发迁移成功！\n\n"
                    f"📝 名称: `{proxy.name}`\n"
                    f"❌ 旧服务器: `{old_server_name}` ({old_server_ip})\n"
                    f"✅ 新服务器: `{new_server.name}` ({new_server.ip})\n"
                    f"🔛 `{new_server.ip}:{proxy.listen_port}` → `{config.get('target', '?')}`",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    f"✅ 代理迁移成功！\n\n"
                    f"📝 名称: `{proxy.name}`\n"
                    f"❌ 旧服务器: `{old_server_name}` ({old_server_ip})\n"
                    f"✅ 新服务器: `{new_server.name}` ({new_server.ip})\n"
                    f"📡 `{new_server.ip}:{proxy.listen_port}` ({proxy.protocol})",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(f"❌ 在新服务器上创建失败！\n错误: {data}", parse_mode='Markdown')


@admin_only
async def list_proxies(update: Update, context: CallbackContext):
    """列出所有代理"""
    with session_scope() as session:
        proxies = session.query(Proxy).all()
        proxy_data = []
        for p in proxies:
            server = session.query(Server).filter(Server.id == p.server_id).first()

            target = ""
            if p.protocol.startswith('forward_'):
                try:
                    config = json.loads(p.config_json) if p.config_json else {}
                    target = config.get('target', '')
                except:
                    pass

            proxy_data.append({
                'id': p.id,
                'name': p.name,
                'server_name': server.name if server else '未知',
                'server_ip': server.ip if server else '未知',
                'protocol': p.protocol,
                'listen_port': p.listen_port,
                'is_active': p.is_active,
                'target': target,
            })

    if not proxy_data:
        await update.message.reply_text("📭 暂无代理/转发。使用 `/create_proxy` 创建。", parse_mode='Markdown')
        return

    lines = ["📋 *代理/转发列表*\n"]
    for p in proxy_data:
        active_emoji = "🟢" if p['is_active'] else "🔴"
        if p['target']:
            lines.append(
                f"{active_emoji} *{p['name']}* (ID:{p['id']})\n"
                f"  服务器: `{p['server_name']}` ({p['server_ip']})\n"
                f"  🔛 `{p['server_ip']}:{p['listen_port']}` → `{p['target']}` ({p['protocol']})\n"
                f"  状态: {'运行中' if p['is_active'] else '已停止'}\n"
            )
        else:
            lines.append(
                f"{active_emoji} *{p['name']}* (ID:{p['id']})\n"
                f"  服务器: `{p['server_name']}` ({p['server_ip']})\n"
                f"  协议: `{p['protocol']}` | 端口: `{p['listen_port']}`\n"
                f"  状态: {'运行中' if p['is_active'] else '已停止'}\n"
            )

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


@admin_only
async def del_proxy(update: Update, context: CallbackContext):
    """删除代理"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/del_proxy <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        proxy = session.query(Proxy).filter(Proxy.name == identifier).first()
        if not proxy:
            try:
                proxy = session.query(Proxy).filter(Proxy.id == int(identifier)).first()
            except ValueError:
                pass
        if not proxy:
            await update.message.reply_text(f"❌ 未找到代理 `{identifier}`", parse_mode='Markdown')
            return

        server = session.query(Server).filter(Server.id == proxy.server_id).first()
        if server:
            client = get_server_api_client(server)
            await client.delete_service(proxy.name)

        name = proxy.name
        session.delete(proxy)

    await update.message.reply_text(f"✅ 代理 *{name}* 已删除。", parse_mode='Markdown')


@admin_only
async def stop_proxy(update: Update, context: CallbackContext):
    """停止代理"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/stop_proxy <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        proxy = session.query(Proxy).filter(Proxy.name == identifier).first()
        if not proxy:
            try:
                proxy = session.query(Proxy).filter(Proxy.id == int(identifier)).first()
            except ValueError:
                pass
        if not proxy:
            await update.message.reply_text(f"❌ 未找到代理 `{identifier}`", parse_mode='Markdown')
            return

        server = session.query(Server).filter(Server.id == proxy.server_id).first()
        if server:
            client = get_server_api_client(server)
            success, data = await client.delete_service(proxy.name)
            if success:
                proxy.is_active = False
                await update.message.reply_text(f"✅ 代理 *{proxy.name}* 已停止。", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"❌ 停止代理失败: {data}", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ 关联的服务器不存在！", parse_mode='Markdown')


@admin_only
async def start_proxy(update: Update, context: CallbackContext):
    """重新启动代理"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/start_proxy <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        proxy = session.query(Proxy).filter(Proxy.name == identifier).first()
        if not proxy:
            try:
                proxy = session.query(Proxy).filter(Proxy.id == int(identifier)).first()
            except ValueError:
                pass
        if not proxy:
            await update.message.reply_text(f"❌ 未找到代理 `{identifier}`", parse_mode='Markdown')
            return

        server = session.query(Server).filter(Server.id == proxy.server_id).first()
        if server:
            client = get_server_api_client(server)

            if proxy.protocol.startswith('forward_'):
                try:
                    config = json.loads(proxy.config_json) if proxy.config_json else {}
                    target_addr = config.get('target', '')
                    fwd_protocol = proxy.protocol.replace('forward_', '')
                    if not target_addr:
                        await update.message.reply_text("❌ 找不到转发目标地址！")
                        return
                    success, data = await client.create_forward_service(
                        name=proxy.name,
                        listen_port=proxy.listen_port,
                        target_addr=target_addr,
                        protocol=fwd_protocol
                    )
                except Exception as e:
                    await update.message.reply_text(f"❌ 恢复转发配置失败: {e}")
                    return
            else:
                success, data = await client.create_proxy_service(
                    name=proxy.name,
                    protocol=proxy.protocol,
                    port=proxy.listen_port
                )

            if success:
                proxy.is_active = True

                if proxy.protocol.startswith('forward_'):
                    config = json.loads(proxy.config_json) if proxy.config_json else {}
                    await update.message.reply_text(
                        f"✅ 转发 *{proxy.name}* 已启动！\n"
                        f"`{server.ip}:{proxy.listen_port}` → `{config.get('target', '?')}`",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        f"✅ 代理 *{proxy.name}* 已启动！\n"
                        f"连接: `{server.ip}:{proxy.listen_port}`",
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text(f"❌ 启动失败: {data}", parse_mode='Markdown')