"""数据模型和常量定义"""
from enum import Enum


class UserStatus(str, Enum):
    """用户状态"""
    ACTIVE = "active"              # 正常接收
    USER_STOPPED = "user_stopped"  # 用户主动停止
    SYSTEM_STOPPED = "system_stopped"  # 系统停止（拉黑/不活跃）


class QueueStatus(str, Enum):
    """队列状态"""
    PENDING = "pending"    # 等待发送
    SENDING = "sending"    # 正在发送中
    DONE = "done"          # 已发送完成


# 状态显示文案
STATUS_TEXT = {
    UserStatus.ACTIVE: "✅ 正常接收中",
    UserStatus.USER_STOPPED: "⏸️ 已暂停（你主动停止）",
    UserStatus.SYSTEM_STOPPED: "🚫 已停止（系统暂停，发送 /resume 恢复）",
}

# 24小时内需要发送的最少视频数，不足则系统停止
MIN_VIDEOS_24H = 10