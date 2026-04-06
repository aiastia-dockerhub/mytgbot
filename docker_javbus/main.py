"""
JavBus 磁力搜索 Telegram Bot
通过 javbus-api 获取影片信息和磁力链接
"""
import logging
import sys
from telegram.ext import Application, ApplicationBuilder, CommandHandler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 加载配置
from config import BOT_TOKEN, ADMIN_IDS, JAVBUS_API_URL

# 导入命令处理函数
from modules.handlers import (
    help_command,
    jav_command,
    jav_star_command,
    jav_filter_command,
    jav_search_command,
    movie_command,
    star_command,
)


def main():
    """启动 Bot"""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN 未设置！请在 .env 文件中配置。")
        return

    if not JAVBUS_API_URL:
        logger.critical("JAVBUS_API_URL 未设置！请在 .env 文件中配置你的 javbus-api 地址。")
        return

    logger.info("Bot 启动中... ADMIN_IDS: %s, API: %s", ADMIN_IDS, JAVBUS_API_URL)

    # 创建 Bot Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # ==================== 注册命令 ====================

    # 帮助
    application.add_handler(CommandHandler("start", help_command))
    application.add_handler(CommandHandler("help", help_command))

    # 磁力链接查询
    application.add_handler(CommandHandler("jav", jav_command))
    application.add_handler(CommandHandler("jav_star", jav_star_command))
    application.add_handler(CommandHandler("jav_filter", jav_filter_command))
    application.add_handler(CommandHandler("jav_search", jav_search_command))

    # 影片 & 演员详情
    application.add_handler(CommandHandler("movie", movie_command))
    application.add_handler(CommandHandler("star", star_command))

    # 启动
    logger.info("JavBus Bot 已启动，开始轮询消息...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    if sys.platform.startswith('win'):
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()