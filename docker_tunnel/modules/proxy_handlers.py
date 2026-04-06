"""
代理管理命令处理 - 单服务器代理服务
"""
import logging
import json
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


def _check_port_conflict(session, server_id: int, port: int, server_name: str) -> str:
    """检查端口冲突，返回错误消息，无冲突返回空字符串"""
    # 1. 检查数据库中同服务器同端口的代理
    port_dup = session.query(Proxy).filter(
        Proxy.server_id == server_id,
        Proxy.listen_port == port
    ).first()
    if port_dup:
        return f"端口 `{port}` 已被代理 `{port_dup.name}` 使用"

    # 2. 检查数据库中同服务器同端口的隧道（通过 TunnelNode 关联）
    from db.models import TunnelNode, Tunnel
    tunnel_node = session.query(TunnelNode).join(Tunnel).filter(
        TunnelNode.server_id == server_id,
        Tunnel.port == port
    ).first()
    if tunnel_node:
        return f"端口 `{port}` 已被隧道 `{tunnel_node.tunnel.name}` 使用"

    return ""


async def _check_remote_port_conflict(client, port: int, server_name: str) -> str:
    """检查远程 gost 服务上的端口冲突"""
    ok, existing_services = await client.get_services()
    if ok and existing_services:
        svc_list = existing_services if isinstance(existing_services, list) else [existing_services]
        for svc in svc_list:
            svc_addr = svc.get('addr', '')
            svc_port = svc_addr.strip(':').split(':')[-1]
            try:
                if int(svc_port) == port:
                    return f"端口 `{port}` 已被远程服务 `{svc.get('name', 'unknown')}` 占用"
            except ValueError:
                pass
    return ""


@admin_only
async def create_proxy(update: Update, context: CallbackContext):
    """
    创建代理/转发服务
    
    两种模式：
    1. 端口转发 — 第3个参数包含冒号（如 1.0.0.1:53）
       /create_proxy <名称> <服务器> <目标IP:端口> [本地端口] [协议]
    
    2. 代理服务 — 第3个参数是协议名（如 socks5）
       /create_proxy <名称> <服务器> <协议> [端口]
    """
    args = context.args or []

    if len(args) < 2:
        protocols_list = "\n".join([f"  `{k}` — {v}" for k, v in PROXY_PROTOCOLS.items()])
        await update.message.reply_text(
            "📋 *创建代理/转发*\n\n"
            "🔹 *端口转发模式*（第3个参数含冒号）:\n"
            "`/create_proxy <名称> <服务器> <目标IP:端口> [本地端口] [tcp|udp]`\n\n"
            "🔹 *代理服务模式*（第3个参数是协议）:\n"
            "`/create_proxy <名称> <服务器> <协议> [端口]`\n\n"
            f"支持协议:\n{protocols_list}\n\n"
            "示例:\n"
            "```\n"
            "# 端口转发 — 转发到 1.0.0.1:53\n"
            "/create_proxy dns_fwd myserver 1.0.0.1:53\n"
            "/create_proxy dns_fwd myserver 1.0.0.1:53 10053\n"
            "/create_proxy dns_fwd myserver 1.0.0.1:53 10053 udp\n\n"
            "# 代理服务 — 创建 socks5 代理\n"
            "/create_proxy myproxy server1 socks5 1080\n"
            "/create_proxy myproxy server1 ss 8388\n"
            "```",
            parse_mode='Markdown'
        )
        return

    proxy_name = args[0]
    server_identifier = args[1]
    third_arg = args[2] if len(args) >= 3 else ""

    with session_scope() as session:
        # 查找服务器
        server = session.query(Server).filter(Server.name == server_identifier).first()
        if not server:
            try:
                server = session.query(Server).filter(Server.id == int(server_identifier)).first()
            except ValueError:
                pass
        if not server:
            await update.message.reply_text(f"❌ 未找到服务器 `{server_identifier}`", parse_mode='Markdown')
            return

        # 检查代理名是否重复
        existing = session.query(Proxy).filter(
            Proxy.server_id == server.id,
            Proxy.name == proxy_name
        ).first()
        if existing:
            await update.message.reply_text(f"❌ 服务器 `{server.name}` 上已存在代理 `{proxy_name}`", parse_mode='Markdown')
            return

        server_id = server.id
        server_ip = server.ip
        server_name = server.name
        client = get_server_api_client(server)

        # ===== 判断模式：端口转发 vs 代理服务 =====
        if third_arg and ':' in third_arg and not third_arg.lower() in PROXY_PROTOCOLS:
            # ====== 端口转发模式 ======
            target_addr = third_arg  # e.g. "1.0.0.1:53"
            
            # 解析本地监听端口
            if len(args) >= 4:
                try:
                    listen_port = int(args[3])
                except ValueError:
                    await update.message.reply_text("❌ 本地端口必须是数字！")
                    return
            else:
                # 默认使用和目标端口一样的端口
                try:
                    listen_port = int(target_addr.split(':')[-1])
                except ValueError:
                    await update.message.reply_text("❌ 无法解析目标端口，请指定本地端口！")
                    return

            # 协议
            protocol = args[4].lower() if len(args) >= 5 else 'tcp'

            # 端口冲突检查
            err = _check_port_conflict(session, server_id, listen_port, server_name)
            if err:
                await update.message.reply_text(f"❌ 端口冲突！{err}", parse_mode='Markdown')
                return

            err = await _check_remote_port_conflict(client, listen_port, server_name)
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
                await update.message.reply_text(
                    f"❌ 创建转发失败！\n错误: {data}",
                    parse_mode='Markdown'
                )

        else:
            # ====== 代理服务模式 ======
            protocol = third_arg.lower() if third_arg else 'socks5'
            port = GOST_DEFAULT_PROXY_PORT

            if len(args) >= 4:
                try:
                    port = int(args[3])
                except ValueError:
                    await update.message.reply_text("❌ 端口必须是数字！")
                    return

            if protocol not in PROXY_PROTOCOLS:
                await update.message.reply_text(
                    f"❌ 不支持的协议 `{protocol}`\n支持: {', '.join(PROXY_PROTOCOLS.keys())}",
                    parse_mode='Markdown'
                )
                return

            # 端口冲突检查
            err = _check_port_conflict(session, server_id, port, server_name)
            if err:
                await update.message.reply_text(f"❌ 端口冲突！{err}", parse_mode='Markdown')
                return

            err = await _check_remote_port_conflict(client, port, server_name)
            if err:
                await update.message.reply_text(f"❌ {err}", parse_mode='Markdown')
                return

            # 通过 API 创建代理
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
                await update.message.reply_text(
                    f"❌ 创建代理失败！\n错误: {data}",
                    parse_mode='Markdown'
                )


@admin_only
async def list_proxies(update: Update, context: CallbackContext):
    """列出所有代理"""
    with session_scope() as session:
        proxies = session.query(Proxy).all()
        # 在 session 内构建数据，避免 DetachedInstanceError
        proxy_data = []
        for p in proxies:
            server = session.query(Server).filter(Server.id == p.server_id).first()
            
            # 解析转发目标
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
            # 转发模式
            lines.append(
                f"{active_emoji} *{p['name']}* (ID:{p['id']})\n"
                f"  服务器: `{p['server_name']}` ({p['server_ip']})\n"
                f"  🔛 `{p['server_ip']}:{p['listen_port']}` → `{p['target']}` ({p['protocol']})\n"
                f"  状态: {'运行中' if p['is_active'] else '已停止'}\n"
            )
        else:
            # 代理模式
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

        # 通过 API 删除服务
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
            
            # 判断是转发模式还是代理模式
            if proxy.protocol.startswith('forward_'):
                # 转发模式 — 从 config_json 恢复目标地址
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
                # 代理模式
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
