"""加密工具模块"""
import logging
from config import ENCRYPTION_KEY

logger = logging.getLogger(__name__)

fernet_cipher = None


def init_encryption():
    """初始化加密器"""
    global fernet_cipher
    if ENCRYPTION_KEY:
        try:
            from cryptography.fernet import Fernet
            fernet_cipher = Fernet(ENCRYPTION_KEY.encode())
            logger.info("加密器初始化成功")
        except Exception as e:
            logger.error("加密器初始化失败: %s", e)
            fernet_cipher = None
    else:
        logger.warning("未设置 ENCRYPTION_KEY，文件ID将明文存储")


def encrypt_file_id(file_id: str) -> str:
    """加密 file_id"""
    if fernet_cipher:
        try:
            return fernet_cipher.encrypt(file_id.encode()).decode()
        except Exception as e:
            logger.error("加密失败: %s", e)
    return file_id


def decrypt_file_id(encrypted: str) -> str:
    """解密 file_id"""
    if fernet_cipher:
        try:
            return fernet_cipher.decrypt(encrypted.encode()).decode()
        except Exception as e:
            logger.error("解密失败: %s", e)
    return encrypted