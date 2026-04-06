"""命令和消息处理器"""
import uuid
import logging

from telegram import Update
from telegram.ext import ContextTypes

from database import (
    register_user, get_user, update_user_status,
    add_to_queue, increment_video_count, get_queue_stats
)
from models import UserStatus, STATUS_TEXT
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


# ===================== 命令处理 =====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start - 注册并启动"""
    user = update.effective_user
    is_new = register_user(user.id, user.username or "")

    if is_new:
        text = (
            "🎉 欢迎注册视频分发 Bot！\n\n"
            "📱 发送视频或照片给我，我会将它们排队分发给所有注册用户。\n\n"
            "📌 命令列表：\n"
            "/status - 查看你的状态\n"
            "/stop - 暂停接收\n"
            "/resume - 恢复接收\n"
            "/stats - 查看统计（管理员）"
        )
    else:
        # 如果用户已存在但可能状态不是active
        u = get_user(user.id)
        if u and u['status'] != UserStatus.ACTIVE:
            update_user_status(user.id, UserStatus.ACTIVE)
        text = "👋 欢迎回来！你已恢复接收状态。"

    await update.message.reply_text(text)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stop - 用户主动停止"""
    user_id = update.effective_user.id
    u = get_user(user_id)

    if not u:
        await update.message.reply_text("你还未注册，发送 /start 开始。")
        return

    update_user_status(user_id, UserStatus.USER_STOPPED)
    await update.message.reply_text("⏸️ 已暂停接收视频。发送 /resume 恢复。")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/resume - 恢复接收"""
    user_id = update.effective_user.id
    u = get_user(user_id)

    if not u:
        await update.message.reply_text("你还未注册，发送 /start 开始。")
        return

    update_user_status(user_id, UserStatus.ACTIVE)
    await update.message.reply_text("✅ 已恢复接收视频！")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status - 查看自己的状态"""
    user_id = update.effective_user.id
    u = get_user(user_id)

    if not u:
        await update.message.reply_text("你还未注册，发送 /start 开始。")
        return

    status = u['status']
    status_text = STATUS_TEXT.get(status, status)

    text = (
        f"📊 **你的状态**\n\n"
        f"状态：{status_text}\n"
        f"24h发送数：{u.get('video_count_24h', 0)}\n"
        f"注册时间：{u.get('registered_at', '未知')}\n"
        f"最后活跃：{u.get('last_active_at', '未知')}"
    )

    await update.message.reply_text(text)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats - 管理员统计"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ 仅管理员可用")
        return

    stats = get_queue_stats()
    text = (
        f"📈 **系统统计**\n\n"
        f"待发送队列：{stats['pending_groups']} 组\n"
        f"注册用户：{stats['total_users']} 人\n"
        f"活跃用户：{stats['active_users']} 人"
    )

    await update.message.reply_text(text)


# ===================== 媒体消息处理 =====================

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理单个视频消息"""
    user = update.effective_user
    msg = update.message

    # 确保用户已注册
    register_user(user.id, user.username or "")

    video = msg.video or msg.document  # 可能以文档形式发送
    if not video:
        return

    file_id = video.file_id
    file_unique_id = video.file_unique_id
    caption = msg.caption or ""

    group_id = str(uuid.uuid4())

    success = add_to_queue(
        from_user_id=user.id,
        from_username=user.username or "",
        group_id=group_id,
        file_id=file_id,
        file_unique_id=file_unique_id,
        file_type="video",
        caption=caption,
        sort_order=0
    )

    if success:
        increment_video_count(user.id)
        await msg.reply_text("✅ 视频已加入发送队列！")
        logger.info("用户 %s 添加视频到队列 (group: %s)", user.id, group_id)
    else:
        await msg.reply_text("❌ 添加队列失败，请重试。")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理单个照片消息"""
    user = update.effective_user
    msg = update.message

    register_user(user.id, user.username or "")

    # 取最大尺寸的照片
    photo = msg.photo[-1] if msg.photo else None
    if not photo:
        return

    file_id = photo.file_id
    file_unique_id = photo.file_unique_id
    caption = msg.caption or ""

    group_id = str(uuid.uuid4())

    success = add_to_queue(
        from_user_id=user.id,
        from_username=user.username or "",
        group_id=group_id,
        file_id=file_id,
        file_unique_id=file_unique_id,
        file_type="photo",
        caption=caption,
        sort_order=0
    )

    if success:
        increment_video_count(user.id)
        await msg.reply_text("✅ 照片已加入发送队列！")
        logger.info("用户 %s 添加照片到队列 (group: %s)", user.id, group_id)
    else:
        await msg.reply_text("❌ 添加队列失败，请重试。")


async def handle_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理媒体组（多张照片/视频）"""
    user = update.effective_user
    msg = update.message

    register_user(user.id, user.username or "")

    media_group_id = msg.media_group_id
    if not media_group_id:
        return

    group_id = media_group_id  # 用Telegram的media_group_id作为组ID

    # 收集本消息的媒体
    file_id = None
    file_unique_id = None
    file_type = None

    if msg.video:
        file_id = msg.video.file_id
        file_unique_id = msg.video.file_unique_id
        file_type = 'video'
    elif msg.photo:
        photo = msg.photo[-1]
        file_id = photo.file_id
        file_unique_id = photo.file_unique_id
        file_type = 'photo'

    if not file_id:
        return

    # 检查是否已添加过这个文件（避免重复）
    from database import get_db
    conn = get_db()
    try:
        dup = conn.execute(
            "SELECT id FROM video_queue WHERE group_id = ? AND file_unique_id = ?",
            (group_id, file_unique_id)
        ).fetchone()
    finally:
        conn.close()

    if dup:
        return  # 已添加过该文件

    # 计算当前组内排序
    conn = get_db()
    try:
        max_order = conn.execute(
            "SELECT MAX(sort_order) as m FROM video_queue WHERE group_id = ?",
            (group_id,)
        ).fetchone()
        sort_order = (max_order['m'] or 0) + 1 if max_order and max_order['m'] is not None else 0

        # 判断是否是组内第一个（用于决定caption和计数）
        is_first = sort_order == 0
    finally:
        conn.close()

    caption = msg.caption or "" if is_first else ""

    success = add_to_queue(
        from_user_id=user.id,
        from_username=user.username or "",
        group_id=group_id,
        file_id=file_id,
        file_unique_id=file_unique_id,
        file_type=file_type,
        caption=caption,
        sort_order=sort_order
    )

    if success and is_first:
        # 只在第一个媒体时增加计数和回复
        increment_video_count(user.id)
        await msg.reply_text("✅ 媒体组已加入发送队列！")
        logger.info("用户 %s 添加媒体组到队列 (group: %s)", user.id, group_id)
    elif success:
        logger.info("用户 %s 媒体组追加 (group: %s, order: %d)", user.id, group_id, sort_order)
