"""数据库操作模块"""
import sqlite3
import logging
from datetime import datetime
from typing import Optional, List, Dict

from config import DB_PATH
from crypto import encrypt_file_id, decrypt_file_id

logger = logging.getLogger(__name__)


def get_db():
    """获取数据库连接（启用 WAL 模式和超时）"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS file_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                bot_username TEXT,
                file_type TEXT NOT NULL,
                telegram_file_id TEXT NOT NULL,
                encrypted_file_id TEXT,
                file_size INTEGER DEFAULT 0,
                file_unique_id TEXT,
                user_id INTEGER,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_file_code ON file_mappings(code);
            CREATE INDEX IF NOT EXISTS idx_file_user ON file_mappings(user_id);

            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                bot_username TEXT,
                name TEXT DEFAULT '',
                user_id INTEGER,
                file_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_col_code ON collections(code);
            CREATE INDEX IF NOT EXISTS idx_col_user ON collections(user_id);

            CREATE TABLE IF NOT EXISTS collection_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_code TEXT NOT NULL,
                file_code TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (collection_code) REFERENCES collections(code),
                FOREIGN KEY (file_code) REFERENCES file_mappings(code)
            );
            CREATE INDEX IF NOT EXISTS idx_ci_col ON collection_items(collection_code);
        ''')
        conn.commit()
        logger.info("数据库初始化完成")
    finally:
        conn.close()


def save_file(user_id: int, file_type: str, file_id: str,
              file_size: int, file_unique_id: str, bot_username: str,
              code_prefix: str) -> Optional[str]:
    """保存文件到数据库，返回完整代码"""
    import string, random
    from config import CODE_LENGTH

    conn = get_db()
    try:
        # 去重：如果同一 bot 下已存在相同 file_unique_id，直接返回已有代码
        if file_unique_id:
            existing = conn.execute(
                "SELECT code FROM file_mappings WHERE file_unique_id = ? AND bot_username = ?",
                (file_unique_id, bot_username)
            ).fetchone()
            if existing:
                logger.info("文件已存在，复用代码: %s (file_unique_id=%s)", existing['code'], file_unique_id)
                return existing['code']

        # 生成唯一代码
        chars = string.ascii_letters + string.digits
        while True:
            raw_code = ''.join(random.choices(chars, k=CODE_LENGTH))
            row = conn.execute(
                "SELECT id FROM file_mappings WHERE code = ? UNION SELECT id FROM collections WHERE code = ?",
                (raw_code, raw_code)
            ).fetchone()
            if not row:
                break

        from config import FILE_TYPE_PREFIX
        prefix = FILE_TYPE_PREFIX.get(file_type, 'd')
        full_code = f"{code_prefix}_{prefix}:{raw_code}"

        encrypted_fid = encrypt_file_id(file_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """INSERT INTO file_mappings 
               (code, bot_username, file_type, telegram_file_id, encrypted_file_id, file_size, file_unique_id, user_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (full_code, bot_username, file_type, file_id, encrypted_fid, file_size, file_unique_id, user_id, now)
        )
        conn.commit()
        return full_code
    except sqlite3.IntegrityError:
        logger.error("代码重复（极少发生）")
        return None
    except Exception as e:
        logger.error("保存文件失败: %s", e)
        return None
    finally:
        conn.close()


def get_file(code: str) -> Optional[Dict]:
    """根据代码获取文件信息"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM file_mappings WHERE code = ?", (code,)
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def get_collection(code: str) -> Optional[Dict]:
    """获取集合信息"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM collections WHERE code = ?", (code,)).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def get_collection_files(code: str) -> List[Dict]:
    """获取集合中的所有文件"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT fm.* FROM file_mappings fm
               JOIN collection_items ci ON fm.code = ci.file_code
               WHERE ci.collection_code = ?
               ORDER BY ci.sort_order""",
            (code,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_collection(code: str, bot_username: str, name: str, user_id: int) -> bool:
    """创建新集合"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO collections (code, bot_username, name, user_id, file_count, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, 'open', ?, ?)""",
            (code, bot_username, name, user_id, now, now)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("创建集合失败: %s", e)
        return False
    finally:
        conn.close()


def add_file_to_collection(col_code: str, file_code: str, sort_order: int) -> bool:
    """添加文件到集合"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO collection_items (collection_code, file_code, sort_order) VALUES (?, ?, ?)",
            (col_code, file_code, sort_order)
        )
        conn.execute(
            "UPDATE collections SET file_count = ?, updated_at = ? WHERE code = ?",
            (sort_order, now, col_code)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("添加文件到集合失败: %s", e)
        return False
    finally:
        conn.close()


def complete_collection(col_code: str, file_count: int) -> bool:
    """完成集合"""
    conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE collections SET status = 'completed', file_count = ?, updated_at = ? WHERE code = ?",
            (file_count, now, col_code)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("完成集合失败: %s", e)
        return False
    finally:
        conn.close()


def delete_collection(col_code: str) -> bool:
    """删除集合及其文件项"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM collection_items WHERE collection_code = ?", (col_code,))
        conn.execute("DELETE FROM collections WHERE code = ?", (col_code,))
        conn.commit()
        return True
    except Exception as e:
        logger.error("删除集合失败: %s", e)
        return False
    finally:
        conn.close()


def get_user_collections(user_id: int, limit: int = 20) -> List[Dict]:
    """获取用户集合列表"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT code, name, file_count, status, created_at FROM collections WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stats() -> Dict:
    """获取统计数据"""
    conn = get_db()
    try:
        file_count = conn.execute("SELECT COUNT(*) as c FROM file_mappings").fetchone()['c']
        col_count = conn.execute("SELECT COUNT(*) as c FROM collections").fetchone()['c']
        user_count = conn.execute("SELECT COUNT(DISTINCT user_id) as c FROM file_mappings").fetchone()['c']
        today = datetime.now().strftime("%Y-%m-%d")
        today_files = conn.execute(
            "SELECT COUNT(*) as c FROM file_mappings WHERE created_at LIKE ?", (f"{today}%",)
        ).fetchone()['c']
        type_stats = conn.execute(
            "SELECT file_type, COUNT(*) as c FROM file_mappings GROUP BY file_type"
        ).fetchall()
        return {
            'file_count': file_count,
            'col_count': col_count,
            'user_count': user_count,
            'today_files': today_files,
            'type_stats': [dict(r) for r in type_stats],
        }
    finally:
        conn.close()


def get_all_files_for_export() -> List[Dict]:
    """导出所有文件记录"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT code, file_type, file_size, user_id, created_at FROM file_mappings ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()