"""消息处理器模块（文本、附件、转发、媒体组）"""
import re
import asyncio
import logging
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import MAX_COLLECTION_FILES, GROUP_SEND_SIZE, FILE_TYPE_MAP
from database import save_file, get_file, get_collection, get_collection_files, create_collection, add_file_to_collection
from utils import get_code_prefix, escape_markdown, generate_raw_code, parse_file_code, parse_collection_code
from senders import send_file_group


def _short_key(context, col_code: str) -> str:
    """生成短 key 用于 callback_data（Telegram 限制 64 字节）"""
    if 'cb_map' not in context.bot_data:
        context.bot_data['cb_map'] = {}
    # 如果已存在映射，复用
    for k, v in context.bot_data['cb_map'].items():
        if v == col_code:
            return k
    # 新建映射: s0, s1, s2 ...
    idx = len(context.bot_data['cb_map'])
    key = f"s{idx}"
    context.bot_data['cb_map'][key] = col_code
    return key

logger = logging.getLogger(__name__)


async def handle_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户发送的图片/视频/音频/文档"""
    message = update.message
    user_id = update.effective_user.id
    bot_username = context.bot.username
    code_prefix = get_code_prefix(bot_username)
    creating_col = context.user_data.get('creating_collection')

    try:
        file_id, file_type, file_size, file_unique_id = _extract_file_info(message)
        if not file_id:
            await message.reply_text("❌ 不支持的文件类型。支持: 图片、视频、音频、文档。")
            return

        code = save_file(user_id, file_type, file_id, file_size, file_unique_id, bot_username, code_prefix)
        if not code:
            await message.reply_text("❌ 保存失败，请重试。")
            return

        type_name = FILE_TYPE_MAP.get(file_type, file_type)
        reply_text = f"✅ {type_name}已保存！\n\n代码: `{code}`"
        reply_kwargs = {'text': reply_text, 'parse_mode': 'Markdown', 'reply_to_message_id': message.message_id}

        # 如果正在创建集合，追加文件
        if creating_col:
            current_count = context.user_data.get('collection_count', 0)
            if current_count >= MAX_COLLECTION_FILES:
                await message.reply_text(f"⚠️ 集合已满 {MAX_COLLECTION_FILES} 个文件，请发送 `/done` 完成。")
                return
            sort_order = current_count + 1
            add_file_to_collection(creating_col, code, sort_order)
            context.user_data['collection_count'] = sort_order
            reply_kwargs['text'] += f"\n\n📦 已添加到集合 ({sort_order}/{MAX_COLLECTION_FILES})"

        await message.reply_text(**reply_kwargs)
    except Exception as e:
        logger.error("处理附件失败: %s", e)
        await message.reply_text(f"❌ 处理文件时出错: {e}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理文本消息，解析代码并发送文件"""
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    bot_username = context.bot.username
    file_codes = parse_file_code(text, bot_username)
    collection_codes = parse_collection_code(text, bot_username)

    # 旧格式兼容: $p $v $d
    legacy_file_ids = []
    if not file_codes and not collection_codes:
        for m in re.compile(r'\$([pvd])(\S+)').finditer(text):
            legacy_file_ids.append((m.group(1), m.group(2)))

    if not file_codes and not collection_codes and not legacy_file_ids:
        await message.reply_text("❓ 未识别的输入。\n\n• 发送文件获取代码\n• 发送代码获取文件\n• `/help` 查看帮助")
        return

    chat_id = message.chat_id
    total_sent = 0

    # 发送单个文件
    if file_codes:
        files, not_found = [], []
        for code in file_codes:
            f = get_file(code)
            if f:
                files.append(f)
            else:
                not_found.append(code)

        if files:
            try:
                total_sent += await send_file_group(context, chat_id, files)
            except Exception as e:
                logger.error("发送文件失败: %s", e)
                await message.reply_text(f"❌ 发送文件时出错: {e}")

        if not_found:
            await message.reply_text("⚠️ 以下代码未找到:\n" + "\n".join(f"• `{c}`" for c in not_found), parse_mode="Markdown")

    # 处理集合
    for col_code in collection_codes:
        col_info = get_collection(col_code)
        if not col_info:
            await message.reply_text(f"❌ 集合不存在: `{col_code}`", parse_mode="Markdown")
            continue

        safe_name = escape_markdown(col_info['name'])
        if col_info['status'] != 'completed':
            await message.reply_text(f"⚠️ 集合「{safe_name}」尚未完成。")
            continue

        files = get_collection_files(col_code)
        if not files:
            await message.reply_text(f"⚠️ 集合「{safe_name}」为空。")
            continue

        total_files = len(files)
        type_counts = {}
        for f in files:
            type_counts[f['file_type']] = type_counts.get(f['file_type'], 0) + 1
        type_stats_text = " ".join(f"{FILE_TYPE_MAP.get(k, k)}x{v}" for k, v in type_counts.items())

        sk = _short_key(context, col_code)
        col_text = f"📦 *集合「{safe_name}」*\n\n📊 共 {total_files} 个文件\n📋 {type_stats_text}\n\n请选择操作："
        keyboard = [
            [InlineKeyboardButton("⬇️ 全部发送", callback_data=f"s|{sk}")],
            [InlineKeyboardButton("▶️ 自动发送", callback_data=f"a|{sk}")],
        ]
        if total_files > GROUP_SEND_SIZE:
            keyboard.append([InlineKeyboardButton("📖 分页浏览", callback_data=f"p|{sk}|1")])

        await message.reply_text(col_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # 旧格式
    if legacy_file_ids:
        for prefix, fid in legacy_file_ids:
            try:
                if prefix == 'p':
                    await context.bot.send_photo(chat_id=chat_id, photo=fid)
                elif prefix == 'v':
                    await context.bot.send_video(chat_id=chat_id, video=fid)
                elif prefix == 'd':
                    await context.bot.send_document(chat_id=chat_id, document=fid)
                total_sent += 1
            except Exception as e:
                logger.error("旧格式发送失败: %s", e)


async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理转发的非媒体消息"""
    message = update.message
    if message.document or message.photo or message.video or message.audio or message.voice:
        await handle_attachment(update, context)
    elif message.text:
        await handle_text(update, context)
    else:
        await message.reply_text("请转发包含媒体的消息，我会返回其代码。")


async def handle_group_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理媒体组（用户一次性发送多个媒体）"""
    message = update.message
    if not message:
        return

    logger.info("handle_group_media 触发: photo=%s, video=%s, document=%s, audio=%s, voice=%s, media_group_id=%s",
                bool(message.photo), bool(message.video), bool(message.document),
                bool(message.audio), bool(message.voice), message.media_group_id)

    media_group_id = message.media_group_id
    if not media_group_id:
        await handle_attachment(update, context)
        return

    # 收集同组媒体
    if 'pending_media_groups' not in context.bot_data:
        context.bot_data['pending_media_groups'] = {}

    if media_group_id not in context.bot_data['pending_media_groups']:
        context.bot_data['pending_media_groups'][media_group_id] = {'messages': [], 'timer': None}

    group_data = context.bot_data['pending_media_groups'][media_group_id]
    group_data['messages'].append(message)
    if group_data['timer']:
        group_data['timer'].cancel()

    async def process():
        try:
            await asyncio.sleep(2)
            msgs = group_data['messages']
            if not msgs:
                return
            codes = await _save_media_messages(msgs, context)
            if codes:
                creating_col = context.user_data.get('creating_collection')
                if creating_col:
                    await _add_to_collection(context, creating_col, codes)
                    count = context.user_data.get('collection_count', 0)
                    reply = f"✅ 媒体组已保存并添加到集合！\n\n共 {len(codes)} 个文件 ({count}/{MAX_COLLECTION_FILES})\n\n"
                else:
                    reply = f"✅ 媒体组已保存！共 {len(codes)} 个文件：\n\n"
                reply += "\n".join(f"`{c}`" for c in codes)
                await msgs[0].reply_text(reply, parse_mode="Markdown")
        except Exception as e:
            logger.error("process_media_group 失败: %s", e, exc_info=True)
        finally:
            context.bot_data.get('pending_media_groups', {}).pop(media_group_id, None)

    group_data['timer'] = asyncio.create_task(process())


async def handle_forwarded_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理转发的媒体消息（自动为媒体组创建集合）"""
    message = update.message
    if not message:
        return

    logger.info("转发媒体: media_group_id=%s, photo=%s, video=%s, doc=%s",
                message.media_group_id, bool(message.photo), bool(message.video), bool(message.document))

    has_media = message.document or message.photo or message.video or message.audio or message.voice
    if not has_media:
        if message.text:
            await handle_text(update, context)
        else:
            await message.reply_text("请转发包含媒体的消息。")
        return

    media_group_id = message.media_group_id
    if not media_group_id:
        # 单个转发，直接处理
        await handle_attachment(update, context)
        return

    # 媒体组：收集后自动创建集合
    if 'pending_forward_groups' not in context.bot_data:
        context.bot_data['pending_forward_groups'] = {}

    if media_group_id not in context.bot_data['pending_forward_groups']:
        context.bot_data['pending_forward_groups'][media_group_id] = {'messages': [], 'timer': None}

    group_data = context.bot_data['pending_forward_groups'][media_group_id]
    group_data['messages'].append(message)
    if group_data['timer']:
        group_data['timer'].cancel()

    async def process():
        try:
            await asyncio.sleep(2)
            msgs = group_data['messages']
            if not msgs:
                return

            codes = await _save_media_messages(msgs, context)
            if not codes:
                await msgs[0].reply_text("❌ 转发的媒体组处理失败。")
                return

            # 自动创建集合
            uid = msgs[0].from_user.id
            bname = context.bot.username
            code_prefix = get_code_prefix(bname)
            col_name = f"转发组_{datetime.now().strftime('%m%d%H%M')}"
            full_col_code = f"{code_prefix}_col:{generate_raw_code()}"

            # 保存集合到数据库
            from database import get_db
            conn = get_db()
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "INSERT INTO collections (code, bot_username, name, user_id, file_count, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'completed', ?, ?)",
                    (full_col_code, bname, col_name, uid, len(codes), now, now)
                )
                for i, code in enumerate(codes):
                    conn.execute("INSERT INTO collection_items (collection_code, file_code, sort_order) VALUES (?, ?, ?)", (full_col_code, code, i + 1))
                conn.commit()
            except Exception as e:
                logger.error("自动创建转发集合失败: %s", e)
                reply = f"✅ 转发媒体已保存（共 {len(codes)} 个）：\n\n" + "\n".join(f"`{c}`" for c in codes)
                await msgs[0].reply_text(reply, parse_mode="Markdown")
                return
            finally:
                conn.close()

            # 回复
            safe_name = escape_markdown(col_name)
            reply = f"✅ 转发媒体组已保存并自动创建集合！\n\n📦 集合: *{safe_name}*\n📊 共 {len(codes)} 个文件\n📦 集合代码: `{full_col_code}`\n\n单个文件代码：\n"
            reply += "\n".join(f"`{c}`" for c in codes)
            sk = _short_key(context, full_col_code)
            keyboard = [[InlineKeyboardButton("⬇️ 全部发送", callback_data=f"s|{sk}"), InlineKeyboardButton("▶️ 自动发送", callback_data=f"a|{sk}")]]
            try:
                await msgs[0].reply_text(reply, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception:
                await msgs[0].reply_text(reply, parse_mode="Markdown")

        except Exception as e:
            logger.error("process_forward_group 失败: %s", e, exc_info=True)
        finally:
            context.bot_data.get('pending_forward_groups', {}).pop(media_group_id, None)

    group_data['timer'] = asyncio.create_task(process())


# ==================== 内部辅助函数 ====================

def _extract_file_info(message) -> tuple:
    """从消息中提取文件信息，返回 (file_id, file_type, file_size, file_unique_id)"""
    if message.photo:
        photo = message.photo[len(message.photo) - 1]
        return photo.file_id, 'photo', photo.file_size or 0, photo.file_unique_id or ''
    elif message.video:
        return message.video.file_id, 'video', message.video.file_size or 0, message.video.file_unique_id or ''
    elif message.audio:
        return message.audio.file_id, 'audio', message.audio.file_size or 0, message.audio.file_unique_id or ''
    elif message.document:
        return message.document.file_id, 'document', message.document.file_size or 0, message.document.file_unique_id or ''
    elif message.voice:
        return message.voice.file_id, 'voice', message.voice.file_size or 0, message.voice.file_unique_id or ''
    return None, None, 0, ''


async def _save_media_messages(messages, context) -> list:
    """批量保存媒体消息，返回代码列表"""
    uid = messages[0].from_user.id
    bname = context.bot.username
    code_prefix = get_code_prefix(bname)
    codes = []

    for msg in messages:
        file_id, file_type, file_size, file_unique_id = _extract_file_info(msg)
        if file_id and file_type:
            code = save_file(uid, file_type, file_id, file_size, file_unique_id, bname, code_prefix)
            if code:
                codes.append(code)
    return codes


async def _add_to_collection(context, col_code, codes):
    """将代码列表添加到集合"""
    current_count = context.user_data.get('collection_count', 0)
    for i, code in enumerate(codes):
        if current_count + i + 1 > MAX_COLLECTION_FILES:
            break
        add_file_to_collection(col_code, code, current_count + i + 1)
    new_count = min(current_count + len(codes), MAX_COLLECTION_FILES)
    context.user_data['collection_count'] = new_count