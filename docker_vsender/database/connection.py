"""数据库连接管理"""
import sqlite3
import os
import logging

from config import DB_PATH

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