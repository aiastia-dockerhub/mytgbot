"""
隧道管理命令处理 - 多服务器组成隧道链路
"""
import logging
from telegram import Update
from telegram.ext import CallbackContext
from db.database import session_scope
from db.models import Server, Tunnel, TunnelNode
from modules.admin import admin_only
from modules.server_handlers import get_server_api_client
from config import GOST_DEFAULT_PROXY_PORT

logger = logging.getLogger(__name__)


def _find_server(session, identifier):
    """查找服务器（按名称或ID）"""
    server = session.query(Server).filter(Server.name == identifier).first()
    if not server:
        try:
            server = session.query(Server).filter(Server.id == int(identifier)).first()
        except ValueError:
            pass
    return server


@admin_only
async def create_tunnel(update: Update, context: CallbackContext):
    """
    创建隧道（多服务器链路）
    
    用法:
    /create_tunnel <隧道名称> <协议> <端口> <服务器1> <服务器2> [服务器3] ...
    
    至少需要2台服务器，按顺序组成链路：
    服务器1(入口) → 服务器2(中转/出口) → ...
    """
    args = context.args or []

    if len(args) < 4:
        await update.message.reply_text(
            "🔗 *创建隧道*\n\n"
            "用法:\n"
            "`/create_tunnel <名称> <协议> <端口> <服务器1> <服务器2> [服务器3...]`\n\n"
            "说明:\n"
            "• 至少需要 2 台服务器\n"
            "• 服务器按顺序组成链路\n"
            "• 第1台为入口，最后1台为出口，中间为中转\n\n"
            "支持协议: `relay+tls`, `relay+ws+tls`, `relay`, `tcp`\n\n"
            "示例:\n"
            "`/create_tunnel mytunnel relay+tls 8080 s1 s2 s3`\n"
            "`/create_tunnel simple tcp 9090 serverA serverB`",
            parse_mode='Markdown'
        )
        return

    tunnel_name = args[0]
    protocol = args[1].lower()
    try:
        port = int(args[2])
    except ValueError:
        await update.message.reply_text("❌ 端口必须是数字！")
        return

    server_identifiers = args[3:]
    if len(server_identifiers) < 2:
        await update.message.reply_text("❌ 隧道至少需要 2 台服务器！")
        return

    # 验证所有服务器存在
    servers = []
    missing = []
    with session_scope() as session:
        # 检查隧道名是否重复
        existing = session.query(Tunnel).filter(Tunnel.name == tunnel_name).first()
        if existing:
            await update.message.reply_text(f"❌ 隧道名称 `{tunnel_name}` 已存在！", parse_mode='Markdown')
            return

        for sid in server_identifiers:
            server = _find_server(session, sid)
            if server:
                servers.append(server)
            else:
                missing.append(sid)

    if missing:
        await update.message.reply_text(
            f"❌ 以下服务器未找到: {', '.join(missing)}\n"
            f"请先用 `/add_server` 添加。",
            parse_mode='Markdown'
        )
        return

    # 检查服务器是否有重复
    server_ids = [s.id for s in servers]
    if len(server_ids) != len(set(server_ids)):
        await update.message.reply_text("❌ 隧道中不能包含重复的服务器！", parse_mode='Markdown')
        return

    # 开始创建隧道
    await update.message.reply_text(f"⏳ 正在创建隧道 *{tunnel_name}*...", parse_mode='Markdown')

    results = []
    errors = []

    with session_scope() as session:
        # 创建隧道记录
        tunnel = Tunnel(
            name=tunnel_name,
            protocol=protocol,
            port=port,
            is_active=False
        )
        session.add(tunnel)
        session.flush()
        tunnel_id = tunnel.id

        # 按顺序创建节点
        for i, server in enumerate(servers):
            # 重新加载 server 对象
            srv = session.query(Server).filter(Server.id == server.id).first()

            if i == 0:
                role = 'entry'
            elif i == len(servers) - 1:
                role = 'exit'
            else:
                role = 'relay'

            service_name = f"tunnel_{tunnel_name}_node{i}"

            node = TunnelNode(
                tunnel_id=tunnel_id,
                server_id=srv.id,
                node_order=i,
                role=role,
                gost_service_name=service_name
            )
            session.add(node)

            results.append({
                'order': i,
                'server_name': srv.name,
                'server_ip': srv.ip,
                'role': role,
                'service_name': service_name,
                'server': srv,
            })

        session.flush()

        # 通过 API 在每台服务器上创建 gost 服务
        for i, r in enumerate(results):
            srv = session.query(Server).filter(Server.id == r['server'].id).first()
            client = get_server_api_client(srv)

            if r['role'] == 'entry':
                # 入口：监听端口 → 转发到下一跳
                next_server = results[i + 1]
                next_hop = f"{next_server['server_ip']}:{port}"
                success, data = await client.create_tunnel_entry(
                    service_name=r['service_name'],
                    port=port,
                    next_hop_addr=next_hop,
                    protocol=protocol
                )
            elif r['role'] == 'relay':
                # 中继：监听端口 → 转发到下一跳
                next_server = results[i + 1]
                next_hop = f"{next_server['server_ip']}:{port}"
                success, data = await client.create_tunnel_relay(
                    service_name=r['service_name'],
                    port=port,
                    next_hop_addr=next_hop,
                    protocol=protocol
                )
            else:
                # 出口：仅监听端口
                success, data = await client.create_tunnel_exit(
                    service_name=r['service_name'],
                    port=port,
                    protocol=protocol
                )

            if success:
                r['status'] = '✅'
            else:
                r['status'] = f'❌ {data}'
                errors.append(f"节点{i} ({srv.name}): {data}")

        # 如果全部成功，标记为活跃
        if not errors:
            tunnel.is_active = True

    # 构建结果消息
    chain_str = " → ".join([f"{r['server_name']}({r['role']})" for r in results])
    
    msg = (
        f"{'✅' if not errors else '⚠️'} 隧道 *{tunnel_name}* 创建{'完成' if not errors else '（部分失败）'}！\n\n"
        f"📝 协议: `{protocol}` | 端口: `{port}`\n"
        f"🔗 链路:\n{chain_str}\n\n"
    )

    for r in results:
        msg += f"  {r['status']} 节点{r['order']}: *{r['server_name']}* ({r['server_ip']}) — {r['role']}\n"

    if not errors:
        entry_server = results[0]
        msg += f"\n🎯 连接入口: `{entry_server['server_ip']}:{port}`"

    await update.message.reply_text(msg, parse_mode='Markdown')


@admin_only
async def list_tunnels(update: Update, context: CallbackContext):
    """列出所有隧道"""
    with session_scope() as session:
        tunnels = session.query(Tunnel).all()

    if not tunnels:
        await update.message.reply_text("📭 暂无隧道。使用 `/create_tunnel` 创建。", parse_mode='Markdown')
        return

    lines = ["🔗 *隧道列表*\n"]
    for t in tunnels:
        active_emoji = "🟢" if t.is_active else "🔴"
        nodes = t.nodes
        chain = " → ".join([n.server.name for n in nodes]) if nodes else "无节点"
        lines.append(
            f"{active_emoji} *{t.name}* (ID:{t.id})\n"
            f"  协议: `{t.protocol}` | 端口: `{t.port}`\n"
            f"  节点数: {len(nodes)}\n"
            f"  链路: {chain}\n"
            f"  状态: {'运行中' if t.is_active else '已停止'}\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


@admin_only
async def tunnel_status(update: Update, context: CallbackContext):
    """查看隧道状态"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/tunnel_status <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        tunnel = session.query(Tunnel).filter(Tunnel.name == identifier).first()
        if not tunnel:
            try:
                tunnel = session.query(Tunnel).filter(Tunnel.id == int(identifier)).first()
            except ValueError:
                pass
        if not tunnel:
            await update.message.reply_text(f"❌ 未找到隧道 `{identifier}`", parse_mode='Markdown')
            return

        nodes = tunnel.nodes
        msg = (
            f"🔗 *隧道详情: {tunnel.name}*\n\n"
            f"协议: `{tunnel.protocol}`\n"
            f"端口: `{tunnel.port}`\n"
            f"状态: {'🟢 运行中' if tunnel.is_active else '🔴 已停止'}\n\n"
            f"*节点状态:*\n"
        )

        for node in nodes:
            server = node.server
            client = get_server_api_client(server)
            
            # 检查服务状态
            svc_ok, svc_data = await client.get_service(node.gost_service_name)
            if svc_ok:
                node_status = "🟢 运行中"
            else:
                # 再尝试连接测试
                conn_ok, _ = await client.test_connection()
                node_status = "🟢 运行中" if conn_ok else "🔴 离线"

            msg += (
                f"  {node_status} 节点{node.node_order}: *{server.name}* ({server.ip})\n"
                f"    角色: {node.role} | 服务: `{node.gost_service_name}`\n"
            )

    await update.message.reply_text(msg, parse_mode='Markdown')


@admin_only
async def start_tunnel(update: Update, context: CallbackContext):
    """启动隧道"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/start_tunnel <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        tunnel = session.query(Tunnel).filter(Tunnel.name == identifier).first()
        if not tunnel:
            try:
                tunnel = session.query(Tunnel).filter(Tunnel.id == int(identifier)).first()
            except ValueError:
                pass
        if not tunnel:
            await update.message.reply_text(f"❌ 未找到隧道 `{identifier}`", parse_mode='Markdown')
            return

        if tunnel.is_active:
            await update.message.reply_text(f"⚠️ 隧道 *{tunnel.name}* 已在运行中。", parse_mode='Markdown')
            return

        nodes = tunnel.nodes
        if not nodes or len(nodes) < 2:
            await update.message.reply_text("❌ 隧道至少需要2个节点！", parse_mode='Markdown')
            return

        await update.message.reply_text(f"⏳ 正在启动隧道 *{tunnel.name}*...", parse_mode='Markdown')

        errors = []
        for i, node in enumerate(nodes):
            server = node.server
            client = get_server_api_client(server)

            # 先检查连接
            conn_ok, _ = await client.test_connection()
            if not conn_ok:
                errors.append(f"节点{i} ({server.name}): 无法连接")
                continue

            if node.role == 'entry':
                next_server = nodes[i + 1].server
                next_hop = f"{next_server.ip}:{tunnel.port}"
                success, data = await client.create_tunnel_entry(
                    service_name=node.gost_service_name,
                    port=tunnel.port,
                    next_hop_addr=next_hop,
                    protocol=tunnel.protocol
                )
            elif node.role == 'relay':
                next_server = nodes[i + 1].server
                next_hop = f"{next_server.ip}:{tunnel.port}"
                success, data = await client.create_tunnel_relay(
                    service_name=node.gost_service_name,
                    port=tunnel.port,
                    next_hop_addr=next_hop,
                    protocol=tunnel.protocol
                )
            else:  # exit
                success, data = await client.create_tunnel_exit(
                    service_name=node.gost_service_name,
                    port=tunnel.port,
                    protocol=tunnel.protocol
                )

            if not success:
                errors.append(f"节点{i} ({server.name}): {data}")

        if not errors:
            tunnel.is_active = True
            entry = nodes[0].server
            await update.message.reply_text(
                f"✅ 隧道 *{tunnel.name}* 已启动！\n\n"
                f"🎯 入口: `{entry.ip}:{tunnel.port}`\n"
                f"🔗 协议: `{tunnel.protocol}`",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"⚠️ 隧道 *{tunnel.name}* 启动部分失败！\n\n"
                f"错误:\n" + "\n".join([f"  ❌ {e}" for e in errors]),
                parse_mode='Markdown'
            )


@admin_only
async def stop_tunnel(update: Update, context: CallbackContext):
    """停止隧道"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/stop_tunnel <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        tunnel = session.query(Tunnel).filter(Tunnel.name == identifier).first()
        if not tunnel:
            try:
                tunnel = session.query(Tunnel).filter(Tunnel.id == int(identifier)).first()
            except ValueError:
                pass
        if not tunnel:
            await update.message.reply_text(f"❌ 未找到隧道 `{identifier}`", parse_mode='Markdown')
            return

        nodes = tunnel.nodes
        errors = []

        for node in nodes:
            server = node.server
            client = get_server_api_client(server)
            success, data = await client.delete_service(node.gost_service_name)
            if not success:
                errors.append(f"节点{node.node_order} ({server.name}): {data}")

        if not errors:
            tunnel.is_active = False
            await update.message.reply_text(f"✅ 隧道 *{tunnel.name}* 已停止。", parse_mode='Markdown')
        else:
            tunnel.is_active = False
            await update.message.reply_text(
                f"⚠️ 隧道 *{tunnel.name}* 停止部分失败！\n\n"
                f"错误:\n" + "\n".join([f"  ❌ {e}" for e in errors]),
                parse_mode='Markdown'
            )


@admin_only
async def del_tunnel(update: Update, context: CallbackContext):
    """删除隧道"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/del_tunnel <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        tunnel = session.query(Tunnel).filter(Tunnel.name == identifier).first()
        if not tunnel:
            try:
                tunnel = session.query(Tunnel).filter(Tunnel.id == int(identifier)).first()
            except ValueError:
                pass
        if not tunnel:
            await update.message.reply_text(f"❌ 未找到隧道 `{identifier}`", parse_mode='Markdown')
            return

        # 先尝试清理远程服务
        nodes = tunnel.nodes
        for node in nodes:
            server = node.server
            client = get_server_api_client(server)
            await client.delete_service(node.gost_service_name)

        name = tunnel.name
        session.delete(tunnel)

    await update.message.reply_text(f"✅ 隧道 *{name}* 已删除。", parse_mode='Markdown')