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


@admin_only
async def create_proxy(update: Update, context: CallbackContext):
    """
    创建代理服务（单服务器模式）
    
    用法:
    /create_proxy <代理名称> <服务器名称> <协议> <端口> [用户名 密码]
    """
    args = context.args or []

    if len(args) < 3:
        protocols_list = "\n".join([f"  `{k}` — {v}" for k, v in PROXY_PROTOCOLS.items()])
        await update.message.reply_text(
            "📋 *创建代理服务*\n\n"
            "用法:\n"
            "`/create_proxy <名称> <服务器> <协议> [端口]`\n\n"
            f"支持协议:\n{protocols_list}\n\n"
            "示例:\n"
            "`/create_proxy myproxy server1 socks5 1080`\n"
            "`/create_proxy myproxy server1 ss 8388`",
            parse_mode='Markdown'
        )
        return

    proxy_name = args[0]
    server_identifier = args[1]
    protocol = args[2].lower()
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

        # 通过 API 创建代理
        client = get_server_api_client(server)
        success, data = await client.create_proxy_service(
            name=proxy_name,
            protocol=protocol,
            port=port
        )

        if success:
            proxy = Proxy(
                name=proxy_name,
                server_id=server.id,
                protocol=protocol,
                listen_port=port,
                config_json=json.dumps(data) if data else '',
                is_active=True
            )
            session.add(proxy)

            await update.message.reply_text(
                f"✅ 代理服务创建成功！\n\n"
                f"📝 名称: `{proxy_name}`\n"
                f"🖥 服务器: `{server.name}` ({server.ip})\n"
                f"📡 协议: `{protocol}`\n"
                f"🔌 端口: `{port}`\n\n"
                f"连接信息: `{server.ip}:{port}`",
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

    if not proxies:
        await update.message.reply_text("📭 暂无代理服务。使用 `/create_proxy` 创建。", parse_mode='Markdown')
        return

    lines = ["📋 *代理列表*\n"]
    for p in proxies:
        with session_scope() as s:
            server = s.query(Server).filter(Server.id == p.server_id).first()
            server_name = server.name if server else '未知'
            server_ip = server.ip if server else '未知'

        active_emoji = "🟢" if p.is_active else "🔴"
        lines.append(
            f"{active_emoji} *{p.name}* (ID:{p.id})\n"
            f"  服务器: `{server_name}` ({server_ip})\n"
            f"  协议: `{p.protocol}` | 端口: `{p.listen_port}`\n"
            f"  状态: {'运行中' if p.is_active else '已停止'}\n"
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
            success, data = await client.create_proxy_service(
                name=proxy.name,
                protocol=proxy.protocol,
                port=proxy.listen_port
            )
            if success:
                proxy.is_active = True
                await update.message.reply_text(
                    f"✅ 代理 *{proxy.name}* 已启动！\n"
                    f"连接: `{server.ip}:{proxy.listen_port}`",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(f"❌ 启动代理失败: {data}", parse_mode='Markdown')