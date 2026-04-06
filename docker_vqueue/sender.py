"""视频发送模块 - 队列消费与媒体发送"""
import asyncio
import logging
from typing import List, Dict

from telegram.ext import ContextTypes
from telegram import InputMediaVideo, InputMediaPhoto

from config import SEND_INTERVAL, VIDEO_INTERVAL, PROTECT_CONTENT, SHOW_SOURCE, SOURCE_FORMAT
from database import (
    get_next_pending_group, get_active_users, update_queue_status,
    increment_sent_count, log_send, update_user_status
)
from models import QueueStatus, UserStatus

logger = logging.getLogger(__name__)


def build_caption(original_caption: str, from_user_id: int, from_username: str) -> str:
    """构建带来源标注的caption"""
    parts = []

    if SHOW_SOURCE:
        username = from_username or "未知"
        source_line = SOURCE_FORMAT.format(username=username, user_id=from_user_id)
        parts.append(source_line)

    if original_caption:
        parts.append(original_caption)

    result = "\n".join(parts)
    # Telegram caption 最大 1024 字符
    return result[:1024] if result else ""


async def send_single_media(
    bot, chat_id: int, item: Dict, caption: str, protect: bool
) -> bool:
    """发送单个媒体文件，返回是否成功"""
    file_id = item['file_id']
    file_type = item['file_type']

    try:
        if file_type == 'video':
            await bot.send_video(
                chat_id=chat_id, video=file_id,
                caption=caption, protect_content=protect
            )
        else:
            await bot.send_photo(
                chat_id=chat_id, photo=file_id,
                caption=caption, protect_content=protect
            )
        return True
    except Exception as e:
        error_str = str(e)
        # 检测拉黑
        if "Forbidden" in error_str or "blocked" in error_str.lower() or "deactivated" in error_str.lower():
            logger.warning("用户 %s 已拉黑bot: %s", chat_id, error_str)
            return False
        logger.error("发送媒体到 %s 失败: %s", chat_id, e)
        return False


async def send_media_group_to_user(
    bot, chat_id: int, items: List[Dict], source_caption: str, protect: bool
) -> int:
    """发送媒体组给单个用户，返回成功发送数"""
    if len(items) == 1:
        # 单个媒体直接发送
        success = await send_single_media(bot, chat_id, items[0], source_caption, protect)
        return 1 if success else 0

    # 多个媒体用 send_media_group
    media_list = []
    for idx, item in enumerate(items):
        cap = source_caption if idx == 0 else ""
        cap = cap[:1024] if cap else ""
        try:
            if item['file_type'] == 'video':
                media_list.append(InputMediaVideo(media=item['file_id'], caption=cap))
            else:
                media_list.append(InputMediaPhoto(media=item['file_id'], caption=cap))
        except Exception as e:
            logger.error("构建媒体列表失败: %s", e)

    if not media_list:
        return 0

    try:
        await bot.send_media_group(
            chat_id=chat_id, media=media_list, protect_content=protect
        )
        return len(media_list)
    except Exception as e:
        logger.error("发送媒体组到 %s 失败: %s，尝试逐个发送", chat_id, e)
        # 降级：逐个发送
        sent = 0
        for item in items:
            cap = source_caption if sent == 0 else ""
            if await send_single_media(bot, chat_id, item, cap, protect):
                sent += 1
        return sent


async def process_queue(context: ContextTypes.DEFAULT_TYPE):
    """处理队列：取一组 → 发送给所有活跃用户"""
    group = get_next_pending_group()
    if not group:
        return

    group_id = group['group_id']
    from_user_id = group['from_user_id']
    from_username = group['from_username']
    items = group['items']
    queue_ids = [item['id'] for item in items]

    # 构建来源caption
    original_caption = items[0].get('caption', '') or ''
    caption = build_caption(original_caption, from_user_id, from_username)

    # 标记为发送中
    update_queue_status(queue_ids, QueueStatus.SENDING)

    active_users = get_active_users()
    if not active_users:
        logger.info("没有活跃用户，跳过发送")
        update_queue_status(queue_ids, QueueStatus.DONE)
        return

    logger.info("开始发送组 %s (%d个媒体) 给 %d 个活跃用户",
                group_id, len(items), len(active_users))

    protect = PROTECT_CONTENT
    blocked_count = 0

    for user in active_users:
        to_id = user['user_id']

        # 不发送给视频来源用户自己
        if to_id == from_user_id:
            continue

        sent = await send_media_group_to_user(
            context.bot, to_id, items, caption, protect
        )

        if sent == 0:
            # 发送失败，可能是拉黑
            blocked_count += 1
            update_user_status(to_id, UserStatus.SYSTEM_STOPPED)
            log_send(queue_ids[0], to_id, "blocked")
            logger.warning("用户 %s 发送失败，标记为 system_stopped", to_id)
        else:
            log_send(queue_ids[0], to_id, "sent")

        # 用户间间隔
        await asyncio.sleep(SEND_INTERVAL)

    # 标记完成
    increment_sent_count(queue_ids)
    update_queue_status(queue_ids, QueueStatus.DONE)

    logger.info("组 %s 发送完成，%d 个用户被标记拉黑", group_id, blocked_count)