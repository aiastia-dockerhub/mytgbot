"""Handler 工具函数"""
from config import ADMIN_USER_ID


def is_admin(user_id: int) -> bool:
    """检查是否是管理员"""
    return user_id in ADMIN_USER_ID