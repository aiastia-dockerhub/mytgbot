"""回调按钮处理器模块"""
import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import AUTO_SEND_INTERVAL, GROUP_SEND_SIZE, FILE_TYPE_MAP
from database import get_collection, get_collection_files
from utils import escape_markdown
from senders import send_file_group

logger = logging.getLogger(__name__)


def _resolve_key(context, sk: str) -> str:
    """从短 key 映射回集合代码"""
    cb_map = context.bot_data.get('cb_map', {})
    col_code = cb_map.get(sk, '')
    logger.info("_resolve_key: sk=%s, found=%s, map_keys=%s", sk, bool(col_code), list(cb_map.keys()))
    return col_code


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理内联按钮回调"""
    query = update.callback_query
    data = query.data
    chat_id = query.from_user.id
    user_id = query.from_user.id

    logger.info("========== 按钮回调 ==========")
    logger.info("data=%s (len=%d), user_id=%s", data, len(data), user_id)

    try:
        await query.answer()
    except Exception as e:
        logger.error("query.answer() 失败: %s", e)

    try:
        # 短格式: s|key, a|key, p|key|page
        if data.startswith("s|") or data.startswith("a|") or data.startswith("p|"):
            action = data[0]
            rest = data[2:]

            if action == 's':
                # 全部发送: s|key
                sk = rest
                col_code = _resolve_key(context, sk)
                if not col_code:
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 按钮已过期，请重新发送集合代码。")
                    return
                await _send_all(context, chat_id, col_code, query)

            elif action == 'a':
                # 自动发送: a|key
                sk = rest
                col_code = _resolve_key(context, sk)
                if not col_code:
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 按钮已过期，请重新发送集合代码。")
                    return
                await _auto_send(context, chat_id, col_code, user_id, query)

            elif action == 'p':
                # 分页: p|key|page
                parts = rest.split("|")
                if len(parts) < 2:
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 数据格式错误。")
                    return
                sk = parts[0]
                page = int(parts[1])
                col_code = _resolve_key(context, sk)
                if not col_code:
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 按钮已过期，请重新发送集合代码。")
                    return
                await _send_page(context, chat_id, col_code, page, query)

        # 旧格式兼容: col_send|code, col_auto|code, col_page|code|page, page_send|code|page
        elif data.startswith("col_send|"):
            col_code = data.split("|", 1)[1]
            await _send_all(context, chat_id, col_code, query)

        elif data.startswith("col_auto|"):
            col_code = data.split("|", 1)[1]
            await _auto_send(context, chat_id, col_code, user_id, query)

        elif data.startswith("col_page|"):
            first_pipe = data.index("|", len("col_page|"))
            col_code = data[len("col_page|"):first_pipe]
            page = int(data[first_pipe + 1:])
            await _send_page(context, chat_id, col_code, page, query)

        elif data.startswith("page_send|"):
            first_pipe = data.index("|", len("page_send|"))
            col_code = data[len("page_send|"):first_pipe]
            page = int(data[first_pipe + 1:])
            await _send_page_files(context, chat_id, col_code, page, query)

        elif data == "stop_auto":
            context.user_data['stop_auto_send'] = True
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await context.bot.send_message(chat_id=chat_id, text="⏹ 已停止自动发送。")

        elif data == "noop":
            pass

        else:
            await context.bot.send_message(chat_id=chat_id, text=f"❓ 未知操作: {data}")

    except Exception as e:
        logger.error("按钮回调处理失败: %s", e, exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 操作失败: {e}")
        except Exception as e2:
            logger.error("发送错误消息也失败: %s", e2)

    logger.info("========== 按钮回调结束 ==========")


async def _send_all(context, chat_id, col_code, query=None):
    """发送集合全部文件"""
    logger.info("_send_all: col_code=%s", col_code)

    status_msg = await context.bot.send_message(chat_id=chat_id, text="📤 正在准备发送...")

    files = get_collection_files(col_code)
    logger.info("_send_all: 查询到 %d 个文件", len(files) if files else 0)

    if not files:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text="⚠️ 集合为空或不存在。")
        return

    total = len(files)

    pv = [f for f in files if f['file_type'] in ('photo', 'video')]
    docs = [f for f in files if f['file_type'] == 'document']
    audios = [f for f in files if f['file_type'] in ('audio', 'voice')]
    logger.info("分组: photo+video=%d, document=%d, audio=%d", len(pv), len(docs), len(audios))

    await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=f"📤 正在发送... (0/{total})")

    sent_count = 0
    batch_num = 0
    for group in [pv, docs, audios]:
        for i in range(0, len(group), GROUP_SEND_SIZE):
            batch = group[i:i + GROUP_SEND_SIZE]
            try:
                sent = await send_file_group(context, chat_id, batch)
                sent_count += sent
                logger.info("batch: sent=%d, total=%d/%d", sent, sent_count, total)
            except Exception as e:
                logger.error("批量发送失败: %s", e, exc_info=True)
            batch_num += 1
            if batch_num % 2 == 0:
                await asyncio.sleep(2)

    result_text = f"✅ 发送完成！成功 {sent_count}/{total}"
    logger.info("_send_all 完成: %s", result_text)
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=result_text)
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=result_text)


async def _auto_send(context, chat_id, col_code, user_id, query=None):
    """自动发送集合文件（每组间隔）"""
    files = get_collection_files(col_code)
    if not files:
        msg = "⚠️ 集合为空。"
        if query:
            try:
                await query.edit_message_text(msg)
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    total = len(files)
    context.user_data['stop_auto_send'] = False

    keyboard = [[InlineKeyboardButton("⏹ 停止发送", callback_data="stop_auto")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    status_msg = await context.bot.send_message(
        chat_id=chat_id, text=f"▶️ 自动发送中... (0/{total})", reply_markup=reply_markup
    )

    pv = [f for f in files if f['file_type'] in ('photo', 'video')]
    docs = [f for f in files if f['file_type'] == 'document']
    audios = [f for f in files if f['file_type'] in ('audio', 'voice')]

    all_groups = []
    for lst in [pv, docs, audios]:
        for i in range(0, len(lst), GROUP_SEND_SIZE):
            all_groups.append(lst[i:i + GROUP_SEND_SIZE])

    sent_count = 0
    for idx, group in enumerate(all_groups):
        if context.user_data.get('stop_auto_send'):
            await context.bot.send_message(chat_id=chat_id, text=f"⏹ 已停止。成功发送 {sent_count}/{total} 个文件。")
            return

        try:
            sent_count += await send_file_group(context, chat_id, group)
        except Exception as e:
            logger.error("自动发送组失败: %s", e)

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text=f"▶️ 自动发送中... ({sent_count}/{total})",
                reply_markup=reply_markup
            )
        except Exception:
            pass

        if idx < len(all_groups) - 1:
            await asyncio.sleep(AUTO_SEND_INTERVAL)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=status_msg.message_id,
            text=f"✅ 自动发送完成！成功 {sent_count}/{total}",
            reply_markup=None
        )
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=f"✅ 自动发送完成！成功 {sent_count}/{total}")


async def _send_page(context, chat_id, col_code, page, query=None):
    """分页浏览集合"""
    files = get_collection_files(col_code)
    col_info = get_collection(col_code)
    if not files or not col_info:
        msg = "⚠️ 集合为空或不存在。"
        if query:
            try:
                await query.edit_message_text(msg)
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    total = len(files)
    per_page = 5
    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    page_files = files[start:start + per_page]

    safe_name = escape_markdown(col_info['name'])
    text = f"📦 *{safe_name}* (第{page}/{total_pages}页，共{total}个文件)\n\n"
    for i, f in enumerate(page_files, start + 1):
        type_name = FILE_TYPE_MAP.get(f['file_type'], f['file_type'])
        size_mb = f['file_size'] / (1024 * 1024) if f['file_size'] else 0
        size_text = f"{size_mb:.1f}MB" if size_mb >= 1 else f"{f['file_size'] / 1024:.0f}KB" if f['file_size'] else "未知"
        text += f"{i}. {type_name} ({size_text})\n"

    # 获取短 key
    sk = None
    cb_map = context.bot_data.get('cb_map', {})
    for k, v in cb_map.items():
        if v == col_code:
            sk = k
            break
    if not sk:
        # 如果找不到映射，重新创建
        from handlers_messages import _short_key
        sk = _short_key(context, col_code)

    buttons = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"p|{sk}|{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"p|{sk}|{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("⬇️ 发送本页文件", callback_data=f"page_send|{col_code}|{page}")])
    buttons.append([
        InlineKeyboardButton("⬇️ 全部发送", callback_data=f"s|{sk}"),
        InlineKeyboardButton("▶️ 自动发送", callback_data=f"a|{sk}"),
    ])

    reply_markup = InlineKeyboardMarkup(buttons)
    if query:
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=reply_markup)


async def _send_page_files(context, chat_id, col_code, page, query=None):
    """发送指定页的文件"""
    files = get_collection_files(col_code)
    if not files:
        msg = "⚠️ 集合为空。"
        if query:
            try:
                await query.edit_message_text(msg)
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    per_page = 5
    start = (page - 1) * per_page
    page_files = files[start:start + per_page]
    if not page_files:
        msg = "⚠️ 该页没有文件。"
        if query:
            try:
                await query.edit_message_text(msg)
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=msg)
        return

    sent = await send_file_group(context, chat_id, page_files)
    result_text = f"✅ 已发送第{page}页文件 ({sent}/{len(page_files)})"
    if query:
        try:
            await query.edit_message_text(result_text)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=result_text)