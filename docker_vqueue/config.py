"""配置文件"""
import os
from pathlib import Path

# 加载 .env 文件
env_path = Path('.env')
if env_path.exists():
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Bot 配置
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]

# 数据库
DB_PATH = './data/vqueue.db'

# 发送控制
SEND_CONCURRENCY = int(os.environ.get('SEND_CONCURRENCY', '10'))    # 并发发送用户数（同时发给N个用户）
BATCH_INTERVAL = float(os.environ.get('BATCH_INTERVAL', '1.0'))     # 每批发完后间隔（秒）
VIDEO_INTERVAL = int(os.environ.get('VIDEO_INTERVAL', '5'))         # 不同组之间间隔（秒）

# 转发保护（防止接收者转发/保存）
PROTECT_CONTENT = os.environ.get('PROTECT_CONTENT', 'true').lower() == 'true'

# 来源标注
SHOW_SOURCE = os.environ.get('SHOW_SOURCE', 'true').lower() == 'true'
SOURCE_FORMAT = os.environ.get('SOURCE_FORMAT', '👤 来源: {username} (ID: {user_id})')

# 24小时活跃度检查（每小时执行一次）
ACTIVE_CHECK_INTERVAL = int(os.environ.get('ACTIVE_CHECK_INTERVAL', '3600'))  # 秒
MIN_VIDEOS_24H = int(os.environ.get('MIN_VIDEOS_24H', '10'))

# 队列检查间隔
QUEUE_CHECK_INTERVAL = int(os.environ.get('QUEUE_CHECK_INTERVAL', '5'))  # 秒