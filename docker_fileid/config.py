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

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', '')
CODE_PREFIX = os.environ.get('CODE_PREFIX', '')  # 自定义代码前缀，默认使用 bot 用户名（不带@）

MAX_COLLECTION_FILES = 999
AUTO_SEND_INTERVAL = 5  # 秒
GROUP_SEND_SIZE = 10  # 每组最多10个
CODE_LENGTH = 32  # 随机码长度
DB_PATH = './data/fileid.db'

FILE_TYPE_MAP = {
    'photo': '🖼 图片',
    'video': '🎬 视频',
    'audio': '🎵 音频',
    'document': '📄 文档',
    'voice': '🎤 语音',
}

FILE_TYPE_PREFIX = {
    'photo': 'p',
    'video': 'v',
    'document': 'd',
    'audio': 'd',
    'voice': 'd',
}
