"""数据库操作模块"""
import sqlite3
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict

from config import DB_PATH, VIDEO_ROOT, VIDEO_EXTS

logger = logging.getLogger(__name__)


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                added_by INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                registered_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                reviewed_by INTEGER,
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS video_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                status TEXT DEFAULT 'unsend',
                sent_at TEXT,
                sent_count INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_vf_status ON video_files(status);
            CREATE INDEX IF NOT EXISTS idx_vf_path ON video_files(file_path);

            CREATE TABLE IF NOT EXISTS send_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                video_file_id INTEGER,
                file_path TEXT DEFAULT '',
                caption TEXT DEFAULT '',
                total_users INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'sending',
                created_at TEXT,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS send_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                send_log_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sd_log ON send_details(send_log_id);
        ''')
        conn.commit()
        logger.info("数据库初始化完成")
    finally:
        conn.close()


# ===================== 用户操作 =====================

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


# ===================== 加入请求操作 =====================

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


# ===================== 视频文件操作 =====================

def scan_video_files() -> Dict:
    """扫描视频目录，注册新文件到数据库，返回统计"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_count = 0
        total_count = 0

        for root, dirs, files in os.walk(VIDEO_ROOT):
            dirs.sort()
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in VIDEO_EXTS:
                    continue
                total_count += 1
                fpath = os.path.join(root, fname)
                fsize = os.path.getsize(fpath)

                existing = conn.execute(
                    "SELECT id FROM video_files WHERE file_path = ?", (fpath,)
                ).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO video_files (file_path, file_name, file_size, status, created_at)
                           VALUES (?, ?, ?, 'unsend', ?)""",
                        (fpath, fname, fsize, now)
                    )
                    new_count += 1

        conn.commit()
        return {'total': total_count, 'new': new_count}
    except Exception as e:
        logger.error("扫描视频文件失败: %s", e)
        return {'total': 0, 'new': 0}
    finally:
        conn.close()


def get_video_files(status: Optional[str] = None, subdir: Optional[str] = None,
                    page: int = 1, page_size: int = 20) -> Dict:
    """获取视频文件列表，支持分页和筛选"""
    conn = get_db()
    try:
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        if subdir:
            subdir_path = os.path.join(VIDEO_ROOT, subdir)
            conditions.append("file_path LIKE ?")
            params.append(f"{subdir_path}%")

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        # 总数
        total = conn.execute(
            f"SELECT COUNT(*) as c FROM video_files{where}", params
        ).fetchone()['c']

        # 分页数据
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM video_files{where} ORDER BY file_path ASC LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()

        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'items': [dict(r) for r in rows]
        }
    finally:
        conn.close()


def get_video_by_path(file_path: str) -> Optional[Dict]:
    """通过路径获取视频文件"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM video_files WHERE file_path = ?", (file_path,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_video_by_name(file_name: str) -> Optional[Dict]:
    """通过文件名获取视频文件（支持相对路径）"""
    conn = get_db()
    try:
        # 先尝试精确匹配 file_name
        row = conn.execute(
            "SELECT * FROM video_files WHERE file_name = ? LIMIT 1", (file_name,)
        ).fetchone()
        if row:
            return dict(row)

        # 尝试作为相对路径匹配
        full_path = os.path.join(VIDEO_ROOT, file_name)
        row = conn.execute(
            "SELECT * FROM video_files WHERE file_path = ? LIMIT 1", (full_path,)
        ).fetchone()
        if row:
            return dict(row)

        # 模糊匹配
        row = conn.execute(
            "SELECT * FROM video_files WHERE file_name LIKE ? OR file_path LIKE ? LIMIT 1",
            (f"%{file_name}%", f"%{file_name}%")
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_unsent_videos(limit: int = 10) -> List[Dict]:
    """获取未发送的视频"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM video_files WHERE status = 'unsend' ORDER BY file_path ASC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_videos_in_dir(subdir: str) -> List[Dict]:
    """获取指定子目录下的视频"""
    conn = get_db()
    try:
        subdir_path = os.path.join(VIDEO_ROOT, subdir)
        rows = conn.execute(
            "SELECT * FROM video_files WHERE file_path LIKE ? ORDER BY file_path ASC",
            (f"{subdir_path}%",)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_video_sent(video_file_id: int):
    """标记视频已发送"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE video_files SET status = 'sent', sent_at = ?, sent_count = sent_count + 1 WHERE id = ?",
            (now, video_file_id)
        )
        conn.commit()
    finally:
        conn.close()


def mark_video_unsent(video_file_id: int):
    """标记视频为未发送"""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE video_files SET status = 'unsend', sent_at = NULL WHERE id = ?",
            (video_file_id,)
        )
        conn.commit()
    finally:
        conn.close()


def get_video_stats() -> Dict:
    """获取视频统计"""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM video_files").fetchone()['c']
        sent = conn.execute("SELECT COUNT(*) as c FROM video_files WHERE status = 'sent'").fetchone()['c']
        unsent = conn.execute("SELECT COUNT(*) as c FROM video_files WHERE status = 'unsend'").fetchone()['c']
        total_size = conn.execute("SELECT COALESCE(SUM(file_size), 0) as s FROM video_files").fetchone()['s']
        return {'total': total, 'sent': sent, 'unsent': unsent, 'total_size': total_size}
    finally:
        conn.close()


def get_subdirs() -> List[Dict]:
    """获取所有子目录及视频数量"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT file_path FROM video_files ORDER BY file_path ASC"
        ).fetchall()

        dir_stats = {}
        for row in rows:
            fpath = row['file_path']
            rel_path = os.path.relpath(fpath, VIDEO_ROOT)
            dir_name = os.path.dirname(rel_path)
            if dir_name == '.':
                dir_name = '(根目录)'
            if dir_name not in dir_stats:
                dir_stats[dir_name] = 0
            dir_stats[dir_name] += 1

        result = [{'dir': d, 'count': c} for d, c in sorted(dir_stats.items())]
        return result
    finally:
        conn.close()


# ===================== 发送日志操作 =====================

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