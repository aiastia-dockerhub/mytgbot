"""回调按钮处理器模块"""
import asyncio
import logging
import traceback

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
    logger.info("_resolve_key: sk=%s, found=%s, map_keys=%s, map_size=%d",
                sk, bool(col_code), list(cb_map.keys()), len(cb_map))
    if not col_code:
        logger.warning("_resolve_key 失败: sk=%s 在 cb_map 中不存在! cb_map 内容: %s",
                       sk, dict(cb_map))
    return col_code


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理内联按钮回调"""
    logger.info("========== 按钮回调开始 ==========")

    # === 安全获取 query 对象 ===
    if not update.callback_query:
        logger.error("button_callback: update.callback_query 为 None! update=%s", update)
        return

    query = update.callback_query
    data = query.data

    # === 修正 chat_id 获取：优先使用 message.chat_id，兼容群组和私聊 ===
    if query.message:
        chat_id = query.message.chat_id
        chat_type = query.message.chat.type if query.message.chat else "unknown"
    else:
        chat_id = query.from_user.id
        chat_type = "unknown(no_message)"

    user_id = query.from_user.id

    logger.info("回调数据: data=%r (len=%d)", data, len(data) if data else 0)
    logger.info("用户信息: user_id=%s, chat_id=%s, chat_type=%s", user_id, chat_id, chat_type)
    logger.info("bot_data cb_map 大小: %d", len(context.bot_data.get('cb_map', {})))

    # === answer 回调 ===
    try:
        await query.answer()
        logger.debug("query.answer() 成功")
    except Exception as e:
        logger.error("query.answer() 失败 (可能回调已过期): %s, data=%s", e, data)

    # === 数据为空检查 ===
    if not data:
        logger.error("button_callback: callback_data 为空! query=%s", query)
        try:
            await context.bot.send_message(chat_id=chat_id, text="❌ 回调数据为空，请重试。")
        except Exception:
            pass
        return

    try:
        # 短格式: s|key, a|key, p|key|page
        if data.startswith("s|") or data.startswith("a|") or data.startswith("p|"):
            action = data[0]
            rest = data[2:]
            logger.info("短格式回调: action=%s, rest=%s", action, rest)

            if action == 's':
                # 全部发送: s|key
                sk = rest
                logger.info("处理全部发送: sk=%s", sk)
                col_code = _resolve_key(context, sk)
                if not col_code:
                    logger.warning("全部发送失败: sk=%s 无法解析, cb_map=%s", sk, list(context.bot_data.get('cb_map', {}).keys()))
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 按钮已过期，请重新发送集合代码。")
                    return
                logger.info("开始全部发送: col_code=%s, chat_id=%s", col_code, chat_id)
                await _send_all(context, chat_id, col_code, query)
                logger.info("全部发送完成: col_code=%s", col_code)

            elif action == 'a':
                # 自动发送: a|key
                sk = rest
                logger.info("处理自动发送: sk=%s", sk)
                col_code = _resolve_key(context, sk)
                if not col_code:
                    logger.warning("自动发送失败: sk=%s 无法解析", sk)
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 按钮已过期，请重新发送集合代码。")
                    return
                logger.info("开始自动发送: col_code=%s, chat_id=%s, user_id=%s", col_code, chat_id, user_id)
                await _auto_send(context, chat_id, col_code, user_id, query)
                logger.info("自动发送完成: col_code=%s", col_code)

            elif action == 'p':
                # 分页: p|key|page
                parts = rest.split("|")
                logger.info("处理分页: parts=%s", parts)
                if len(parts) < 2:
                    logger.error("分页数据格式错误: rest=%s, parts=%s", rest, parts)
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 数据格式错误。")
                    return
                sk = parts[0]
                try:
                    page = int(parts[1])
                except ValueError:
                    logger.error("分页页码不是数字: parts[1]=%s", parts[1])
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 页码格式错误。")
                    return
                col_code = _resolve_key(context, sk)
                if not col_code:
                    logger.warning("分页失败: sk=%s 无法解析", sk)
                    await context.bot.send_message(chat_id=chat_id, text="⚠️ 按钮已过期，请重新发送集合代码。")
                    return
                logger.info("开始分页: col_code=%s, page=%d", col_code, page)
                await _send_page(context, chat_id, col_code, page, query)
                logger.info("分页完成: col_code=%s, page=%d", col_code, page)

        # 旧格式兼容: col_send|code, col_auto|code, col_page|code|page, page_send|code|page
        elif data.startswith("col_send|"):
            col_code = data.split("|", 1)[1]
            logger.info("旧格式全部发送: col_code=%s", col_code)
            await _send_all(context, chat_id, col_code, query)

        elif data.startswith("col_auto|"):
            col_code = data.split("|", 1)[1]
            logger.info("旧格式自动发送: col_code=%s", col_code)
            await _auto_send(context, chat_id, col_code, user_id, query)

        elif data.startswith("col_page|"):
            first_pipe = data.index("|", len("col_page|"))
            col_code = data[len("col_page|"):first_pipe]
            page = int(data[first_pipe + 1:])
            logger.info("旧格式分页: col_code=%s, page=%d", col_code, page)
            await _send_page(context, chat_id, col_code, page, query)

        elif data.startswith("page_send|"):
            first_pipe = data.index("|", len("page_send|"))
            col_code = data[len("page_send|"):first_pipe]
            page = int(data[first_pipe + 1:])
            logger.info("旧格式发送本页: col_code=%s, page=%d", col_code, page)
            await _send_page_files(context, chat_id, col_code, page, query)

        elif data == "stop_auto":
            logger.info("处理停止自动发送: user_id=%s", user_id)
            context.user_data['stop_auto_send'] = True
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                logger.warning("停止按钮: 编辑消息失败 (可忽略): %s", e)
            await context.bot.send_message(chat_id=chat_id, text="⏹ 已停止自动发送。")

        elif data == "noop":
            logger.debug("noop 回调")

        else:
            logger.warning("未知的回调数据: %r", data)
            await context.bot.send_message(chat_id=chat_id, text=f"❓ 未知操作: {data}")

    except Exception as e:
        logger.error("按钮回调处理失败: data=%r, error=%s", data, e, exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 操作失败: {e}")
        except Exception as e2:
            logger.error("发送错误消息也失败: %s\n原始错误: %s", e2, e)

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
    logger.info("_auto_send 开始: col_code=%s, chat_id=%s, user_id=%s", col_code, chat_id, user_id)
    files = get_collection_files(col_code)
    logger.info("_auto_send: 查询到 %d 个文件", len(files) if files else 0)
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
    logger.info("_send_page: col_code=%s, page=%d, chat_id=%s", col_code, page, chat_id)
    files = get_collection_files(col_code)
    col_info = get_collection(col_code)
    logger.info("_send_page: files=%d, col_info=%s", len(files) if files else 0, bool(col_info))
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
    logger.info("_send_page_files: col_code=%s, page=%d, chat_id=%s", col_code, page, chat_id)
    files = get_collection_files(col_code)
    logger.info("_send_page_files: files=%d", len(files) if files else 0)
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

    logger.info("_send_page_files: 准备发送 %d 个文件", len(page_files))
    sent = await send_file_group(context, chat_id, page_files)
    result_text = f"✅ 已发送第{page}页文件 ({sent}/{len(page_files)})"
    logger.info("_send_page_files 完成: %s", result_text)
    if query:
        try:
            await query.edit_message_text(result_text)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=result_text)