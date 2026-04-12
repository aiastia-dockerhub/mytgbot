"""
TG Message Extractor Bot — 入口文件

模块结构：
    config.py      → 配置管理（环境变量、管理员ID）
    database.py    → 数据库操作（messages / user_status）
    patterns.py    → 正则提取 & bot 类型识别
    decorators.py  → 通用装饰器（admin_only）
    handlers.py    → 命令 & 消息处理器
"""
import logging
import sys

from telegram.ext import ApplicationBuilder

from config import BOT_TOKEN
from database import init_db
from handlers import register_all

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    if not BOT_TOKEN:
        print("错误：未设置 BOT_TOKEN 环境变量")
        return

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_all(app)

    logger.info("Bot 启动中...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        logger.exception("Bot 异常退出")
        sys.exit(1)