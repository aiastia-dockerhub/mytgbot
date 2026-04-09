"""配置管理模块"""
import os
from dotenv import load_dotenv

load_dotenv()

# Bot Token
TOKEN = os.getenv('BOT_TOKEN')

# 管理员用户ID列表
ADMIN_USER_ID = [int(id) for id in os.getenv('ADMIN_USER_ID', '').split(',') if id.strip().isdigit()]

# 自定义 Telegram API URL（用于突破限制）
TELEGRAM_API_URL = os.getenv('TELEGRAM_API_URL')

# 本地视频目录
VIDEO_ROOT = os.getenv('VIDEO_ROOT', '/app/videos')

# 支持的视频格式
VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.ts', '.m4v', '.rmvb', '.rm'}

# 数据库路径
DB_PATH = os.getenv('DB_PATH', './data/vsender.db')

# 发送并发数
SEND_CONCURRENCY = int(os.getenv('SEND_CONCURRENCY', '5'))

# 批次间间隔（秒）
BATCH_INTERVAL = float(os.getenv('BATCH_INTERVAL', '1.0'))

# 视频间间隔（秒）
VIDEO_INTERVAL = float(os.getenv('VIDEO_INTERVAL', '3.0'))

# 列表每页显示数量
LIST_PAGE_SIZE = int(os.getenv('LIST_PAGE_SIZE', '20'))

# 超时配置
CONNECT_TIMEOUT = 60
READ_TIMEOUT = 1810
WRITE_TIMEOUT = 1810
POOL_TIMEOUT = 60
MEDIA_WRITE_TIMEOUT = 1810