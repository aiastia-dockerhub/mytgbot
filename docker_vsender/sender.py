"""视频发送模块 - 广播视频给白名单用户"""
import asyncio
import logging
import os
from typing import List, Dict, Optional

from telegram.ext import ContextTypes

from config import SEND_CONCURRENCY, BATCH_INTERVAL, VIDEO_INTERVAL
from database import (
    get_active_users, mark_video_sent, update_user_status,
    create_send_log, update_send_log, log_send_detail
)

logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


async def send_video_to_user(bot, chat_id: int, video_path: str,
                             caption: str = "") -> bool:
    """发送本地视频文件给单个用户，返回是否成功"""
    try:
        with open(video_path, 'rb') as vf:
            await bot.send_video(
                chat_id=chat_id,
                video=vf,
                caption=caption[:1024] if caption else "",
                supports_streaming=True
            )
        return True
    except Exception as e:
        error_str = str(e)
        # 检测拉黑/封禁
        if "Forbidden" in error_str or "blocked" in error_str.lower() or "deactivated" in error_str.lower():
            logger.warning("用户 %s 已拉黑bot: %s", chat_id, error_str)
            return False
        logger.error("发送视频到 %s 失败: %s", chat_id, e)
        return False


async def broadcast_video(
    context: ContextTypes.DEFAULT_TYPE,
    video_path: str,
    video_file_id: Optional[int],
    admin_user_id: int,
    caption: str = ""
) -> Dict:
    """
    广播视频给所有白名单用户
    返回 {'success': int, 'fail': int, 'blocked': list}
    """
    if not os.path.exists(video_path):
        logger.error("视频文件不存在: %s", video_path)
        return {'success': 0, 'fail': 0, 'blocked': [], 'error': '文件不存在'}

    active_users = get_active_users()
    if not active_users:
        logger.info("没有活跃用户，跳过发送")
        return {'success': 0, 'fail': 0, 'blocked': [], 'error': '没有活跃用户'}

    file_name = os.path.basename(video_path)
    file_size = os.path.getsize(video_path)

    # 创建发送日志
    log_id = create_send_log(
        admin_user_id=admin_user_id,
        video_file_id=video_file_id,
        file_path=video_path,
        caption=caption,
        total_users=len(active_users)
    )

    # 通知管理员开始发送
    try:
        await context.bot.send_message(
            chat_id=admin_user_id,
            text=f"📤 开始发送: {file_name}\n"
                 f"📦 大小: {format_size(file_size)}\n"
                 f"👥 目标用户: {len(active_users)} 人\n"
                 f"⏳ 发送中..."
        )
    except Exception:
        pass

    success_count = 0
    fail_count = 0
    blocked_users = []

    # 分批发送
    for i in range(0, len(active_users), SEND_CONCURRENCY):
        batch = active_users[i:i + SEND_CONCURRENCY]

        tasks = []
        for user in batch:
            tasks.append(
                _send_and_log(context.bot, user['user_id'], video_path, caption, log_id)
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error("发送异常: %s", r)
                fail_count += 1
            elif r['success']:
                success_count += 1
            else:
                fail_count += 1
                blocked_users.append(r['user_id'])

        # 批次间间隔
        if i + SEND_CONCURRENCY < len(active_users):
            await asyncio.sleep(BATCH_INTERVAL)

    # 标记视频已发送
    if video_file_id:
        mark_video_sent(video_file_id)

    # 更新发送日志
    update_send_log(log_id, success_count, fail_count, 'done')

    # 通知管理员发送结果
    result_text = (
        f"✅ 发送完成: {file_name}\n"
        f"📊 成功: {success_count} / 失败: {fail_count}\n"
        f"👥 目标: {len(active_users)} 人"
    )
    if blocked_users:
        result_text += f"\n🚫 被拉黑用户: {len(blocked_users)} 人（已自动标记）"

    try:
        await context.bot.send_message(chat_id=admin_user_id, text=result_text)
    except Exception:
        pass

    return {
        'success': success_count,
        'fail': fail_count,
        'blocked': blocked_users
    }


async def _send_and_log(bot, user_id: int, video_path: str,
                        caption: str, log_id: int) -> Dict:
    """发送视频并记录结果"""
    success = await send_video_to_user(bot, user_id, video_path, caption)

    if success:
        log_send_detail(log_id, user_id, 'sent')
        return {'user_id': user_id, 'success': True}
    else:
        # 标记用户为 stopped
        update_user_status(user_id, 'stopped')
        log_send_detail(log_id, user_id, 'blocked')
        return {'user_id': user_id, 'success': False}


async def send_videos_batch(
    context: ContextTypes.DEFAULT_TYPE,
    videos: List[Dict],
    admin_user_id: int,
    caption: str = ""
) -> Dict:
    """
    批量发送多个视频
    返回总计统计
    """
    total_success = 0
    total_fail = 0
    total_blocked = []
    results = []

    for idx, video in enumerate(videos):
        video_path = video['file_path']
        video_name = video.get('file_name', os.path.basename(video_path))

        logger.info("发送视频 %d/%d: %s", idx + 1, len(videos), video_name)

        # 通知管理员进度
        try:
            await context.bot.send_message(
                chat_id=admin_user_id,
                text=f"📹 [{idx + 1}/{len(videos)}] 正在发送: {video_name}"
            )
        except Exception:
            pass

        result = await broadcast_video(
            context=context,
            video_path=video_path,
            video_file_id=video.get('id'),
            admin_user_id=admin_user_id,
            caption=caption
        )

        total_success += result.get('success', 0)
        total_fail += result.get('fail', 0)
        total_blocked.extend(result.get('blocked', []))
        results.append({'video': video_name, 'result': result})

        # 视频间间隔
        if idx < len(videos) - 1:
            await asyncio.sleep(VIDEO_INTERVAL)

    # 汇总报告
    summary = (
        f"📋 批量发送完成！\n"
        f"📹 视频数量: {len(videos)}\n"
        f"📊 总成功: {total_success}\n"
        f"📊 总失败: {total_fail}\n"
        f"🚫 被拉黑: {len(set(total_blocked))} 人"
    )
    try:
        await context.bot.send_message(chat_id=admin_user_id, text=summary)
    except Exception:
        pass

    return {
        'total_success': total_success,
        'total_fail': total_fail,
        'blocked': list(set(total_blocked)),
        'results': results
    }