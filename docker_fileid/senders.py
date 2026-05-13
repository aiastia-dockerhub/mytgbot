"""文件发送逻辑模块"""
import asyncio
import logging
import re
from typing import List, Dict

from telegram.ext import ContextTypes
from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

from config import GROUP_SEND_SIZE, SEND_DELAY, FLOOD_RETRY_MARGIN, FLOOD_MAX_RETRIES

logger = logging.getLogger(__name__)

# 匹配 "Retry in X seconds" 的正则
_FLOOD_RE = re.compile(r'Retry in (\d+) seconds?', re.IGNORECASE)


def _parse_flood_seconds(error_msg: str) -> int:
    """从 Flood Control 错误消息中解析需要等待的秒数，解析失败返回 0"""
    m = _FLOOD_RE.search(str(error_msg))
    if m:
        return int(m.group(1))
    return 0


async def _wait_for_flood(error_msg: str, context_label: str = "") -> bool:
    """
    处理 Flood Control 错误：解析等待时间并 sleep。
    返回 True 表示已等待可以重试，False 表示无法解析（不用等）。
    """
    seconds = _parse_flood_seconds(str(error_msg))
    if seconds > 0:
        wait_time = seconds + FLOOD_RETRY_MARGIN
        logger.warning(
            "Flood Control 触发%s，等待 %d 秒（原始 %d + 缓冲 %d）后重试",
            f" [{context_label}]" if context_label else "",
            wait_time, seconds, FLOOD_RETRY_MARGIN
        )
        await asyncio.sleep(wait_time)
        return True
    return False


async def _safe_send(send_func, context_label: str = "", retries: int = FLOOD_MAX_RETRIES):
    """
    带重试的安全发送封装。
    send_func: async callable，执行实际的发送操作
    context_label: 用于日志标识
    retries: 最大重试次数
    返回 (success: bool, result_or_error)
    """
    for attempt in range(retries + 1):
        try:
            result = await send_func()
            return True, result
        except Exception as e:
            error_str = str(e)
            if 'Flood control' in error_str or 'flood' in error_str.lower():
                if attempt < retries:
                    waited = await _wait_for_flood(error_str, context_label)
                    if waited:
                        continue  # 重试
                logger.error("发送失败（已达最大重试 %d 次）%s: %s",
                             retries, f" [{context_label}]" if context_label else "", e)
                return False, e
            else:
                logger.error("发送失败%s: %s", f" [{context_label}]" if context_label else "", e)
                return False, e
    return False, Exception("超出最大重试次数")


async def send_file_group(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    files: List[Dict],
    caption: str = ""
) -> int:
    """
    组发送文件（图片+视频用相册，文档用文档组，音频用音频组）
    返回成功发送的数量
    """
    if not files:
        logger.warning("send_file_group: files 为空")
        return 0

    logger.info("send_file_group: 准备发送 %d 个文件到 chat_id=%s", len(files), chat_id)

    # 按类型分组
    photo_video = []
    documents = []
    audios = []

    for f in files:
        ft = f['file_type']
        if ft in ('photo', 'video'):
            photo_video.append(f)
        elif ft == 'audio':
            audios.append(f)
        else:  # document, voice
            documents.append(f)

    sent_count = 0

    # 1. 发送图片+视频
    for i in range(0, len(photo_video), GROUP_SEND_SIZE):
        batch = photo_video[i:i + GROUP_SEND_SIZE]
        logger.info("发送图片+视频组: %d 个文件", len(batch))

        if len(batch) == 1:
            f = batch[0]
            fid = f['telegram_file_id']
            logger.info("发送单个媒体: type=%s, file_id=%s...(len=%d)",
                        f['file_type'], str(fid)[:30], len(str(fid)))

            async def _send_single_media(f=f):
                if f['file_type'] == 'photo':
                    return await context.bot.send_photo(
                        chat_id=chat_id, photo=fid,
                        caption=caption[:1024] if caption else "")
                else:
                    return await context.bot.send_video(
                        chat_id=chat_id, video=fid,
                        caption=caption[:1024] if caption else "")

            success, _ = await _safe_send(_send_single_media, f"单媒体-{f['file_type']}")
            if success:
                sent_count += 1
            await asyncio.sleep(SEND_DELAY)
        else:
            media_list = []
            for idx, f in enumerate(batch):
                file_id = f['telegram_file_id']
                cap = caption if idx == 0 else ""
                try:
                    if f['file_type'] == 'photo':
                        media_list.append(InputMediaPhoto(media=file_id, caption=cap[:1024] if cap else ""))
                    else:
                        media_list.append(InputMediaVideo(media=file_id, caption=cap[:1024] if cap else ""))
                except Exception as e:
                    logger.error("构建媒体列表失败: %s", e)

            if media_list:
                async def _send_media_group(ml=media_list):
                    return await context.bot.send_media_group(chat_id=chat_id, media=ml)

                success, _ = await _safe_send(_send_media_group, f"媒体组-{len(media_list)}个")

                if success:
                    sent_count += len(media_list)
                    await asyncio.sleep(SEND_DELAY)
                else:
                    # 降级：逐个发送，带节流和 Flood 重试
                    logger.warning("媒体组发送失败，降级为逐个发送（%d 个文件）", len(batch))
                    for f in batch:
                        async def _send_fallback(f=f):
                            if f['file_type'] == 'photo':
                                return await context.bot.send_photo(
                                    chat_id=chat_id, photo=f['telegram_file_id'])
                            else:
                                return await context.bot.send_video(
                                    chat_id=chat_id, video=f['telegram_file_id'])

                        ok, _ = await _safe_send(_send_fallback, f"降级-{f['file_type']}")
                        if ok:
                            sent_count += 1
                        await asyncio.sleep(SEND_DELAY)

    # 组间休息，避免连续发送触发限流
    if photo_video and (documents or audios):
        await asyncio.sleep(SEND_DELAY)

    # 2. 发送文档
    for i in range(0, len(documents), GROUP_SEND_SIZE):
        batch = documents[i:i + GROUP_SEND_SIZE]
        if len(batch) == 1:
            async def _send_single_doc(b=batch):
                return await context.bot.send_document(
                    chat_id=chat_id, document=b[0]['telegram_file_id'],
                    caption=caption[:1024] if caption else "")

            success, _ = await _safe_send(_send_single_doc, "单文档")
            if success:
                sent_count += 1
            await asyncio.sleep(SEND_DELAY)
        else:
            media_list = []
            for f in batch:
                try:
                    media_list.append(InputMediaDocument(media=f['telegram_file_id']))
                except Exception as e:
                    logger.error("构建文档列表失败: %s", e)
            if media_list:
                async def _send_doc_group(ml=media_list):
                    return await context.bot.send_media_group(chat_id=chat_id, media=ml)

                success, _ = await _safe_send(_send_doc_group, f"文档组-{len(media_list)}个")

                if success:
                    sent_count += len(media_list)
                    await asyncio.sleep(SEND_DELAY)
                else:
                    logger.warning("文档组发送失败，降级为逐个发送")
                    for f in batch:
                        async def _send_fallback_doc(f=f):
                            return await context.bot.send_document(
                                chat_id=chat_id, document=f['telegram_file_id'])

                        ok, _ = await _safe_send(_send_fallback_doc, "降级文档")
                        if ok:
                            sent_count += 1
                        await asyncio.sleep(SEND_DELAY)

    # 组间休息
    if documents and audios:
        await asyncio.sleep(SEND_DELAY)

    # 3. 发送音频
    for i in range(0, len(audios), GROUP_SEND_SIZE):
        batch = audios[i:i + GROUP_SEND_SIZE]
        if len(batch) == 1:
            async def _send_single_audio(b=batch):
                return await context.bot.send_audio(
                    chat_id=chat_id, audio=b[0]['telegram_file_id'],
                    caption=caption[:1024] if caption else "")

            success, _ = await _safe_send(_send_single_audio, "单音频")
            if success:
                sent_count += 1
            await asyncio.sleep(SEND_DELAY)
        else:
            media_list = []
            for f in batch:
                try:
                    media_list.append(InputMediaAudio(media=f['telegram_file_id']))
                except Exception as e:
                    logger.error("构建音频列表失败: %s", e)
            if media_list:
                async def _send_audio_group(ml=media_list):
                    return await context.bot.send_media_group(chat_id=chat_id, media=ml)

                success, _ = await _safe_send(_send_audio_group, f"音频组-{len(media_list)}个")

                if success:
                    sent_count += len(media_list)
                    await asyncio.sleep(SEND_DELAY)
                else:
                    logger.warning("音频组发送失败，降级为逐个发送")
                    for f in batch:
                        async def _send_fallback_audio(f=f):
                            return await context.bot.send_audio(
                                chat_id=chat_id, audio=f['telegram_file_id'])

                        ok, _ = await _safe_send(_send_fallback_audio, "降级音频")
                        if ok:
                            sent_count += 1
                        await asyncio.sleep(SEND_DELAY)

    return sent_count