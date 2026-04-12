"""数据库操作模块"""
import sqlite3
from contextlib import contextmanager
from typing import Optional

from config import DB_PATH


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


@contextmanager
def transaction():
    """事务上下文管理器"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params=()):
    """执行查询，返回所有行"""
    conn = _connect()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def query_one(sql: str, params=()):
    """执行查询，返回单行"""
    conn = _connect()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def execute(sql: str, params=()) -> None:
    """执行写操作（自动 commit）"""
    with transaction() as conn:
        conn.execute(sql, params)


def init_db() -> None:
    """初始化数据库表"""
    with transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            type TEXT,
            created_at TEXT,
            UNIQUE(user_id, content)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS user_status (
            user_id INTEGER PRIMARY KEY,
            last_send_time TEXT
        )""")
    print("数据库初始化完成")