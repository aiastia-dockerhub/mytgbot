import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 加载 .env 文件
env_path = Path('.env')
if env_path.exists():
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

# Bot Token
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

# 管理员ID列表
ADMIN_IDS = [int(x.strip()) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]

# JavBus API 地址
JAVBUS_API_URL = os.environ.get('JAVBUS_API_URL', '').rstrip('/')

# API 认证 Token（可选）
JAVBUS_AUTH_TOKEN = os.environ.get('JAVBUS_AUTH_TOKEN', '')

# 默认影片类型：normal(有码) / uncensored(无码)
DEFAULT_TYPE = os.environ.get('DEFAULT_TYPE', 'normal')

# 磁力链接排序方式：size / date
MAGNET_SORT_BY = os.environ.get('MAGNET_SORT_BY', 'size')

# 磁力链接排序方向：desc / asc
MAGNET_SORT_ORDER = os.environ.get('MAGNET_SORT_ORDER', 'desc')

# 并发请求数
MAX_CONCURRENT = int(os.environ.get('MAX_CONCURRENT', '10'))

# 单次搜索最大页数（防止一次拉太多）
MAX_PAGES = int(os.environ.get('MAX_PAGES', '20'))

# API 请求限速：每分钟最大请求数（防止 429）
RATE_LIMIT = int(os.environ.get('RATE_LIMIT', '10'))

logger.info(f"Config loaded. ADMIN_IDS: {ADMIN_IDS}, API: {JAVBUS_API_URL}")
