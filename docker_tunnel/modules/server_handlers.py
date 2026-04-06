"""
服务器管理命令处理
"""
import logging
import secrets
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from db.database import session_scope
from db.models import Server
from modules.admin import admin_only
from modules.gost_api import GostAPIClient
from config import encrypt_value, decrypt_value, GOST_DEFAULT_API_PORT

logger = logging.getLogger(__name__)


def generate_password(length: int = 32) -> str:
    """生成强随机密码"""
    alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
    while True:
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        # 确保包含至少一个大写、小写、数字和特殊字符
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in '!@#$%^&*' for c in password)
        if has_upper and has_lower and has_digit and has_special:
            return password


def generate_username() -> str:
    """生成随机用户名"""
    hex_part = secrets.token_hex(3)  # 6位hex
    return f"gost_{hex_part}"


def get_server_api_client(server: Server) -> GostAPIClient:
    """从 Server 模型创建 GostAPIClient"""
    return GostAPIClient(
        ip=server.ip,
        api_port=server.api_port,
        api_user=server.api_user,
        api_password=decrypt_value(server.api_password_encrypted)
    )


@admin_only
async def add_server(update: Update, context: CallbackContext):
    """
    添加服务器
    
    用法:
    /add_server <名称> <IP> [API端口]
    /add_server <名称> <IP> <API用户名> <API密码> [API端口]
    """
    args = context.args or []
    
    if len(args) < 2:
        await update.message.reply_text(
            "📋 *添加服务器*\n\n"
            "用法:\n"
            "`/add_server <名称> <IP>` — 自动生成 API 密码\n"
            "`/add_server <名称> <IP> <API端口>` — 指定端口\n"
            "`/add_server <名称> <IP> <用户名> <密码> [端口]` — 自定义认证\n\n"
            "示例:\n"
            "`/add_server 我的VPS 1.2.3.4`\n"
            "`/add_server 我的VPS 1.2.3.4 18080`\n"
            "`/add_server 我的VPS 1.2.3.4 myuser mypass`",
            parse_mode='Markdown'
        )
        return

    name = args[0]
    ip = args[1]

    # 检查是否已存在
    with session_scope() as session:
        existing = session.query(Server).filter(Server.name == name).first()
        if existing:
            await update.message.reply_text(f"❌ 服务器名称 `{name}` 已存在！", parse_mode='Markdown')
            return

    # 解析参数
    api_port = GOST_DEFAULT_API_PORT
    if len(args) == 3:
        # /add_server name ip port
        try:
            api_port = int(args[2])
        except ValueError:
            await update.message.reply_text("❌ API端口必须是数字！")
            return
    elif len(args) == 4:
        # /add_server name ip user pass
        api_user = args[2]
        api_password = args[3]
    elif len(args) >= 5:
        # /add_server name ip user pass port
        api_user = args[2]
        api_password = args[3]
        try:
            api_port = int(args[4])
        except ValueError:
            await update.message.reply_text("❌ API端口必须是数字！")
            return
    else:
        # 自动生成
        api_user = generate_username()
        api_password = generate_password()

    if 'api_user' not in dir():
        api_user = generate_username()
        api_password = generate_password()

    # 生成部署命令
    docker_cmd = (
        f"docker run -d --name gost --restart=always --net=host \\\n"
        f"  gogost/gost \\\n"
        f"  -api \"{api_user}:{api_password}@:{api_port}\""
    )

    # 保存到数据库
    encrypted_password = encrypt_value(api_password)
    with session_scope() as session:
        server = Server(
            name=name,
            ip=ip,
            api_port=api_port,
            api_user=api_user,
            api_password_encrypted=encrypted_password,
            status='offline'
        )
        session.add(server)
        session.flush()
        server_id = server.id

    await update.message.reply_text(
        f"✅ 服务器 *{name}* 已添加（待验证）\n\n"
        f"🚀 请在服务器 `{ip}` 上执行以下命令部署 gost：\n\n"
        f"```\n{docker_cmd}\n```\n\n"
        f"📌 API 认证信息：\n"
        f"  用户名: `{api_user}`\n"
        f"  密码: `{api_password}`\n"
        f"  API端口: `{api_port}`\n\n"
        f"部署完成后，发送 `/verify_server {name}` 验证连通性",
        parse_mode='Markdown'
    )


@admin_only
async def verify_server(update: Update, context: CallbackContext):
    """验证服务器连通性"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/verify_server <名称>`", parse_mode='Markdown')
        return

    name = args[0]
    with session_scope() as session:
        server = session.query(Server).filter(Server.name == name).first()
        if not server:
            # 尝试按 ID 查找
            try:
                server = session.query(Server).filter(Server.id == int(name)).first()
            except ValueError:
                pass
        if not server:
            await update.message.reply_text(f"❌ 未找到服务器 `{name}`", parse_mode='Markdown')
            return

        client = get_server_api_client(server)
        success, data = await client.test_connection()
        if success:
            server.status = 'online'
            await update.message.reply_text(
                f"✅ 服务器 *{name}* ({server.ip}) 连接成功！\n\n"
                f"当前 gost 配置:\n```\n{data}\n```",
                parse_mode='Markdown'
            )
        else:
            server.status = 'offline'
            await update.message.reply_text(
                f"❌ 服务器 *{name}* ({server.ip}) 连接失败！\n"
                f"错误: {data}\n\n"
                f"请确认已部署 gost 并开启 API。",
                parse_mode='Markdown'
            )


@admin_only
async def list_servers(update: Update, context: CallbackContext):
    """列出所有服务器"""
    with session_scope() as session:
        servers = session.query(Server).all()

    if not servers:
        await update.message.reply_text("📭 暂无服务器。使用 `/add_server` 添加。", parse_mode='Markdown')
        return

    lines = ["📋 *服务器列表*\n"]
    for s in servers:
        status_emoji = "🟢" if s.status == 'online' else "🔴"
        lines.append(
            f"{status_emoji} *{s.name}* (ID:{s.id})\n"
            f"  IP: `{s.ip}:{s.api_port}`\n"
            f"  状态: {s.status}\n"
            f"  添加时间: {s.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')


@admin_only
async def server_info(update: Update, context: CallbackContext):
    """查看服务器详情"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/server_info <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        server = session.query(Server).filter(Server.name == identifier).first()
        if not server:
            try:
                server = session.query(Server).filter(Server.id == int(identifier)).first()
            except ValueError:
                pass
        if not server:
            await update.message.reply_text(f"❌ 未找到服务器 `{identifier}`", parse_mode='Markdown')
            return

        # 实时检测状态
        client = get_server_api_client(server)
        success, data = await client.test_connection()
        server.status = 'online' if success else 'offline'

        status_emoji = "🟢" if server.status == 'online' else "🔴"
        password_masked = decrypt_value(server.api_password_encrypted)[:4] + "****"

        msg = (
            f"{status_emoji} *服务器详情*\n\n"
            f"名称: `{server.name}`\n"
            f"ID: {server.id}\n"
            f"IP: `{server.ip}`\n"
            f"API端口: {server.api_port}\n"
            f"API用户: `{server.api_user}`\n"
            f"API密码: `{password_masked}`\n"
            f"状态: {server.status}\n"
            f"备注: {server.remark or '无'}\n"
            f"创建时间: {server.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        if success:
            # 获取运行中的服务
            svc_ok, svc_data = await client.get_services()
            if svc_ok and svc_data:
                msg += f"\n📡 运行中的服务数: {len(svc_data) if isinstance(svc_data, list) else 1}"

    await update.message.reply_text(msg, parse_mode='Markdown')


@admin_only
async def del_server(update: Update, context: CallbackContext):
    """删除服务器"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/del_server <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        server = session.query(Server).filter(Server.name == identifier).first()
        if not server:
            try:
                server = session.query(Server).filter(Server.id == int(identifier)).first()
            except ValueError:
                pass
        if not server:
            await update.message.reply_text(f"❌ 未找到服务器 `{identifier}`", parse_mode='Markdown')
            return

        name = server.name
        session.delete(server)

    await update.message.reply_text(f"✅ 服务器 *{name}* 已删除。", parse_mode='Markdown')


@admin_only
async def check_server(update: Update, context: CallbackContext):
    """检查服务器连通性"""
    args = context.args or []
    if not args:
        await update.message.reply_text("用法: `/check_server <名称或ID>`", parse_mode='Markdown')
        return

    identifier = args[0]
    with session_scope() as session:
        server = session.query(Server).filter(Server.name == identifier).first()
        if not server:
            try:
                server = session.query(Server).filter(Server.id == int(identifier)).first()
            except ValueError:
                pass
        if not server:
            await update.message.reply_text(f"❌ 未找到服务器 `{identifier}`", parse_mode='Markdown')
            return

        client = get_server_api_client(server)
        
        # 测试连接
        success, data = await client.test_connection()
        server.status = 'online' if success else 'offline'

        if success:
            # 获取服务状态
            svc_ok, svc_data = await client.get_services_status()
            services_info = ""
            if svc_ok and svc_data:
                if isinstance(svc_data, list):
                    for svc in svc_data:
                        services_info += f"  • {svc.get('name', 'unknown')} - {svc.get('status', 'unknown')}\n"
                else:
                    services_info = f"  服务: {svc_data}\n"

            await update.message.reply_text(
                f"🟢 服务器 *{server.name}* ({server.ip}) 在线！\n\n"
                f"服务状态:\n{services_info or '  暂无运行中的服务'}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"🔴 服务器 *{server.name}* ({server.ip}) 离线！\n"
                f"错误: {data}",
                parse_mode='Markdown'
            )