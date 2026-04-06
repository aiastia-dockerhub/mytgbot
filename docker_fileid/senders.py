"""文件发送逻辑模块"""
import logging
from typing import List, Dict

from telegram.ext import ContextTypes
from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio

from config import GROUP_SEND_SIZE

logger = logging.getLogger(__name__)


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
            try:
                fid = f['telegram_file_id']
                logger.info("发送单个媒体: type=%s, file_id=%s...(len=%d)", f['file_type'], str(fid)[:30], len(str(fid)))
                if f['file_type'] == 'photo':
                    await context.bot.send_photo(chat_id=chat_id, photo=fid, caption=caption[:1024] if caption else "")
                else:
                    await context.bot.send_video(chat_id=chat_id, video=fid, caption=caption[:1024] if caption else "")
                sent_count += 1
            except Exception as e:
                logger.error("发送单个媒体失败: %s", e, exc_info=True)
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
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                    sent_count += len(media_list)
                except Exception as e:
                    logger.error("发送媒体组失败: %s", e)
                    for f in batch:
                        try:
                            if f['file_type'] == 'photo':
                                await context.bot.send_photo(chat_id=chat_id, photo=f['telegram_file_id'])
                            else:
                                await context.bot.send_video(chat_id=chat_id, video=f['telegram_file_id'])
                            sent_count += 1
                        except Exception as e2:
                            logger.error("降级发送失败: %s", e2)

    # 2. 发送文档
    for i in range(0, len(documents), GROUP_SEND_SIZE):
        batch = documents[i:i + GROUP_SEND_SIZE]
        if len(batch) == 1:
            try:
                await context.bot.send_document(chat_id=chat_id, document=batch[0]['telegram_file_id'], caption=caption[:1024] if caption else "")
                sent_count += 1
            except Exception as e:
                logger.error("发送文档失败: %s", e)
        else:
            media_list = []
            for f in batch:
                try:
                    media_list.append(InputMediaDocument(media=f['telegram_file_id']))
                except Exception as e:
                    logger.error("构建文档列表失败: %s", e)
            if media_list:
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                    sent_count += len(media_list)
                except Exception as e:
                    logger.error("发送文档组失败: %s", e)
                    for f in batch:
                        try:
                            await context.bot.send_document(chat_id=chat_id, document=f['telegram_file_id'])
                            sent_count += 1
                        except Exception as e2:
                            logger.error("降级发送文档失败: %s", e2)

    # 3. 发送音频
    for i in range(0, len(audios), GROUP_SEND_SIZE):
        batch = audios[i:i + GROUP_SEND_SIZE]
        if len(batch) == 1:
            try:
                await context.bot.send_audio(chat_id=chat_id, audio=batch[0]['telegram_file_id'], caption=caption[:1024] if caption else "")
                sent_count += 1
            except Exception as e:
                logger.error("发送音频失败: %s", e)
        else:
            media_list = []
            for f in batch:
                try:
                    media_list.append(InputMediaAudio(media=f['telegram_file_id']))
                except Exception as e:
                    logger.error("构建音频列表失败: %s", e)
            if media_list:
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                    sent_count += len(media_list)
                except Exception as e:
                    logger.error("发送音频组失败: %s", e)
                    for f in batch:
                        try:
                            await context.bot.send_audio(chat_id=chat_id, audio=f['telegram_file_id'])
                            sent_count += 1
                        except Exception as e2:
                            logger.error("降级发送音频失败: %s", e2)

    return sent_count