"""发送日志相关数据库操作"""
import logging
from datetime import datetime
from typing import Optional

from database.connection import get_db

logger = logging.getLogger(__name__)


def create_send_log(admin_user_id: int, video_file_id: Optional[int],
                    file_path: str, caption: str, total_users: int) -> int:
    """创建发送日志，返回日志ID"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            """INSERT INTO send_log (admin_user_id, video_file_id, file_path, caption,
               total_users, success_count, fail_count, status, created_at)
               VALUES (?, ?, ?, ?, ?, 0, 0, 'sending', ?)""",
            (admin_user_id, video_file_id, file_path, caption, total_users, now)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_send_log(log_id: int, success_count: int, fail_count: int, status: str = 'done'):
    """更新发送日志"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE send_log SET success_count = ?, fail_count = ?, status = ?, finished_at = ? WHERE id = ?",
            (success_count, fail_count, status, now, log_id)
        )
        conn.commit()
    finally:
        conn.close()


def log_send_detail(log_id: int, user_id: int, status: str):
    """记录发送明细"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO send_details (send_log_id, to_user_id, status, created_at) VALUES (?, ?, ?, ?)",
            (log_id, user_id, status, now)
        )
        conn.commit()
    finally:
        conn.close()