"""加入请求相关数据库操作"""
import logging
from datetime import datetime
from typing import Optional, List, Dict

from database.connection import get_db

logger = logging.getLogger(__name__)


def add_join_request(user_id: int, username: str = "") -> Optional[int]:
    """添加加入请求，返回请求ID。如果已有待处理请求则返回None"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 检查是否已在白名单
        existing_user = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing_user:
            return None

        # 检查是否有待处理的请求
        pending = conn.execute(
            "SELECT id FROM join_requests WHERE user_id = ? AND status = 'pending'",
            (user_id,)
        ).fetchone()
        if pending:
            return None

        conn.execute(
            """INSERT INTO join_requests (user_id, username, status, created_at)
               VALUES (?, ?, 'pending', ?)""",
            (user_id, username, now)
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception as e:
        logger.error("添加加入请求失败: %s", e)
        return None
    finally:
        conn.close()


def get_pending_requests() -> List[Dict]:
    """获取所有待处理的请求"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM join_requests WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def approve_request(request_id: int, reviewed_by: int) -> Optional[Dict]:
    """批准请求，返回请求信息"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        req = conn.execute(
            "SELECT * FROM join_requests WHERE id = ? AND status = 'pending'",
            (request_id,)
        ).fetchone()
        if not req:
            return None

        req_dict = dict(req)
        # 更新请求状态
        conn.execute(
            "UPDATE join_requests SET status = 'approved', reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (reviewed_by, now, request_id)
        )
        # 添加用户到白名单
        conn.execute(
            """INSERT OR IGNORE INTO users (user_id, username, status, added_by, registered_at, updated_at)
               VALUES (?, ?, 'active', ?, ?, ?)""",
            (req_dict['user_id'], req_dict['username'], reviewed_by, now, now)
        )
        conn.commit()
        return req_dict
    except Exception as e:
        logger.error("批准请求失败: %s", e)
        return None
    finally:
        conn.close()


def reject_request(request_id: int, reviewed_by: int) -> Optional[Dict]:
    """拒绝请求，返回请求信息"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        req = conn.execute(
            "SELECT * FROM join_requests WHERE id = ? AND status = 'pending'",
            (request_id,)
        ).fetchone()
        if not req:
            return None

        req_dict = dict(req)
        conn.execute(
            "UPDATE join_requests SET status = 'rejected', reviewed_by = ?, reviewed_at = ? WHERE id = ?",
            (reviewed_by, now, request_id)
        )
        conn.commit()
        return req_dict
    except Exception as e:
        logger.error("拒绝请求失败: %s", e)
        return None
    finally:
        conn.close()