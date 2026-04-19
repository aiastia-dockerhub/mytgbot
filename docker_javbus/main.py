"""
JavBus 磁力搜索 Telegram Bot
通过 javbus-api 获取影片信息和磁力链接
"""
import asyncio
import logging
import sys
from telegram.ext import Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler

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
    codes_command,
    stop_command,
    button_callback,
)


async def post_init(application):
    """Bot 初始化后自动注册命令列表（让用户在输入框看到命令提示）"""
    commands = [
        ("jav", "查询影片磁力链接"),
        ("jav_star", "获取演员全部影片磁力"),
        ("jav_filter", "按类型筛选影片"),
        ("jav_search", "搜索影片"),
        ("movie", "查看影片详情"),
        ("star", "查看演员信息"),
        ("codes", "列出演员影片番号"),
        ("stop", "停止当前批量任务"),
        ("help", "查看帮助"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("已注册 %d 个 Telegram 命令", len(commands))


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
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ==================== 注册命令 ====================

    # 帮助
    application.add_handler(CommandHandler("start", help_command))
    application.add_handler(CommandHandler("help", help_command))

    # 停止任务
    application.add_handler(CommandHandler("stop", stop_command))

    # 按钮回调
    application.add_handler(CallbackQueryHandler(button_callback))

    # 磁力链接查询
    application.add_handler(CommandHandler("jav", jav_command))
    application.add_handler(CommandHandler("jav_star", jav_star_command))
    application.add_handler(CommandHandler("jav_filter", jav_filter_command))
    application.add_handler(CommandHandler("jav_search", jav_search_command))

    # 影片 & 演员详情
    application.add_handler(CommandHandler("movie", movie_command))
    application.add_handler(CommandHandler("star", star_command))
    application.add_handler(CommandHandler("codes", codes_command))

    # 全局错误处理
    async def error_handler(update: object, context: ContextTypes) -> None:
        """全局错误处理器，记录所有未捕获的异常"""
        logger.error("全局异常 (update=%s): %s", update, context.error, exc_info=context.error)
        # 尝试通知用户
        if update and hasattr(update, 'effective_message') and update.effective_message:
            try:
                await update.effective_message.reply_text(f"❌ Bot 内部错误，请联系管理员")
            except Exception:
                pass

    application.add_error_handler(error_handler)

    # 启动
    logger.info("JavBus Bot 已启动，开始轮询消息...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    if sys.platform.startswith('win'):
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()