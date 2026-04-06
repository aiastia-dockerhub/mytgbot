"""FileID Bot - 入口文件"""
import logging

from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import BOT_TOKEN
from crypto import init_encryption
from database import init_db
from handlers_commands import (
    start_command, create_collection_cmd, done_collection_cmd,
    cancel_collection_cmd, get_id_command, my_collections_cmd,
    delete_collection_cmd, stats_command, export_command
)
from handlers_messages import (
    handle_attachment, handle_text, handle_forward,
    handle_group_media, handle_forwarded_media
)
from handlers_callbacks import button_callback

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
# 降低 httpx/httpcore 和 telegram.ext 日志级别，避免刷屏
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.INFO)
logging.getLogger('telegram').setLevel(logging.INFO)

logger = logging.getLogger(__name__)


async def error_handler(update: object, context):
    """全局错误处理"""
    logger.error("===== 全局错误处理器触发 =====")
    logger.error("错误类型: %s", type(context.error).__name__ if context.error else "Unknown")
    logger.error("错误详情: %s", context.error, exc_info=True)

    # 记录 update 信息
    if update:
        if hasattr(update, 'callback_query') and update.callback_query:
            cq = update.callback_query
            logger.error("来自回调: data=%s, user=%s, chat=%s",
                         cq.data,
                         cq.from_user.id if cq.from_user else None,
                         cq.message.chat_id if cq.message else None)
        elif hasattr(update, 'effective_message') and update.effective_message:
            logger.error("来自消息: chat_id=%s, text=%s",
                         update.effective_message.chat_id,
                         (update.effective_message.text or '')[:100])

    if update and hasattr(update, 'effective_message') and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ 处理请求时发生内部错误，请稍后重试。")
        except Exception as e2:
            logger.error("全局错误处理: 发送错误提示也失败: %s", e2)


async def post_init(application):
    """Bot 初始化后注册命令"""
    commands = [
        ("start", "开始使用 / 查看帮助"),
        ("help", "查看帮助"),
        ("create", "创建集合 create 名称"),
        ("done", "完成集合"),
        ("cancel", "取消当前操作"),
        ("getid", "回复消息获取文件ID"),
        ("mycol", "查看我的集合"),
        ("delcol", "删除集合 delcol 代码"),
        ("stats", "管理员统计"),
        ("export", "管理员导出"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot @%s 已初始化，注册了 %d 个命令", application.bot.username, len(commands))


def main():
    if not BOT_TOKEN:
        print("❌ 错误: 未设置 BOT_TOKEN 环境变量")
        return

    init_encryption()
    init_db()
    logger.info("FileID Bot 启动中...")

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # 命令处理器
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("create", create_collection_cmd))
    application.add_handler(CommandHandler("done", done_collection_cmd))
    application.add_handler(CommandHandler("cancel", cancel_collection_cmd))
    application.add_handler(CommandHandler("getid", get_id_command))
    application.add_handler(CommandHandler("mycol", my_collections_cmd))
    application.add_handler(CommandHandler("delcol", delete_collection_cmd))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("export", export_command))

    # 转发的媒体消息（优先级最高）
    application.add_handler(MessageHandler(
        filters.FORWARDED & (filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE),
        handle_forwarded_media
    ))

    # 转发的非媒体消息
    application.add_handler(MessageHandler(
        filters.FORWARDED & filters.TEXT & ~filters.COMMAND,
        handle_forward
    ))

    # 媒体组处理（非转发的媒体）
    application.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE,
        handle_group_media
    ))

    # 文本消息（代码解析）
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text
    ))

    # 回调按钮
    application.add_handler(CallbackQueryHandler(button_callback))

    # 全局错误处理
    application.add_error_handler(error_handler)

    logger.info("FileID Bot 已启动，开始轮询消息...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()