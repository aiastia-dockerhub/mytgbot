"""数据库操作模块"""
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from config import DB_PATH
from models import UserStatus, QueueStatus

logger = logging.getLogger(__name__)


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                video_count_24h INTEGER DEFAULT 0,
                registered_at TEXT,
                last_active_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS video_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user_id INTEGER NOT NULL,
                from_username TEXT DEFAULT '',
                group_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_unique_id TEXT DEFAULT '',
                file_type TEXT NOT NULL DEFAULT 'video',
                caption TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                sent_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_vq_status ON video_queue(status);
            CREATE INDEX IF NOT EXISTS idx_vq_group ON video_queue(group_id);

            CREATE TABLE IF NOT EXISTS send_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'sent',
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sl_user ON send_log(to_user_id);
        ''')
        conn.commit()
        logger.info("数据库初始化完成")
    finally:
        conn.close()


# ===================== 用户操作 =====================

def register_user(user_id: int, username: str = "") -> bool:
    """注册或更新用户，返回是否为新用户"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = conn.execute(
            "SELECT status FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE users SET username = ?, last_active_at = ? WHERE user_id = ?",
                (username, now, user_id)
            )
            conn.commit()
            return False

        conn.execute(
            """INSERT INTO users (user_id, username, status, video_count_24h, registered_at, last_active_at, updated_at)
               VALUES (?, ?, ?, 0, ?, ?, ?)""",
            (user_id, username, UserStatus.ACTIVE, now, now, now)
        )
        conn.commit()
        return True
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


def get_active_users() -> List[Dict]:
    """获取所有活跃用户"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM users WHERE status = ? ORDER BY user_id",
            (UserStatus.ACTIVE,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def increment_video_count(user_id: int):
    """增加用户24h视频计数"""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET video_count_24h = video_count_24h + 1, last_active_at = ? WHERE user_id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        conn.commit()
    finally:
        conn.close()


def check_and_reset_24h_counts() -> List[int]:
    """检查24h活跃度，重置计数，返回需要系统停止的用户ID列表"""
    conn = get_db()
    try:
        now = datetime.now()
        cutoff = now - timedelta(hours=24)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

        # 找出不活跃的用户（24h内发送不足 MIN_VIDEOS_24H 个视频且当前为active）
        from config import MIN_VIDEOS_24H
        inactive_users = conn.execute(
            """SELECT user_id FROM users
               WHERE status = ? AND video_count_24h < ?""",
            (UserStatus.ACTIVE, MIN_VIDEOS_24H)
        ).fetchall()

        stopped_ids = []
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        for row in inactive_users:
            uid = row['user_id']
            # 检查注册时间是否超过24小时（新用户给24小时宽限期）
            user = conn.execute("SELECT registered_at FROM users WHERE user_id = ?", (uid,)).fetchone()
            if user and user['registered_at']:
                reg_time = datetime.strptime(user['registered_at'], "%Y-%m-%d %H:%M:%S")
                if reg_time > cutoff:
                    continue  # 新用户不足24小时，跳过

            conn.execute(
                "UPDATE users SET status = ?, video_count_24h = 0, updated_at = ? WHERE user_id = ?",
                (UserStatus.SYSTEM_STOPPED, now_str, uid)
            )
            stopped_ids.append(uid)

        # 重置所有用户的24h计数
        conn.execute("UPDATE users SET video_count_24h = 0")
        conn.commit()

        return stopped_ids
    finally:
        conn.close()


# ===================== 队列操作 =====================

def add_to_queue(from_user_id: int, from_username: str,
                 group_id: str, file_id: str, file_unique_id: str,
                 file_type: str, caption: str = "", sort_order: int = 0) -> bool:
    """添加媒体到队列"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO video_queue
               (from_user_id, from_username, group_id, file_id, file_unique_id,
                file_type, caption, sort_order, status, created_at, sent_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (from_user_id, from_username, group_id, file_id, file_unique_id,
             file_type, caption, sort_order, QueueStatus.PENDING, now)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("添加到队列失败: %s", e)
        return False
    finally:
        conn.close()


def get_next_pending_group() -> Optional[Dict]:
    """获取下一个待发送的组（返回组信息，包含所有媒体）"""
    conn = get_db()
    try:
        # 找到最早的一个pending组
        row = conn.execute(
            """SELECT group_id, from_user_id, from_username, MIN(created_at) as first_created
               FROM video_queue WHERE status = ? GROUP BY group_id
               ORDER BY first_created ASC LIMIT 1""",
            (QueueStatus.PENDING,)
        ).fetchone()

        if not row:
            return None

        group_id = row['group_id']

        # 获取该组的所有媒体
        items = conn.execute(
            """SELECT * FROM video_queue WHERE group_id = ? AND status = ?
               ORDER BY sort_order ASC, id ASC""",
            (group_id, QueueStatus.PENDING)
        ).fetchall()

        if not items:
            return None

        return {
            'group_id': group_id,
            'from_user_id': row['from_user_id'],
            'from_username': row['from_username'] or '',
            'items': [dict(r) for r in items]
        }
    finally:
        conn.close()


def update_queue_status(queue_ids: list, status: str):
    """更新队列项状态"""
    conn = get_db()
    try:
        placeholders = ','.join('?' * len(queue_ids))
        conn.execute(
            f"UPDATE video_queue SET status = ? WHERE id IN ({placeholders})",
            [status] + queue_ids
        )
        conn.commit()
    finally:
        conn.close()


def increment_sent_count(queue_ids: list):
    """增加已发送计数"""
    conn = get_db()
    try:
        placeholders = ','.join('?' * len(queue_ids))
        conn.execute(
            f"UPDATE video_queue SET sent_count = sent_count + 1 WHERE id IN ({placeholders})",
            queue_ids
        )
        conn.commit()
    finally:
        conn.close()


def log_send(queue_id: int, to_user_id: int, status: str = "sent"):
    """记录发送日志"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO send_log (queue_id, to_user_id, status, created_at) VALUES (?, ?, ?, ?)",
            (queue_id, to_user_id, status, now)
        )
        conn.commit()
    finally:
        conn.close()


def get_queue_stats() -> Dict:
    """获取队列统计"""
    conn = get_db()
    try:
        pending = conn.execute(
            "SELECT COUNT(DISTINCT group_id) as c FROM video_queue WHERE status = ?",
            (QueueStatus.PENDING,)
        ).fetchone()['c']

        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()['c']
        active_users = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE status = ?", (UserStatus.ACTIVE,)
        ).fetchone()['c']

        return {
            'pending_groups': pending,
            'total_users': total_users,
            'active_users': active_users,
        }
    finally:
        conn.close()