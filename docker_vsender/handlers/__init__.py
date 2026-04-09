"""命令和消息处理器 - 统一导出接口"""

# 工具函数
from handlers.utils import is_admin

# 通用命令
from handlers.common import (
    cmd_start, cmd_help, cmd_myid, cmd_status, cmd_request,
    handle_approval_callback
)

# 管理员 - 用户管理命令
from handlers.admin_users import (
    cmd_adduser, cmd_removeuser, cmd_ban, cmd_unban,
    cmd_listusers, cmd_pending
)

# 管理员 - 视频发送命令
from handlers.admin_videos import (
    cmd_reload, cmd_listvideos, cmd_listunsend, cmd_dirs,
    cmd_send, cmd_sendnext, cmd_senddir, cmd_markunsend, cmd_stats,
    handle_listpage_callback, handle_senddir_callback
)

__all__ = [
    # utils
    'is_admin',
    # common
    'cmd_start', 'cmd_help', 'cmd_myid', 'cmd_status', 'cmd_request',
    'handle_approval_callback',
    # admin_users
    'cmd_adduser', 'cmd_removeuser', 'cmd_ban', 'cmd_unban',
    'cmd_listusers', 'cmd_pending',
    # admin_videos
    'cmd_reload', 'cmd_listvideos', 'cmd_listunsend', 'cmd_dirs',
    'cmd_send', 'cmd_sendnext', 'cmd_senddir', 'cmd_markunsend', 'cmd_stats',
    'handle_listpage_callback', 'handle_senddir_callback',
]