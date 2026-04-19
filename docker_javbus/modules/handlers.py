"""
Telegram 命令处理器
"""
import asyncio
import io
import logging
import aiohttp
from html import escape as html_escape
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, filters
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

# 每个 chat_id 对应的待收集磁力的影片 ID 列表（搜索/筛选后暂存）
_pending_magnets: dict[int, list[str]] = {}

# 搜索结果消息追踪: message_id → (movie_ids, file_prefix)
# 用于回复消息触发收集
_search_result_messages: dict[int, tuple[list[str], str]] = {}


# ==================== 任务队列 ====================

class _TaskQueue:
    """每个 chat_id 一个 FIFO 队列，收集任务串行执行，bot 保持响应"""

    def __init__(self):
        self._queues: dict[int, asyncio.Queue] = {}
        self._workers: dict[int, asyncio.Task] = {}
        self._cancel_events: dict[int, asyncio.Event] = {}
        # 当前正在执行的任务描述
        self._current_task: dict[int, str] = {}

    def get_cancel_event(self, chat_id: int) -> asyncio.Event:
        if chat_id not in self._cancel_events:
            self._cancel_events[chat_id] = asyncio.Event()
        return self._cancel_events[chat_id]

    def queue_size(self, chat_id: int) -> int:
        q = self._queues.get(chat_id)
        return q.qsize() if q else 0

    def current_task_desc(self, chat_id: int) -> str | None:
        return self._current_task.get(chat_id)

    def is_running(self, chat_id: int) -> bool:
        return chat_id in self._current_task

    async def submit(self, chat_id: int, bot, coro_factory, description: str):
        """提交任务到队列。coro_factory 是 async def (...) -> None 的工厂函数"""
        if chat_id not in self._queues:
            self._queues[chat_id] = asyncio.Queue()

        # 放入队列: (coro_factory, description)
        await self._queues[chat_id].put((coro_factory, description))

        # 如果没有 worker 在运行，启动一个
        if chat_id not in self._workers or self._workers[chat_id].done():
            self._workers[chat_id] = asyncio.create_task(self._worker(chat_id, bot))

    async def _worker(self, chat_id: int, bot):
        """串行执行队列中的任务"""
        q = self._queues[chat_id]
        try:
            while not q.empty():
                coro_factory, description = await q.get()
                cancel_event = self.get_cancel_event(chat_id)
                cancel_event.clear()
                self._current_task[chat_id] = description

                try:
                    await coro_factory()
                except Exception as e:
                    logger.error("任务执行异常 [%s]: %s", description, e, exc_info=True)
                    try:
                        await bot.send_message(chat_id=chat_id, text=f"❌ 任务执行出错: {e}")
                    except Exception:
                        pass
                finally:
                    self._current_task.pop(chat_id, None)
                    q.task_done()
        finally:
            # worker 结束时清理
            self._workers.pop(chat_id, None)

    def cancel_current(self, chat_id: int) -> bool:
        """取消当前正在执行的任务"""
        event = self._cancel_events.get(chat_id)
        if event and not event.is_set() and chat_id in self._current_task:
            event.set()
            return True
        return False

    def clear_queue(self, chat_id: int) -> int:
        """清空等待中的任务，返回清空数量"""
        q = self._queues.get(chat_id)
        if not q:
            return 0
        count = q.qsize()
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
            except asyncio.QueueEmpty:
                break
        return count


# 全局任务队列实例
task_queue = _TaskQueue()
# 兼容旧代码
_cancel_events = task_queue._cancel_events


def _get_cancel_event(chat_id: int) -> asyncio.Event:
    return task_queue.get_cancel_event(chat_id)


def admin_only(func):
    """管理员权限装饰器（ADMIN_IDS 为空时所有人可用）"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes, *args, **kwargs):
        if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
            await update.effective_message.reply_text("⛔ 仅管理员可使用此 Bot。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


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
    """停止当前批量任务并清空队列"""
    chat_id = update.effective_chat.id
    stopped = task_queue.cancel_current(chat_id)
    cleared = task_queue.clear_queue(chat_id)
    parts = []
    if stopped:
        parts.append("⏹ 已发送停止信号，正在中止当前任务...")
    if cleared:
        parts.append(f"🗑 已取消 {cleared} 个排队中的任务")
    if not parts:
        await update.message.reply_text("ℹ️ 当前没有正在运行的任务")
    else:
        await update.message.reply_text("\n".join(parts))


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

    total = len(movie_ids)
    desc = f"jav_star {star_id} ({total}部)"
    queued = task_queue.queue_size(chat_id)
    await status_msg.edit_text(
        f"📋 找到 <b>{total}</b> 部影片"
        + (f"，排队中（前面还有 {queued + 1} 个任务）..." if task_queue.is_running(chat_id) else "，正在收集磁力链接..."),
        parse_mode="HTML"
    )

    async def _do_collect():
        cancel_event = _get_cancel_event(chat_id)
        await status_msg.edit_text(
            f"📋 共 {total} 部影片，正在逐个收集磁力链接...\n磁力链接收集: <b>0/{total}</b>",
            parse_mode="HTML"
        )

        async def _progress(done, total):
            if cancel_event.is_set():
                return
            try:
                await status_msg.edit_text(
                    f"📋 共 {total} 部影片，正在逐个收集磁力链接...\n磁力链接收集: <b>{done}/{total}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        results = await get_magnets_for_movie_list(
            movie_ids, progress_callback=_progress, cancel_event=cancel_event
        )
        if cancel_event.is_set():
            await context.bot.send_message(chat_id=chat_id, text="⏹ 任务已停止")
            return
        if not results:
            await context.bot.send_message(chat_id=chat_id, text="❌ 未能获取到磁力链接")
            return
        lines = [r['link'] for r in results if r.get('link')]
        content = "\n".join(lines)
        await _send_magnet_file_by_chat(
            context, update=None, chat_id=chat_id,
            content=content, filename=f"star_{star_id}.txt",
            count=len(results), reply_to=None
        )
        try:
            await status_msg.edit_text(
                f"✅ 磁力链接收集完成！共 <b>{len(results)}</b> 个（总计 {total} 部影片）",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await task_queue.submit(chat_id, context.bot, _do_collect, desc)


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

    # 超过 10 个影片时，额外发送影片ID列表 TXT（可回复触发收集）
    if len(movie_ids) > 10:
        file_prefix = f"{filter_type}_{filter_value}"
        id_content = "\n".join(movie_ids)
        await _send_txt_and_track(context, update.effective_chat.id, id_content, f"{file_prefix}_影片列表.txt", f"📋 共 {len(movie_ids)} 个影片ID，回复此文件可触发收集", file_prefix)

    # 记录搜索结果消息，用于回复触发
    _search_result_messages[status_msg.message_id] = (movie_ids, f"{filter_type}_{filter_value}")


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

    # 超过 10 个影片时，额外发送影片ID列表 TXT（可回复触发收集）
    if len(movie_ids) > 10:
        file_prefix = f"search_{keyword}"
        id_content = "\n".join(movie_ids)
        await _send_txt_and_track(context, update.effective_chat.id, id_content, f"{file_prefix}_影片列表.txt", f"📋 共 {len(movie_ids)} 个影片ID，回复此文件可触发收集", file_prefix)

    # 记录搜索结果消息，用于回复触发
    _search_result_messages[status_msg.message_id] = (movie_ids, f"search_{keyword}")


# ==================== 回复搜索结果触发收集 ====================

@admin_only
async def reply_search_handler(update: Update, context: ContextTypes):
    """用户回复搜索结果消息时，自动触发磁力链接收集"""
    if not update.message or not update.message.reply_to_message:
        return

    replied_msg_id = update.message.reply_to_message.message_id
    if replied_msg_id not in _search_result_messages:
        return

    movie_ids, file_prefix = _search_result_messages.pop(replied_msg_id)
    # 同时清理暂存
    chat_id = update.effective_chat.id
    _pending_magnets.pop(chat_id, None)

    total = len(movie_ids)
    desc = f"reply:{file_prefix} ({total}部)"
    queued = task_queue.queue_size(chat_id)
    if task_queue.is_running(chat_id):
        await update.message.reply_text(
            f"📋 {total} 部影片已加入队列（前面还有 {queued + 1} 个任务），请等待..."
        )
    else:
        await update.message.reply_text(
            f"📋 共 <b>{total}</b> 部影片，正在准备收集磁力链接...",
            parse_mode="HTML"
        )

    async def _do_collect():
        cancel_event = _get_cancel_event(chat_id)
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"📋 共 {total} 部影片，正在逐个收集磁力链接...\n磁力链接收集: <b>0/{total}</b>",
            parse_mode="HTML"
        )

        async def _progress(done, total):
            if cancel_event.is_set():
                return
            try:
                await status_msg.edit_text(
                    f"📋 共 {total} 部影片，正在逐个收集磁力链接...\n磁力链接收集: <b>{done}/{total}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        try:
            results = await get_magnets_for_movie_list(
                movie_ids, progress_callback=_progress, cancel_event=cancel_event
            )
        except Exception as e:
            logger.error("回复触发收集异常: %s", e, exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 收集磁力链接时出错: {e}")
            return

        if cancel_event.is_set():
            await context.bot.send_message(chat_id=chat_id, text="⏹ 任务已停止")
            return

        if not results:
            await context.bot.send_message(chat_id=chat_id, text="❌ 未能获取到磁力链接")
            return

        lines = [r['link'] for r in results if r.get('link')]
        content = "\n".join(lines)
        await _send_magnet_file_by_chat(
            context, update=None, chat_id=chat_id,
            content=content, filename=f"{file_prefix}.txt",
            count=len(results), reply_to=None
        )

        try:
            await status_msg.edit_text(
                f"✅ 磁力链接收集完成！共 <b>{len(results)}</b> 个（总计 {total} 部影片）",
                parse_mode="HTML"
            )
        except Exception:
            pass

    await task_queue.submit(chat_id, context.bot, _do_collect, desc)


async def _send_txt_and_track(context, chat_id, content, filename, caption, file_prefix):
    """发送 TXT 文件并追踪消息 ID，用于回复触发收集"""
    bytes_io = io.BytesIO(content.encode("utf-8"))
    bytes_io.seek(0)
    try:
        msg = await context.bot.send_document(
            chat_id=chat_id,
            document=bytes_io,
            filename=filename,
            caption=caption,
        )
        bytes_io.close()
        # 从文件名解析影片 ID 列表
        movie_ids = content.strip().split("\n")
        _search_result_messages[msg.message_id] = (movie_ids, file_prefix)
        logger.info("TXT文件已发送并追踪: msg_id=%s, %d个影片", msg.message_id, len(movie_ids))
    except Exception as e:
        logger.error("发送TXT文件失败: %s", e)


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

            if action == "filter":
                filter_type, filter_value = param.split(":", 1)
                file_prefix = f"{filter_type}_{filter_value}"
            else:
                file_prefix = f"search_{param}"

            total = len(movie_ids)
            desc = f"{action}:{param} ({total}部)"
            queued = task_queue.queue_size(chat_id)
            if task_queue.is_running(chat_id):
                await query.message.reply_text(
                    f"📋 {total} 部影片已加入队列（前面还有 {queued + 1} 个任务），请等待..."
                )

            async def _do_collect():
                await _collect_magnets_with_ids(query, context, movie_ids, file_prefix, chat_id)

            await task_queue.submit(chat_id, context.bot, _do_collect, desc)
            return

    except Exception as e:
        logger.error("button_callback 异常: %s", e, exc_info=True)
        try:
            await query.message.reply_text(f"❌ 处理按钮回调时出错: {e}")
        except Exception:
            pass


async def _collect_magnets_with_ids(query, context, movie_ids, file_prefix, chat_id):
    """使用已有的影片 ID 列表直接收集磁力链接（由任务队列调用）"""
    cancel_event = _get_cancel_event(chat_id)
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
        await context.bot.send_message(chat_id=chat_id, text=f"❌ 收集磁力链接时出错: {e}")
        return

    if cancel_event.is_set():
        await context.bot.send_message(chat_id=chat_id, text="⏹ 任务已停止")
        return

    if not results:
        await context.bot.send_message(chat_id=chat_id, text="❌ 未能获取到磁力链接")
        return

    lines = [r['link'] for r in results if r.get('link')]
    content = "\n".join(lines)
    await _send_magnet_file_by_chat(
        context, update=None, chat_id=chat_id,
        content=content, filename=f"{file_prefix}.txt",
        count=len(results), reply_to=None
    )

    try:
        await status_msg.edit_text(
            f"✅ 磁力链接收集完成！共 <b>{len(results)}</b> 个（总计 {total} 部影片）",
            parse_mode="HTML"
        )
    except Exception:
        pass
