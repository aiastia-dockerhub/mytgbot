"""
Telegram 命令处理器
"""
import asyncio
import io
import logging
import aiohttp
from html import escape as html_escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from functools import wraps
from config import ADMIN_IDS, JAVBUS_API_URL
from modules.javbus_api import (
    get_single_movie_magnet,
    get_all_movie_ids_by_filter,
    search_all_movie_ids,
    get_magnets_for_movie_list,
)
# 详情类命令从 info_handlers 导入，供 re-export
from modules.info_handlers import movie_command, star_command, codes_command  # noqa: F401

logger = logging.getLogger(__name__)

# 每个 chat_id 对应的取消事件
_cancel_events: dict[int, asyncio.Event] = {}

# 每个 chat_id 对应的待收集磁力的影片 ID 列表（搜索/筛选后暂存）
_pending_magnets: dict[int, list[str]] = {}


def admin_only(func):
    """管理员权限装饰器（ADMIN_IDS 为空时所有人可用）"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes, *args, **kwargs):
        if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
            await update.effective_message.reply_text("⛔ 仅管理员可使用此 Bot。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def _get_cancel_event(chat_id: int) -> asyncio.Event:
    """获取或创建取消事件"""
    if chat_id not in _cancel_events:
        _cancel_events[chat_id] = asyncio.Event()
    return _cancel_events[chat_id]


@admin_only
async def help_command(update: Update, context: ContextTypes):
    """帮助命令"""
    text = (
        "🔞 <b>JavBus 磁力搜索 Bot</b>\n\n"
        "📋 <b>命令列表:</b>\n"
        "<code>/jav [番号]</code> — 查询单个影片磁力链接\n"
        "  示例: <code>/jav SSIS-406</code>\n\n"
        "<code>/jav_star [演员id]</code> — 直接获取演员全部影片磁力链接\n"
        "  示例: <code>/jav_star 2xi</code>\n\n"
        "<code>/jav_filter [类型] [值]</code> — 按类型筛选影片\n"
        "  类型: <code>star</code> <code>genre</code> <code>director</code> <code>studio</code> <code>label</code> <code>series</code>\n"
        "  示例: <code>/jav_filter star 2xi</code>\n\n"
        "<code>/jav_search [关键词]</code> — 搜索影片\n"
        "  示例: <code>/jav_search 三上</code>\n\n"
        "<code>/movie [番号]</code> — 查看影片详情（封面、演员、类别等）\n"
        "  示例: <code>/movie SSIS-406</code>\n\n"
        "<code>/star [演员id]</code> — 查看演员信息\n"
        "  示例: <code>/star 2xi</code>\n\n"
        "<code>/codes [演员id]</code> — 列出演员全部影片番号（不含磁力）\n"
        "  示例: <code>/codes 2xi</code>\n\n"
        "<code>/stop</code> — 停止当前批量任务\n\n"
        "📖 <b>说明:</b>\n"
        "• 演员ID 获取: 访问 javbus.com/star 页面，URL 中的ID\n"
        "• <code>/jav_star</code> 直接收集磁力链接并返回文件\n"
        "• <code>/jav_filter</code> 和 <code>/jav_search</code> 先展示影片列表，确认后再收集磁力\n"
        "• 批量任务执行中可随时用 <code>/stop</code> 停止"
    )
    await update.message.reply_text(text, parse_mode="HTML")


@admin_only
async def stop_command(update: Update, context: ContextTypes):
    """停止当前批量任务"""
    chat_id = update.effective_chat.id
    event = _cancel_events.get(chat_id)
    if event and not event.is_set():
        event.set()
        await update.message.reply_text("⏹ 已发送停止信号，正在中止...")
    else:
        await update.message.reply_text("ℹ️ 当前没有正在运行的任务")


@admin_only
async def jav_command(update: Update, context: ContextTypes):
    """查询单个影片的磁力链接"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "用法: <code>/jav [番号]</code>\n示例: <code>/jav SSIS-406</code>",
            parse_mode="HTML"
        )
        return

    movie_id = context.args[0].upper()
    await update.message.reply_text(
        f"🔍 正在查询 <code>{html_escape(movie_id)}</code> ...",
        parse_mode="HTML"
    )

    result = await get_single_movie_magnet(movie_id)
    if not result:
        await update.message.reply_text(
            f"❌ 未找到影片 <code>{html_escape(movie_id)}</code>",
            parse_mode="HTML"
        )
        return

    detail = result["detail"]
    magnets = result["magnets"]

    if not magnets:
        await update.message.reply_text(
            f"❌ 影片 <code>{html_escape(movie_id)}</code> 暂无磁力链接",
            parse_mode="HTML"
        )
        return

    title = html_escape(detail.get("title", movie_id))
    lines = [f"🎬 <b>{html_escape(movie_id)}</b>\n{title}\n"]

    for i, m in enumerate(magnets[:5], 1):
        size = html_escape(m.get("size", "?"))
        hd = "🎬" if m.get("isHD") else ""
        sub = "📝" if m.get("hasSubtitle") else ""
        lines.append(f"{i}. [{size}] {hd}{sub}")
        lines.append(f"<code>{html_escape(m['link'])}</code>\n")

    if len(magnets) > 5:
        lines.append(f"... 共 {len(magnets)} 个磁力链接")

    text = "\n".join(lines)
    if len(text) > 4000:
        best = max(magnets, key=lambda x: x.get('numberSize', 0) or 0)
        text = (
            f"🎬 <b>{html_escape(movie_id)}</b>\n{title}\n\n"
            f"🏆 最大文件: {html_escape(best.get('size', ''))}\n"
            f"<code>{html_escape(best['link'])}</code>"
        )

    await update.message.reply_text(text, parse_mode="HTML")


# ==================== jav_star: 直接收集磁力 ====================

@admin_only
async def jav_star_command(update: Update, context: ContextTypes):
    """获取演员全部影片磁力链接（直接收集，不确认）"""
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "用法: <code>/jav_star [演员id]</code>\n示例: <code>/jav_star 2xi</code>",
            parse_mode="HTML"
        )
        return

    star_id = context.args[0]
    chat_id = update.effective_chat.id
    cancel_event = _get_cancel_event(chat_id)
    cancel_event.clear()

    status_msg = await update.message.reply_text(
        f"🔍 正在获取演员 <code>{html_escape(star_id)}</code> 的影片列表...",
        parse_mode="HTML"
    )

    movie_ids = await get_all_movie_ids_by_filter("star", star_id)
    if not movie_ids:
        await update.message.reply_text(
            f"❌ 未找到演员 <code>{html_escape(star_id)}</code> 的影片",
            parse_mode="HTML"
        )
        return

    await status_msg.edit_text(
        f"📋 找到 <b>{len(movie_ids)}</b> 部影片，正在逐个收集磁力链接...\n"
        f"磁力链接收集: <b>0/{len(movie_ids)}</b>",
        parse_mode="HTML"
    )

    async def _progress(done, total):
        await status_msg.edit_text(
            f"📋 共 {total} 部影片，正在逐个收集磁力链接...\n"
            f"磁力链接收集: <b>{done}/{total}</b>",
            parse_mode="HTML"
        )

    results = await get_magnets_for_movie_list(
        movie_ids, progress_callback=_progress, cancel_event=cancel_event
    )

    if cancel_event.is_set():
        await update.message.reply_text("⏹ 任务已停止")
        return

    if not results:
        await update.message.reply_text("❌ 未能获取到磁力链接")
        return

    lines = [r['link'] for r in results if r.get('link')]
    content = "\n".join(lines)
    await _send_magnet_file(update, context, content, f"star_{star_id}.txt", len(results))


# ==================== 工具函数 ====================


async def _send_magnet_file(update, context, content, filename, count):
    """发送磁力链接 txt 文件"""
    bytes_io = io.BytesIO(content.encode("utf-8"))
    bytes_io.seek(0)
    try:
        await context.bot.send_document(
            chat_id=update.message.chat_id,
            document=bytes_io,
            filename=filename,
            caption=f"✅ 共收集到 {count} 个磁力链接",
            reply_to_message_id=update.effective_message.message_id
        )
        bytes_io.close()
    except Exception as e:
        logger.error("发送文件失败: %s", e)
        await update.message.reply_text(f"❌ 发送文件失败: {e}")


async def _send_magnet_file_by_chat(context, update, chat_id, content, filename, count, reply_to):
    """通过 chat_id 发送磁力链接 txt 文件（用于回调用）"""
    bytes_io = io.BytesIO(content.encode("utf-8"))
    bytes_io.seek(0)
    try:
        kwargs = {
            "chat_id": chat_id,
            "document": bytes_io,
            "filename": filename,
            "caption": f"✅ 共收集到 {count} 个磁力链接",
        }
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to
        await context.bot.send_document(**kwargs)
        bytes_io.close()
    except Exception as e:
        logger.error("发送文件失败: %s", e)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 发送磁力链接文件失败: {e}")
        except Exception:
            pass


# ==================== jav_filter: 先展示再确认 ====================

@admin_only
async def jav_filter_command(update: Update, context: ContextTypes):
    """按类型筛选：先收集影片 ID，展示后让用户确认是否收集磁力"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "用法: <code>/jav_filter [类型] [值]</code>\n"
            "类型: <code>star</code> <code>genre</code> <code>director</code> <code>studio</code> <code>label</code> <code>series</code>\n"
            "示例: <code>/jav_filter star 2xi</code>",
            parse_mode="HTML"
        )
        return

    filter_type = context.args[0]
    filter_value = context.args[1]

    valid_types = ("star", "genre", "director", "studio", "label", "series")
    if filter_type not in valid_types:
        types_str = ", ".join(f"<code>{t}</code>" for t in valid_types)
        await update.message.reply_text(
            f"❌ 无效类型 <code>{html_escape(filter_type)}</code>，可选: {types_str}",
            parse_mode="HTML"
        )
        return

    status_msg = await update.message.reply_text(
        f"🔍 正在按 <code>{html_escape(filter_type)}={html_escape(filter_value)}</code> 筛选影片列表...",
        parse_mode="HTML"
    )

    movie_ids = await get_all_movie_ids_by_filter(filter_type, filter_value)
    if not movie_ids:
        await update.message.reply_text("❌ 未找到符合条件的影片")
        return

    # 暂存搜索结果，点击按钮时直接使用，无需重新搜索
    chat_id = update.effective_chat.id
    _pending_magnets[chat_id] = movie_ids
    logger.info("jav_filter: chat_id=%s, 暂存 %d 个影片ID", chat_id, len(movie_ids))

    # 展示影片列表 + 确认按钮
    movie_list = ", ".join(f"<code>{html_escape(mid)}</code>" for mid in movie_ids[:50])
    text = (
        f"📋 按 <code>{html_escape(filter_type)}={html_escape(filter_value)}</code> 筛选到 <b>{len(movie_ids)}</b> 部影片：\n\n"
        f"{movie_list}"
    )
    if len(movie_ids) > 50:
        text += f"\n\n... 等共 {len(movie_ids)} 部"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 收集磁力链接", callback_data=f"magnet:filter:{filter_type}:{filter_value}"),
            InlineKeyboardButton("❌ 取消", callback_data="cancel"),
        ]
    ])

    await status_msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


# ==================== jav_search: 先展示再确认 ====================

@admin_only
async def jav_search_command(update: Update, context: ContextTypes):
    """搜索影片：先收集影片 ID，展示后让用户确认是否收集磁力"""
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "用法: <code>/jav_search [关键词]</code>\n示例: <code>/jav_search 三上</code>",
            parse_mode="HTML"
        )
        return

    keyword = " ".join(context.args)
    status_msg = await update.message.reply_text(
        f"🔍 正在搜索影片 <code>{html_escape(keyword)}</code> ...",
        parse_mode="HTML"
    )

    movie_ids = await search_all_movie_ids(keyword)
    if not movie_ids:
        await update.message.reply_text(
            f"❌ 未找到关键词 <code>{html_escape(keyword)}</code> 的影片",
            parse_mode="HTML"
        )
        return

    # 暂存搜索结果，点击按钮时直接使用，无需重新搜索
    chat_id = update.effective_chat.id
    _pending_magnets[chat_id] = movie_ids
    logger.info("jav_search: chat_id=%s, 暂存 %d 个影片ID", chat_id, len(movie_ids))

    # 展示影片列表 + 确认按钮
    movie_list = ", ".join(f"<code>{html_escape(mid)}</code>" for mid in movie_ids[:50])
    text = (
        f"📋 搜索 <code>{html_escape(keyword)}</code> 找到 <b>{len(movie_ids)}</b> 部影片：\n\n"
        f"{movie_list}"
    )
    if len(movie_ids) > 50:
        text += f"\n\n... 等共 {len(movie_ids)} 部"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 收集磁力链接", callback_data=f"magnet:search:{keyword}"),
            InlineKeyboardButton("❌ 取消", callback_data="cancel"),
        ]
    ])

    await status_msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


# ==================== 按钮回调处理 ====================

async def button_callback(update: Update, context: ContextTypes):
    """处理内联按钮回调"""
    query = update.callback_query
    await query.answer()

    data = query.data
    logger.info("button_callback: data=%s", data)

    try:
        # 取消按钮
        if data == "cancel":
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await query.edit_message_text(query.message.text + "\n\n❌ 已取消")
            return

        # 收集磁力链接
        if data.startswith("magnet:"):
            parts = data.split(":", 2)
            if len(parts) < 3:
                await query.message.reply_text("❌ 回调数据格式错误")
                return

            action = parts[1]  # filter / search
            param = parts[2]   # type:value / keyword

            # 移除旧按钮
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass

            chat_id = update.effective_chat.id

            # 从暂存中取出之前搜索到的影片 ID
            movie_ids = _pending_magnets.pop(chat_id, None)
            logger.info("button_callback: chat_id=%s, 暂存中有 %d 个影片ID", chat_id, len(movie_ids) if movie_ids else 0)

            if not movie_ids:
                # 暂存数据不存在（bot 重启等），回退到重新搜索
                logger.warning("button_callback: 暂存为空，回退重新搜索 action=%s param=%s", action, param)
                if action == "filter":
                    filter_type, filter_value = param.split(":", 1)
                    movie_ids = await get_all_movie_ids_by_filter(filter_type, filter_value)
                elif action == "search":
                    movie_ids = await search_all_movie_ids(param)

                if not movie_ids:
                    await query.message.reply_text("❌ 未找到影片，请重新使用 /jav_filter 或 /jav_search 搜索")
                    return

            cancel_event = _get_cancel_event(chat_id)
            cancel_event.clear()

            if action == "filter":
                filter_type, filter_value = param.split(":", 1)
                file_prefix = f"{filter_type}_{filter_value}"
            else:
                file_prefix = f"search_{param}"

            await _collect_magnets_with_ids(query, context, movie_ids, cancel_event, file_prefix)
            return

    except Exception as e:
        logger.error("button_callback 异常: %s", e, exc_info=True)
        try:
            await query.message.reply_text(f"❌ 处理按钮回调时出错: {e}")
        except Exception:
            pass


async def _collect_magnets_with_ids(query, context, movie_ids, cancel_event, file_prefix):
    """使用已有的影片 ID 列表直接收集磁力链接"""
    total = len(movie_ids)
    status_msg = await query.message.reply_text(
        f"📋 共 <b>{total}</b> 部影片，正在逐个收集磁力链接...\n"
        f"磁力链接收集: <b>0/{total}</b>",
        parse_mode="HTML"
    )

    async def _progress(done, total):
        if cancel_event.is_set():
            return
        try:
            await status_msg.edit_text(
                f"📋 共 {total} 部影片，正在逐个收集磁力链接...\n"
                f"磁力链接收集: <b>{done}/{total}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

    try:
        results = await get_magnets_for_movie_list(
            movie_ids, progress_callback=_progress, cancel_event=cancel_event
        )
    except Exception as e:
        logger.error("收集磁力链接异常: %s", e, exc_info=True)
        await query.message.reply_text(f"❌ 收集磁力链接时出错: {e}")
        return

    if cancel_event.is_set():
        await query.message.reply_text("⏹ 任务已停止")
        return

    if not results:
        await query.message.reply_text("❌ 未能获取到磁力链接")
        return

    lines = [r['link'] for r in results if r.get('link')]
    content = "\n".join(lines)
    await _send_magnet_file_by_chat(
        context, update=None, chat_id=query.message.chat_id,
        content=content, filename=f"{file_prefix}.txt",
        count=len(results), reply_to=None
    )

    # 更新状态消息为已完成
    try:
        await status_msg.edit_text(
            f"✅ 磁力链接收集完成！共 <b>{len(results)}</b> 个（总计 {total} 部影片）",
            parse_mode="HTML"
        )
    except Exception:
        pass
