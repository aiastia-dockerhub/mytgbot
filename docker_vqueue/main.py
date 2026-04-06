"""视频队列分发 Bot - 入口文件"""
import logging

from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler,
    MessageHandler, filters
)

from config import BOT_TOKEN
from database import init_db
from handlers import (
    cmd_start, cmd_stop, cmd_resume, cmd_status, cmd_stats,
    handle_video, handle_photo, handle_media_group
)
from scheduler import setup_jobs

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.INFO)
logging.getLogger('telegram').setLevel(logging.INFO)

logger = logging.getLogger(__name__)


async def error_handler(update: object, context):
    """全局错误处理"""
    logger.error("===== 全局错误 =====")
    logger.error("错误: %s", context.error, exc_info=True)

    if update and hasattr(update, 'effective_message') and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ 处理请求时发生错误，请稍后重试。")
        except Exception:
            pass


async def post_init(application):
    """Bot 初始化后注册命令"""
    commands = [
        ("start", "注册 / 查看帮助"),
        ("stop", "暂停接收视频"),
        ("resume", "恢复接收视频"),
        ("status", "查看你的状态"),
        ("stats", "管理员统计"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot 已初始化，注册了 %d 个命令", len(commands))


def main():
    if not BOT_TOKEN:
        print("❌ 错误: 未设置 BOT_TOKEN 环境变量")
        return

    init_db()
    logger.info("视频队列分发 Bot 启动中...")

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # 命令处理器
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("stats", cmd_stats))

    # 媒体组处理（优先匹配，因为有 media_group_id）
    application.add_handler(MessageHandler(
        filters.VIDEO | filters.PHOTO,
        _handle_media
    ))

    # 全局错误处理
    application.add_error_handler(error_handler)

    # 注册定时任务
    setup_jobs(application)

    logger.info("Bot 已启动，开始轮询消息...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


async def _handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一媒体入口：根据是否有 media_group_id 分发"""
    msg = update.message
    if not msg:
        return

    if msg.media_group_id:
        await handle_media_group(update, context)
    elif msg.video or (msg.document and msg.document.mime_type and msg.document.mime_type.startswith('video/')):
        await handle_video(update, context)
    elif msg.photo:
        await handle_photo(update, context)


if __name__ == '__main__':
    main()