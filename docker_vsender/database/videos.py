"""视频文件相关数据库操作"""
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict

from config import VIDEO_ROOT, VIDEO_EXTS
from database.connection import get_db

logger = logging.getLogger(__name__)


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