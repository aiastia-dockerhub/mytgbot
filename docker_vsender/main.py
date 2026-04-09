"""视频分发 Bot - 入口文件"""
import os
import logging

from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from telegram.request import HTTPXRequest

from config import (
    TOKEN, ADMIN_USER_ID, TELEGRAM_API_URL,
    CONNECT_TIMEOUT, READ_TIMEOUT, WRITE_TIMEOUT,
    POOL_TIMEOUT, MEDIA_WRITE_TIMEOUT
)
from database import init_db, scan_video_files
from handlers import (
    cmd_start, cmd_help, cmd_myid, cmd_status, cmd_request,
    cmd_adduser, cmd_removeuser, cmd_ban, cmd_unban,
    cmd_listusers, cmd_pending,
    cmd_reload, cmd_listvideos, cmd_listunsend, cmd_dirs,
    cmd_send, cmd_sendnext, cmd_senddir, cmd_markunsend, cmd_stats,
    handle_approval_callback, handle_listpage_callback, handle_senddir_callback
)

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    # 数据库初始化
    init_db()
    logger.info("数据库初始化完成")

    # 扫描视频目录
    result = scan_video_files()
    logger.info("视频扫描完成: %d 个文件, %d 个新增", result['total'], result['new'])

    logger.info("Admin User IDs: %s", ADMIN_USER_ID)

    # 构建 Application
    base_url = os.getenv('TELEGRAM_API_URL') or TELEGRAM_API_URL
    request = HTTPXRequest(
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        write_timeout=WRITE_TIMEOUT,
        pool_timeout=POOL_TIMEOUT,
        media_write_timeout=MEDIA_WRITE_TIMEOUT
    )
    builder = ApplicationBuilder().token(TOKEN).request(request)
    if base_url:
        builder.base_url(f"{base_url}/bot")
        builder.base_file_url(f"{base_url}/file/bot")
    application = builder.build()

    # 注册用户命令
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("myid", cmd_myid))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("request", cmd_request))

    # 管理员 - 用户管理命令
    application.add_handler(CommandHandler("adduser", cmd_adduser))
    application.add_handler(CommandHandler("removeuser", cmd_removeuser))
    application.add_handler(CommandHandler("ban", cmd_ban))
    application.add_handler(CommandHandler("unban", cmd_unban))
    application.add_handler(CommandHandler("listusers", cmd_listusers))
    application.add_handler(CommandHandler("pending", cmd_pending))

    # 管理员 - 视频发送命令
    application.add_handler(CommandHandler("send", cmd_send))
    application.add_handler(CommandHandler("sendnext", cmd_sendnext))
    application.add_handler(CommandHandler("senddir", cmd_senddir))
    application.add_handler(CommandHandler("listvideos", cmd_listvideos))
    application.add_handler(CommandHandler("listunsend", cmd_listunsend))
    application.add_handler(CommandHandler("dirs", cmd_dirs))
    application.add_handler(CommandHandler("markunsend", cmd_markunsend))
    application.add_handler(CommandHandler("reload", cmd_reload))
    application.add_handler(CommandHandler("stats", cmd_stats))

    # 回调处理器
    application.add_handler(CallbackQueryHandler(handle_approval_callback, pattern=r'^(approve|reject)_'))
    application.add_handler(CallbackQueryHandler(handle_listpage_callback, pattern=r'^(vpage|upage)_'))
    application.add_handler(CallbackQueryHandler(handle_senddir_callback, pattern=r'^(sendall|sendunsent|cancel)'))

    # 启动 Bot
    logger.info("Bot 启动中...")
    application.run_polling()


if __name__ == '__main__':
    main()