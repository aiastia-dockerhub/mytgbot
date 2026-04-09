"""用户相关数据库操作"""
import logging
from datetime import datetime
from typing import Optional, List, Dict

from database.connection import get_db

logger = logging.getLogger(__name__)


def add_user(user_id: int, username: str = "", added_by: int = 0, notes: str = "") -> bool:
    """添加用户到白名单"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """INSERT INTO users (user_id, username, status, added_by, notes, registered_at, updated_at)
               VALUES (?, ?, 'active', ?, ?, ?, ?)""",
            (user_id, username, added_by, notes, now, now)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("添加用户失败: %s", e)
        return False
    finally:
        conn.close()


def remove_user(user_id: int) -> bool:
    """移除用户"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def ban_user(user_id: int) -> bool:
    """封禁用户"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE users SET status = 'banned', updated_at = ? WHERE user_id = ?",
            (now, user_id)
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def unban_user(user_id: int) -> bool:
    """解封用户"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE users SET status = 'active', updated_at = ? WHERE user_id = ?",
            (now, user_id)
        )
        conn.commit()
        return conn.total_changes > 0
    finally:
        conn.close()


def get_user(user_id: int) -> Optional[Dict]:
    """获取用户信息"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_users() -> List[Dict]:
    """获取所有活跃用户"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = 'active' ORDER BY user_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_users() -> List[Dict]:
    """获取所有用户"""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY user_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_user_status(user_id: int, status: str):
    """更新用户状态"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE user_id = ?",
            (status, now, user_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_user_count() -> Dict:
    """获取用户统计"""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
        active = conn.execute("SELECT COUNT(*) as c FROM users WHERE status = 'active'").fetchone()['c']
        banned = conn.execute("SELECT COUNT(*) as c FROM users WHERE status = 'banned'").fetchone()['c']
        return {'total': total, 'active': active, 'banned': banned}
    finally:
        conn.close()