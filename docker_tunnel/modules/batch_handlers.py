"""
批量操作命令处理
"""
import logging
import io
import csv
from telegram import Update
from telegram.ext import CallbackContext
from db.database import session_scope
from db.models import Server, Proxy
from modules.admin import admin_only
from modules.server_handlers import generate_username, generate_password, get_server_api_client
from modules.gost_api import GostAPIClient
from config import encrypt_value, decrypt_value, GOST_DEFAULT_API_PORT

# 用于存储等待文件上传的状态
_pending_batch_proxy = {}

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
        # 在 session 内提取数据
        server_data = []
        for s in servers:
            server_data.append({
                'id': s.id,
                'name': s.name,
                'ip': s.ip,
                'api_port': s.api_port,
                'api_user': s.api_user,
                'api_password_encrypted': s.api_password_encrypted,
            })

    if not server_data:
        await update.message.reply_text("📭 暂无服务器。", parse_mode='Markdown')
        return

    await update.message.reply_text(f"⏳ 正在检查 {len(server_data)} 台服务器...")

    results = []
    for sd in server_data:
        # 构建临时 Server 对象用于 API 客户端
        from config import decrypt_value
        client = GostAPIClient(
            ip=sd['ip'],
            api_port=sd['api_port'],
            api_user=sd['api_user'],
            api_password=decrypt_value(sd['api_password_encrypted'])
        )
        success, data = await client.test_connection()

        with session_scope() as session:
            srv = session.query(Server).filter(Server.id == sd['id']).first()
            if srv:
                srv.status = 'online' if success else 'offline'

        if success:
            # 获取服务数
            svc_ok, svc_data = await client.get_services()
            svc_count = 0
            if svc_ok and isinstance(svc_data, list):
                svc_count = len(svc_data)
            results.append(f"🟢 *{sd['name']}* ({sd['ip']}) — 在线 | 服务数: {svc_count}")
        else:
            results.append(f"🔴 *{sd['name']}* ({sd['ip']}) — 离线")

    msg = "📡 *服务器状态检查*\n\n" + "\n".join(results)
    await update.message.reply_text(msg, parse_mode='Markdown')


async def _do_batch_create_proxy(server_name: str, proxy_lines: list, update: Update):
    """
    批量创建代理的内部实现
    
    proxy_lines 格式（每行）:
    - 目标IP,目标端口           → 自动分配本地端口，协议 tcp
    - 目标IP,目标端口,本地端口   → 指定本地端口
    - 目标IP,目标端口,本地端口,协议
    """
    results = []
    success_count = 0
    fail_count = 0

    with session_scope() as session:
        server = session.query(Server).filter(Server.name == server_name).first()
        if not server:
            try:
                server = session.query(Server).filter(Server.id == int(server_name)).first()
            except ValueError:
                pass
        if not server:
            await update.message.reply_text(f"❌ 未找到服务器 `{server_name}`", parse_mode='Markdown')
            return

        server_id = server.id
        server_ip = server.ip
        server_name_actual = server.name

        # 获取当前服务器上已用的端口
        existing_proxies = session.query(Proxy).filter(Proxy.server_id == server_id).all()
        used_ports = set(p.listen_port for p in existing_proxies)

        # 找最大端口，用于自动分配
        max_port = max(used_ports) if used_ports else 10000

    await update.message.reply_text(
        f"⏳ 正在服务器 *{server_name_actual}* 上批量创建 {len(proxy_lines)} 个转发...",
        parse_mode='Markdown'
    )

    with session_scope() as session:
        server = session.query(Server).filter(Server.id == server_id).first()
        client = get_server_api_client(server)

        for line_num, line in enumerate(proxy_lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = [p.strip() for p in line.split(',')]
            if len(parts) < 2:
                results.append(f"❌ 第{line_num}行 格式错误: `{line}`")
                fail_count += 1
                continue

            target_ip = parts[0]
            try:
                target_port = int(parts[1])
            except ValueError:
                results.append(f"❌ 第{line_num}行 端口错误: `{parts[1]}`")
                fail_count += 1
                continue

            # 本地监听端口
            if len(parts) >= 3:
                try:
                    listen_port = int(parts[2])
                except ValueError:
                    listen_port = None
            else:
                listen_port = None

            # 协议（默认 tcp 转发）
            protocol = parts[3] if len(parts) >= 4 else 'tcp'

            # 自动分配端口
            if listen_port is None:
                max_port = max(max_port + 1, target_port)
                # 避免端口冲突：检查已用端口和 gost 远程端口
                while max_port in used_ports:
                    max_port += 1
                listen_port = max_port
                used_ports.add(listen_port)

            # 检查端口冲突
            if listen_port in used_ports and listen_port != max_port:
                results.append(f"❌ 第{line_num}行 端口 {listen_port} 已被占用")
                fail_count += 1
                continue

            used_ports.add(listen_port)

            # 生成代理名称
            proxy_name = f"fwd_{target_ip}_{target_port}_to_{listen_port}"

            # 检查名称重复
            existing = session.query(Proxy).filter(
                Proxy.server_id == server_id,
                Proxy.name == proxy_name
            ).first()
            if existing:
                proxy_name = f"fwd_{target_ip}_{target_port}_to_{listen_port}_{line_num}"

            try:
                # 通过 gost API 创建 TCP 转发
                success, data = await client.create_forward_service(
                    name=proxy_name,
                    listen_port=listen_port,
                    target_addr=f"{target_ip}:{target_port}",
                    protocol=protocol
                )

                if success:
                    proxy = Proxy(
                        name=proxy_name,
                        server_id=server_id,
                        protocol=protocol,
                        listen_port=listen_port,
                        config_json=f'{{"target":"{target_ip}:{target_port}"}}',
                        is_active=True
                    )
                    session.add(proxy)
                    session.flush()
                    results.append(
                        f"✅ #{line_num} `{server_ip}:{listen_port}` → `{target_ip}:{target_port}` ({protocol})"
                    )
                    success_count += 1
                else:
                    results.append(f"❌ #{line_num} 创建失败: {data}")
                    fail_count += 1

            except Exception as e:
                results.append(f"❌ #{line_num} 错误: {str(e)}")
                fail_count += 1

    # 构建结果消息
    msg = (
        f"📊 *批量创建转发结果*\n"
        f"服务器: `{server_name_actual}` | 成功: {success_count} | 失败: {fail_count}\n\n"
        + "\n".join(results)
    )

    # 分段发送
    if len(msg) > 4000:
        await update.message.reply_text(
            f"📊 *批量创建转发结果*\n服务器: `{server_name_actual}` | 成功: {success_count} | 失败: {fail_count}\n\n"
            f"详细信息较长，正在分批发送...",
            parse_mode='Markdown'
        )
        chunk = ""
        for r in results:
            if len(chunk) + len(r) > 3500:
                await update.message.reply_text(chunk, parse_mode='Markdown')
                chunk = ""
            chunk += r + "\n"
        if chunk:
            await update.message.reply_text(chunk, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')


@admin_only
async def batch_create_proxies(update: Update, context: CallbackContext):
    """
    批量创建代理/转发
    
    用法1 - 直接文本:
    /batch_proxy <服务器名称>
    目标IP,目标端口
    目标IP,目标端口,本地端口
    
    用法2 - 上传文件:
    /batch_proxy <服务器名称>
    然后上传 .txt 文件，每行格式: 目标IP,目标端口[,本地端口,协议]
    """
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "📋 *批量创建转发*\n\n"
            "用法1 — 直接跟随目标:\n"
            "```\n"
            "/batch_proxy <服务器名称>\n"
            "目标IP,目标端口\n"
            "目标IP,目标端口,本地端口\n"
            "目标IP,目标端口,本地端口,协议\n"
            "```\n\n"
            "用法2 — 上传文件:\n"
            "1. 先发 `/batch_proxy <服务器名称>`\n"
            "2. 再上传 .txt 文件\n\n"
            "格式说明:\n"
            "• `目标IP,目标端口` — 自动分配本地端口\n"
            "• `目标IP,目标端口,本地端口` — 指定本地端口\n"
            "• `目标IP,目标端口,本地端口,tcp` — 指定协议\n\n"
            "示例:\n"
            "```\n"
            "/batch_proxy myserver\n"
            "8.8.8.8,80\n"
            "1.1.1.1,443,10443\n"
            "9.9.9.9,53,10053,udp\n"
            "```",
            parse_mode='Markdown'
        )
        return

    server_name = args[0]
    text = update.message.text

    # 检查是否跟随了目标行
    lines = text.split('\n')[1:]  # 去掉命令行
    target_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith('#')]

    if target_lines:
        # 直接在消息中包含了目标，立即执行
        await _do_batch_create_proxy(server_name, target_lines, update)
    else:
        # 没有跟随目标，等待用户上传文件
        user_id = update.effective_user.id
        _pending_batch_proxy[user_id] = {
            'server_name': server_name,
            'chat_id': update.effective_chat.id,
        }
        await update.message.reply_text(
            f"📁 请上传 .txt 文件，每行一个转发目标：\n\n"
            f"```\n"
            f"目标IP,目标端口\n"
            f"目标IP,目标端口,本地端口\n"
            f"目标IP,目标端口,本地端口,协议\n"
            f"```\n\n"
            f"服务器: `{server_name}`\n"
            f"💡 发送 /cancel 取消",
            parse_mode='Markdown'
        )


@admin_only
async def handle_proxy_file(update: Update, context: CallbackContext):
    """处理上传的代理批量文件"""
    user_id = update.effective_user.id

    # 检查是否在等待文件上传
    if user_id not in _pending_batch_proxy:
        return

    pending = _pending_batch_proxy.pop(user_id)
    server_name = pending['server_name']

    # 获取上传的文件
    doc = update.message.document
    if not doc:
        await update.message.reply_text("❌ 请上传文件。")
        return

    # 检查文件类型
    if not doc.file_name.endswith(('.txt', '.csv')):
        await update.message.reply_text("❌ 仅支持 .txt 或 .csv 文件！")
        return

    # 下载文件内容
    try:
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        content = bytes(file_bytes).decode('utf-8')
    except Exception as e:
        await update.message.reply_text(f"❌ 下载文件失败: {e}")
        return

    # 解析行
    lines = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]

    if not lines:
        await update.message.reply_text("❌ 文件内容为空！")
        return

    await update.message.reply_text(f"📄 已读取文件 `{doc.file_name}`，共 {len(lines)} 条记录。", parse_mode='Markdown')
    await _do_batch_create_proxy(server_name, lines, update)
