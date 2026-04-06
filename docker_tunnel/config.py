import os
from pathlib import Path
from cryptography.fernet import Fernet
import base64
import hashlib
import logging

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

# 数据库路径
DATABASE_PATH = os.environ.get('DATABASE_PATH', './data/tunnel.db')

# 加密密钥（用于加密存储 API 密码）
_enc_key_raw = os.environ.get('ENCRYPTION_KEY', 'default_encryption_key_change_me')
# 将任意长度的密钥转换为 Fernet 兼容的 32 字节 base64 密钥
_enc_key_bytes = hashlib.sha256(_enc_key_raw.encode()).digest()
ENCRYPTION_KEY = base64.urlsafe_b64encode(_enc_key_bytes)

def encrypt_value(plain_text: str) -> str:
    """加密文本"""
    f = Fernet(ENCRYPTION_KEY)
    return f.encrypt(plain_text.encode()).decode()

def decrypt_value(encrypted_text: str) -> str:
    """解密文本"""
    f = Fernet(ENCRYPTION_KEY)
    return f.decrypt(encrypted_text.encode()).decode()

# gost 相关配置
GOST_DEFAULT_API_PORT = 18080
GOST_DEFAULT_PROXY_PORT = 8080
GOST_DOCKER_IMAGE = "gogost/gost"
GOST_DOCKER_NAME = "gost"

logger.info(f"Config loaded. ADMIN_IDS: {ADMIN_IDS}")