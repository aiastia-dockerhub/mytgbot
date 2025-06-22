import logging
from telethon.tl.types import MessageMediaWebPage
from .check_admin_utils import check_admin
logger = logging.getLogger(__name__)


async def handle_offset_for_id_command(event, client, account_config, account_name):
    """命令格式: /offset_for_id <chat_id> <message_id> [type]  计算该消息id在历史消息中的offset，type同/batch_forward"""
    logger.info(f"Received /offset_for_id command from {event.sender_id}: {event.text}")
    if not event.is_private or not await check_admin(event, account_config):
        return
    try:
        args = event.text.strip().split()
        if len(args) < 3:
            await event.respond("用法: /offset_for_id <chat_id> <message_id> [type] (type 可选: all, photo, video, image, document, audio, text, media)")
            return
        chat_id = int(args[1])
        target_message_id = int(args[2])
        media_type = args[3].lower() if len(args) > 3 else None
        found, offset = await offset_for_id(client, chat_id, target_message_id, media_type)
        if found:
            await event.respond(f"消息id {target_message_id} 在 chat_id {chat_id} 的 offset 为 {offset}（type={media_type or 'media'}）。\n可用于 /batch_forward {chat_id} <目标chatid> <数量> {offset} {media_type or 'media'}")
        else:
            await event.respond(f"未找到消息id {target_message_id}，或不符合 type={media_type or 'media'} 的过滤条件。")
    except Exception as e:
        logger.error(f"Error in handle_offset_for_id_command: {e}", exc_info=True)
        await event.respond(f"获取offset失败: {e}")

def is_media_type(message, media_type=None):
    """
    判断消息是否符合指定 media_type 过滤规则，与 batch_forward/offset_for_id 统一
    """
    from telethon.tl.types import MessageMediaWebPage
    doc = getattr(message.media, 'document', None)
    mime = doc.mime_type if doc and hasattr(doc, 'mime_type') else None
    is_photo = message.photo is not None
    is_video = mime and mime.startswith('video/')
    is_image = is_photo or (mime and mime.startswith('image/'))
    is_audio = mime and mime.startswith('audio/')
    is_document = doc and not (is_image or is_video or is_audio)
    is_text = doc and (mime == 'text/plain' or (doc and doc.attributes and any(getattr(attr, 'file_name', '').endswith('.txt') for attr in doc.attributes)))
    is_webpage = message.media is not None and isinstance(message.media, MessageMediaWebPage)
    is_sticker = False
    if doc and mime:
        if mime in ('application/x-tgsticker', 'image/webp'):
            is_sticker = True
        if hasattr(doc, 'attributes'):
            for attr in doc.attributes:
                if attr.__class__.__name__ == 'DocumentAttributeSticker':
                    is_sticker = True
    is_gif = (mime == 'image/gif')
    should_count = False
    if media_type == 'all-txt':
        should_count = True
    elif media_type == 'all':
        should_count = message.media is not None and not is_webpage
    elif media_type in (None, '', 'media'):
        should_count = is_image or is_video
    elif media_type in ('photo', 'image'):
        should_count = is_image
    elif media_type == 'video':
        should_count = is_video
    elif media_type == 'audio':
        should_count = is_audio
    elif media_type == 'document':
        should_count = is_document
    elif media_type == 'text':
        should_count = is_text
    if is_sticker or is_gif:
        should_count = False
    return should_count

async def offset_for_id(client, chat_id, target_message_id, media_type=None):
    """
    计算某消息id在历史消息中的offset，type同/batch_forward
    :param client: Telethon client
    :param chat_id: 群组/频道id
    :param target_message_id: 目标消息id
    :param media_type: 过滤类型
    :return: (found, offset)
    """
    offset = 0
    found = False
    async for message in client.iter_messages(chat_id, reverse=True):
        if is_media_type(message, media_type):
            if message.id == target_message_id:
                found = True
                break
            offset += 1
    return found, offset
