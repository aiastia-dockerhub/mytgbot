"""Sticker2Img Bot - 收到贴纸转为图片发送"""
import os
import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters
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
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()