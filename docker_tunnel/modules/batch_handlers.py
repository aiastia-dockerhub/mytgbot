"""
批量操作命令处理
"""
import logging
from telegram import Update
from telegram.ext import CallbackContext
from db.database import session_scope
from db.models import Server
from modules.admin import admin_only
from modules.server_handlers import generate_username, generate_password, get_server_api_client
from config import encrypt_value, GOST_DEFAULT_API_PORT

logger = logging.getLogger(__name__)


@admin_only
async def batch_add_servers(update: Update, context: CallbackContext):
    """
    批量添加服务器
    
    每行格式: 名称,IP[,端口,用户名,密码]
    端口、用户名、密码可选，不提供则自动生成
    """
    text = update.message.text
    # 去掉命令部分
    lines = text.split('\n')[1:]  # 第一行是命令

    if not lines:
        await update.message.reply_text(
            "📋 *批量添加服务器*\n\n"
            "用法: 回复或跟随以下格式（每行一个服务器）:\n\n"
            "```\n"
            "/batch_servers\n"
            "名称1,1.2.3.4\n"
            "名称2,2.3.4.5,18080\n"
            "名称3,3.4.5.6,18080,user,pass\n"
            "```\n\n"
            "格式: `名称,IP[,端口,用户名,密码]`",
            parse_mode='Markdown'
        )
        return

    results = []
    success_count = 0
    fail_count = 0

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 2:
            results.append(f"❌ 格式错误: `{line}`")
            fail_count += 1
            continue

        name = parts[0]
        ip = parts[1]

        if len(parts) >= 5:
            api_port = int(parts[2]) if parts[2] else GOST_DEFAULT_API_PORT
            api_user = parts[3]
            api_password = parts[4]
        elif len(parts) >= 4:
            api_port = GOST_DEFAULT_API_PORT
            api_user = parts[2]
            api_password = parts[3]
        elif len(parts) >= 3:
            try:
                api_port = int(parts[2])
                api_user = generate_username()
                api_password = generate_password()
            except ValueError:
                api_port = GOST_DEFAULT_API_PORT
                api_user = parts[2]
                api_password = generate_password()
        else:
            api_port = GOST_DEFAULT_API_PORT
            api_user = generate_username()
            api_password = generate_password()

        try:
            with session_scope() as session:
                existing = session.query(Server).filter(Server.name == name).first()
                if existing:
                    results.append(f"❌ `{name}` — 名称已存在")
                    fail_count += 1
                    continue

                encrypted_password = encrypt_value(api_password)
                server = Server(
                    name=name,
                    ip=ip,
                    api_port=api_port,
                    api_user=api_user,
                    api_password_encrypted=encrypted_password,
                    status='offline'
                )
                session.add(server)

            # 生成部署命令
            docker_cmd = f"docker run -d --name gost --restart=always --net=host gogost/gost -api \"{api_user}:{api_password}@:{api_port}\""
            results.append(f"✅ `{name}` ({ip}:{api_port})\n  `{api_user}:{api_password[:8]}...`\n  ```\n{docker_cmd}\n  ```")
            success_count += 1

        except Exception as e:
            results.append(f"❌ `{name}` — 错误: {str(e)}")
            fail_count += 1

    msg = (
        f"📊 *批量添加结果*\n"
        f"成功: {success_count} | 失败: {fail_count}\n\n"
        + "\n".join(results)
    )

    # 如果消息太长，分段发送
    if len(msg) > 4000:
        await update.message.reply_text(
            f"📊 *批量添加结果*\n成功: {success_count} | 失败: {fail_count}\n\n详细信息较长，正在分批发送...",
            parse_mode='Markdown'
        )
        chunk = ""
        for r in results:
            if len(chunk) + len(r) > 3500:
                await update.message.reply_text(chunk, parse_mode='Markdown')
                chunk = ""
            chunk += r + "\n\n"
        if chunk:
            await update.message.reply_text(chunk, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')


@admin_only
async def batch_check_servers(update: Update, context: CallbackContext):
    """批量检查所有服务器状态"""
    with session_scope() as session:
        servers = session.query(Server).all()

    if not servers:
        await update.message.reply_text("📭 暂无服务器。", parse_mode='Markdown')
        return

    await update.message.reply_text(f"⏳ 正在检查 {len(servers)} 台服务器...")

    results = []
    for server in servers:
        client = get_server_api_client(server)
        success, data = await client.test_connection()

        with session_scope() as session:
            srv = session.query(Server).filter(Server.id == server.id).first()
            if srv:
                srv.status = 'online' if success else 'offline'

        if success:
            # 获取服务数
            svc_ok, svc_data = await client.get_services()
            svc_count = 0
            if svc_ok and isinstance(svc_data, list):
                svc_count = len(svc_data)
            results.append(f"🟢 *{server.name}* ({server.ip}) — 在线 | 服务数: {svc_count}")
        else:
            results.append(f"🔴 *{server.name}* ({server.ip}) — 离线")

    msg = "📡 *服务器状态检查*\n\n" + "\n".join(results)
    await update.message.reply_text(msg, parse_mode='Markdown')