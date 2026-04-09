"""数据库操作模块 - 统一导出接口"""

# 连接管理
from database.connection import get_db, init_db

# 用户操作
from database.users import (
    add_user, remove_user, ban_user, unban_user, get_user,
    get_active_users, get_all_users, update_user_status, get_user_count
)

# 加入请求操作
from database.requests import (
    add_join_request, get_pending_requests, approve_request, reject_request
)

# 视频文件操作
from database.videos import (
    scan_video_files, get_video_files, get_video_by_path, get_video_by_name,
    get_unsent_videos, get_videos_in_dir, mark_video_sent, mark_video_unsent,
    get_video_stats, get_subdirs
)

# 发送日志操作
from database.send_log import (
    create_send_log, update_send_log, log_send_detail
)

__all__ = [
    # connection
    'get_db', 'init_db',
    # users
    'add_user', 'remove_user', 'ban_user', 'unban_user', 'get_user',
    'get_active_users', 'get_all_users', 'update_user_status', 'get_user_count',
    # requests
    'add_join_request', 'get_pending_requests', 'approve_request', 'reject_request',
    # videos
    'scan_video_files', 'get_video_files', 'get_video_by_path', 'get_video_by_name',
    'get_unsent_videos', 'get_videos_in_dir', 'mark_video_sent', 'mark_video_unsent',
    'get_video_stats', 'get_subdirs',
    # send_log
    'create_send_log', 'update_send_log', 'log_send_detail',
]