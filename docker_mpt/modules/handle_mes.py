
from collections import defaultdict
import time
import logging 
from modules.check_admin_utils import check_admin
from modules.handle_med import handle_media
import logging
from db.base import init_db
from db.models import Message
from db.base import SessionLocal
import asyncio
from datetime import datetime
from collections import defaultdict
import time

logging.basicConfig(
    level=logging.INFO, # 可以暂时设置为 DEBUG 级别以获取更多信息
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== 频率限制：每 chat_id 每秒最多转发一次 ==========
# 记录上次转发时间，key=(source_id, target_id)
last_forward_time = defaultdict(lambda: 0)

async def handle_message(event, client, account_config, account_name, db_account, text_watch_rules, media_watch_rules):
    """处理新消息，支持群组、频道和私聊"""
    logger.debug(f"[DEBUG] handle_message triggered for chat_id: {event.chat_id}, message_id: {event.message.id}")
    
    # 判断是否为私聊、群组或频道
    is_private = event.is_private
    is_group = event.is_group
    is_channel = event.is_channel

    logger.debug(f"[DEBUG] Message type: private={is_private}, group={is_group}, channel={is_channel}")

    # 只处理配置中允许的群组/频道/私聊
    enabled_chats = [str(cid) for cid in account_config['monitoring'].get('enabled_chats', [])] # 确保都是字符串
    logger.debug(f"[DEBUG] Configured enabled_chats: {enabled_chats}")

    # 获取消息来源的 chat_id (统一为字符串)
    source_id = str(event.chat_id)

    if is_group or is_channel:
        if enabled_chats and source_id not in enabled_chats:
            logger.debug(f"[DEBUG] Skipping disabled group/channel chat_id: {source_id}")
            return
        else:
            logger.debug(f"[DEBUG] Processing group/channel message from chat_id: {source_id}")
    elif is_private:
        monitor_private_bots = account_config['monitoring'].get('monitor_private_bots', False)
        bot_usernames = account_config['monitoring'].get('bot_usernames', [])
        logger.debug(f"[DEBUG] Private chat monitoring config: monitor_private_bots={monitor_private_bots}, bot_usernames={bot_usernames}")

        if monitor_private_bots:
            sender_is_bot = getattr(event.message.sender, 'bot', False)
            sender_username = getattr(event.message.sender, 'username', None)
            logger.debug(f"[DEBUG] Private message sender: is_bot={sender_is_bot}, username={sender_username}")

            if not sender_is_bot:
                logger.debug(f"[DEBUG] Skipping non-bot private message: sender={event.message.sender_id}")
                return
            if bot_usernames and sender_username not in bot_usernames:
                logger.debug(f"[DEBUG] Skipping unmonitored bot: {sender_username}")
                return
            logger.debug(f"[DEBUG] Processing private bot message from sender: {sender_username} ({event.message.sender_id})")
        else:
            logger.debug(f"[DEBUG] monitor_private_bots is False, skipping all private messages (unless specifically enabled for users).")
            # 如果 monitor_private_bots 为 False，且没有其他逻辑来处理非机器人私聊，则跳过
            return
    else:
        # 既不是私聊也不是群组/频道 (例如，可能是未知类型的更新)
        logger.debug(f"[DEBUG] Skipping unknown message type from chat_id: {source_id}")
        return

    try:
        # 记录消息
        message = Message(
            account_id=db_account.id,
            message_id=event.message.id,
            chat_id=event.chat_id,
            chat_title=event.chat.title if hasattr(event.chat, 'title') and event.chat.title else "Chat",
            sender_id=event.message.sender_id,
            sender_username=getattr(event.message.sender, 'username', None),
            content=event.message.text or "",
            timestamp=datetime.now(),
            is_bot=getattr(event.message.sender, 'bot', False),
            is_forwarded=event.message.forward is not None
        )

        # 保存消息
        with SessionLocal() as session:
            session.add(message)
            session.commit()
        logger.debug(f"[DEBUG] Message {event.message.id} from {event.chat_id} saved to DB.")

        logger.debug(f"[DEBUG] Current text watch rules: {text_watch_rules}")
        logger.debug(f"[DEBUG] Current media watch rules: {media_watch_rules}")

        # 处理媒体文件和转发逻辑分离，先判断转发
        if event.message.media: # 再次检查是否有媒体，因为之前可能只是下载
            if source_id in media_watch_rules:
                rule = media_watch_rules[source_id]
                target_id_media = rule['target_id']
                media_type = rule.get('type')
                should_forward = False
                doc = getattr(event.message.media, 'document', None)
                mime = doc.mime_type if doc and hasattr(doc, 'mime_type') else None
                # --- 新增 sticker/gif 排除逻辑，与 batch_forward_media 保持一致 ---
                is_sticker = False
                if doc and mime:
                    if mime in ('application/x-tgsticker', 'image/webp'):
                        is_sticker = True
                    if hasattr(doc, 'attributes'):
                        for attr in doc.attributes:
                            if attr.__class__.__name__ == 'DocumentAttributeSticker':
                                is_sticker = True
                # --- END ---
                # --- 新增 gif 排除 ---
                is_gif = (mime == 'image/gif')
                # --- END ---
                # --- 新增：更健壮的视频判断 ---
                is_video = (mime and mime.startswith('video/')) or getattr(event.message, 'video', None) is not None
                # --- END ---
                if media_type == 'all':
                    should_forward = True
                elif media_type == 'all-txt':
                    # 新增：所有消息（包括纯文字和所有媒体）
                    should_forward = True
                elif media_type in (None, '', 'media'):
                    # 默认：常见媒体
                    if event.message.photo or is_video or (mime and (mime.startswith('image/') or mime.startswith('audio/'))):
                        should_forward = True
                elif media_type == 'photo' or media_type == 'image':
                    if event.message.photo or (mime and mime.startswith('image/')):
                        should_forward = True
                elif media_type == 'video':
                    if is_video:
                        should_forward = True
                elif media_type == 'audio':
                    if (mime and mime.startswith('audio/')):
                        should_forward = True
                elif media_type == 'document':
                    if doc and not (mime and (mime.startswith('image/') or mime.startswith('video/') or mime.startswith('audio/'))):
                        should_forward = True
                elif media_type == 'text':
                    if doc and mime and (mime == 'text/plain' or (doc.attributes and any(getattr(attr, 'file_name', '').endswith('.txt') for attr in doc.attributes))):
                        should_forward = True
                # 这里排除 sticker
                if is_sticker:
                    should_forward = False
                # 这里排除 gif
                if is_gif:
                    should_forward = False
                # --- 新增：未转发时详细日志 ---
                if not should_forward:
                    logger.warning(f"未转发媒体: id={event.message.id}, mime={mime}, is_sticker={is_sticker}, is_gif={is_gif}, is_video={is_video}, attributes={[attr.__class__.__name__ for attr in doc.attributes] if doc and hasattr(doc, 'attributes') else None}")
                # --- END ---
                if should_forward:
                    # ====== 频率限制：如不足1秒则延迟发送 ======
                    now = time.time()
                    key = (source_id, str(target_id_media))
                    wait_time = 1.0 - (now - last_forward_time[key])
                    if wait_time > 0:
                        logger.info(f"频率限制：{key} 距上次转发不足1秒，延迟 {wait_time:.2f} 秒后发送。")
                        await asyncio.sleep(wait_time)
                    last_forward_time[key] = time.time()
                    logger.info(f"命中媒体规则: {source_id} -> {target_id_media} 类型: {media_type or 'media'} 转发媒体消息 {event.message.id}.")
                    await safe_forward_message(event.message, target_id_media, client)
                else:
                    logger.debug(f"[DEBUG] Media rule hit but type not match: {media_type}, mime: {mime}")
        # 处理媒体文件（下载），不影响转发
        if event.message.media:
            logger.debug(f"[DEBUG] Message contains media. Calling handle_media.")
            await handle_media(event.message, account_config)
        # 文字监控
        if event.message.text:
            text_processed = False
            for (sid, keyword), target_id in text_watch_rules.items():
                if sid == source_id and (keyword == '*' or keyword in event.message.text):
                    # ====== 频率限制：如不足1秒则延迟发送 ======
                    now = time.time()
                    key = (source_id, str(target_id))
                    wait_time = 1.0 - (now - last_forward_time[key])
                    if wait_time > 0:
                        logger.info(f"频率限制：{key} 距上次转发不足1秒，延迟 {wait_time:.2f} 秒后发送。")
                        await asyncio.sleep(wait_time)
                    last_forward_time[key] = time.time()
                    logger.info(f"命中文字规则: ({sid}, '{keyword}') -> {target_id}. 转发消息: '{event.message.text[:50]}...'")
                    await safe_forward_message(event.message, target_id, client)
                    text_processed = True
                    break # 命中一个规则后停止，避免重复转发
            if not text_processed:
                logger.debug(f"[DEBUG] No text rule hit for chat_id={source_id}, text='{event.message.text[:50]}...'")
    except Exception as e:
        logger.error(f"处理消息时发生未预期错误: {str(e)}", exc_info=True) # 打印完整堆栈
        # 注意：这里不能await event.respond，因为handle_message是通用监听，可能来自不应回复的群组
        # 或者可以只在私聊中回复错误
        if is_private and await check_admin(event, account_config): # 仅管理员私聊时回复错误
            await event.respond(f"处理消息时发生错误: {str(e)}")

async def safe_forward_message(message, target_id, client):
    """安全转发消息，自动兼容 int/用户名两种写法，并捕获实体找不到等异常"""
    try:
        if isinstance(target_id, str) and target_id.lstrip('-').isdigit():
            target_id = int(target_id)
        await message.forward_to(target_id)
    except ValueError as e:
        logger.error(f"无法找到目标实体 {target_id}，请确保机器人已与目标建立对话或在群组/频道内。错误: {e}")
    except Exception as e:
        logger.error(f"转发消息到 {target_id} 时出错: {e}")