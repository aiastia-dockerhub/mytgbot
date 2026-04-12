"""Sticker2Img Bot - 收到贴纸转为图片发送"""
import os
import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

from handlers import handle_pack, handle_sticker

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def handle_mention_with_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """在群组中被 @提及时，检查 reply_to_message 是否包含贴纸

    支持隐私模式：Commander Bot 发送贴纸后 @提及本 bot，
    本 bot 收到 @mention 后通过 reply_to_message 获取贴纸并处理。
    """
    message = update.message

    # 检查是否是回复消息且被回复的消息包含贴纸
    if message.reply_to_message and message.reply_to_message.sticker:
        # 用被回复的贴纸消息调用 handle_sticker
        # handle_sticker 中 message.reply_photo 会回复到群组中的贴纸消息
        # Commander Bot 监控群组中 bot 的回复，从而转发结果给用户
        await handle_sticker(message.reply_to_message, context)


async def post_init(application):
    commands = [("start", "发送贴纸即可转为图片"), ("pack", "回复贴纸下载整个表情包")]
    await application.bot.set_my_commands(commands)
    logger.info("Bot @%s 已启动", application.bot.username)


def main():
    if not BOT_TOKEN:
        print("❌ 请设置 BOT_TOKEN 环境变量")
        return

    request = HTTPXRequest(connect_timeout=30.0, read_timeout=120.0, write_timeout=120.0)
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).request(request).build()
    app.add_handler(CommandHandler("pack", handle_pack))
    # 直接收到贴纸
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    # 在群组中被 @提及，且回复的消息是贴纸（支持隐私模式下通过 @mention 触发）
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUP & filters.TEXT & filters.Entity("mention") & filters.REPLY & ~filters.COMMAND,
            handle_mention_with_sticker,
        )
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()