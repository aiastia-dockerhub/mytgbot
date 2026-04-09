"""管理员 - 视频发送命令处理器"""
import asyncio
import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import VIDEO_ROOT, LIST_PAGE_SIZE
from database.videos import (
    scan_video_files, get_video_files, get_video_by_name, get_unsent_videos,
    get_videos_in_dir, mark_video_unsent, get_video_stats, get_subdirs
)
from database.users import get_user_count
from sender import broadcast_video, send_videos_batch, format_size
from handlers.utils import is_admin

logger = logging.getLogger(__name__)


async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reload - 重新扫描视频目录"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    msg = await update.message.reply_text("🔍 正在扫描视频目录...")

    result = scan_video_files()
    stats = get_video_stats()

    text = (
        f"✅ 扫描完成！\n\n"
        f"📊 发现视频: {result['total']} 个\n"
        f"🆕 新增: {result['new']} 个\n"
        f"✅ 已发送: {stats['sent']} 个\n"
        f"⬜ 未发送: {stats['unsent']} 个\n"
        f"📦 总大小: {format_size(stats['total_size'])}"
    )

    await msg.edit_text(text)


async def cmd_listvideos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/listvideos [页码] - 列出视频文件"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    page = 1
    if context.args:
        try:
            page = int(context.args[0])
        except ValueError:
            pass

    result = get_video_files(page=page, page_size=LIST_PAGE_SIZE)
    if not result['items']:
        await update.message.reply_text("📋 没有视频文件。发送 /reload 扫描目录。")
        return

    lines = [f"📂 **视频列表** (第 {page}/{result['total_pages']} 页, 共 {result['total']} 个)\n"]
    for item in result['items']:
        status_icon = "✅" if item['status'] == 'sent' else "⬜"
        rel_path = os.path.relpath(item['file_path'], VIDEO_ROOT)
        size = format_size(item['file_size'])
        lines.append(f"{status_icon} {rel_path} ({size})")

    text = "\n".join(lines)

    # 分页按钮
    keyboard = None
    if result['total_pages'] > 1:
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"vpage_{page - 1}"))
        if page < result['total_pages']:
            buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"vpage_{page + 1}"))
        keyboard = InlineKeyboardMarkup([buttons])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def cmd_listunsend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/listunsend [页码] - 列出未发送视频"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    page = 1
    if context.args:
        try:
            page = int(context.args[0])
        except ValueError:
            pass

    result = get_video_files(status='unsend', page=page, page_size=LIST_PAGE_SIZE)
    if not result['items']:
        await update.message.reply_text("✅ 没有未发送的视频。")
        return

    lines = [f"⬜ **未发送视频** (第 {page}/{result['total_pages']} 页, 共 {result['total']} 个)\n"]
    for item in result['items']:
        rel_path = os.path.relpath(item['file_path'], VIDEO_ROOT)
        size = format_size(item['file_size'])
        lines.append(f"⬜ {rel_path} ({size})")

    text = "\n".join(lines)

    keyboard = None
    if result['total_pages'] > 1:
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"upage_{page - 1}"))
        if page < result['total_pages']:
            buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"upage_{page + 1}"))
        keyboard = InlineKeyboardMarkup([buttons])

    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def handle_listpage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理列表分页回调"""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    data = query.data
    if data.startswith("vpage_"):
        page = int(data.split("_")[1])
        result = get_video_files(page=page, page_size=LIST_PAGE_SIZE)

        lines = [f"📂 **视频列表** (第 {page}/{result['total_pages']} 页, 共 {result['total']} 个)\n"]
        for item in result['items']:
            status_icon = "✅" if item['status'] == 'sent' else "⬜"
            rel_path = os.path.relpath(item['file_path'], VIDEO_ROOT)
            size = format_size(item['file_size'])
            lines.append(f"{status_icon} {rel_path} ({size})")

        text = "\n".join(lines)
        keyboard = None
        if result['total_pages'] > 1:
            buttons = []
            if page > 1:
                buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"vpage_{page - 1}"))
            if page < result['total_pages']:
                buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"vpage_{page + 1}"))
            keyboard = InlineKeyboardMarkup([buttons])

        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)

    elif data.startswith("upage_"):
        page = int(data.split("_")[1])
        result = get_video_files(status='unsend', page=page, page_size=LIST_PAGE_SIZE)

        lines = [f"⬜ **未发送视频** (第 {page}/{result['total_pages']} 页, 共 {result['total']} 个)\n"]
        for item in result['items']:
            rel_path = os.path.relpath(item['file_path'], VIDEO_ROOT)
            size = format_size(item['file_size'])
            lines.append(f"⬜ {rel_path} ({size})")

        text = "\n".join(lines)
        keyboard = None
        if result['total_pages'] > 1:
            buttons = []
            if page > 1:
                buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"upage_{page - 1}"))
            if page < result['total_pages']:
                buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"upage_{page + 1}"))
            keyboard = InlineKeyboardMarkup([buttons])

        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def cmd_dirs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dirs - 列出子文件夹"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    dirs = get_subdirs()
    if not dirs:
        await update.message.reply_text("📂 没有视频文件夹。发送 /reload 扫描。")
        return

    lines = [f"📂 **文件夹列表**\n"]
    for d in dirs:
        lines.append(f"📁 {d['dir']} ({d['count']} 个视频)")

    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode='Markdown')


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/send <文件名> - 发送指定视频"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    if not context.args:
        await update.message.reply_text("用法: /send <文件名或相对路径>\n例: /send video.mp4\n例: /send folder/video.mp4")
        return

    file_name = " ".join(context.args)
    video = get_video_by_name(file_name)

    if not video:
        await update.message.reply_text(f"❌ 未找到视频: {file_name}\n发送 /listvideos 查看可用视频。")
        return

    if not os.path.exists(video['file_path']):
        await update.message.reply_text(f"❌ 文件不存在: {video['file_path']}")
        return

    caption = f"📹 {video['file_name']}"

    # 异步发送，避免阻塞
    asyncio.create_task(
        broadcast_video(
            context=context,
            video_path=video['file_path'],
            video_file_id=video['id'],
            admin_user_id=update.effective_user.id,
            caption=caption
        )
    )

    await update.message.reply_text(
        f"📤 开始发送: {video['file_name']}\n"
        f"📦 大小: {format_size(video['file_size'])}"
    )


async def cmd_sendnext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sendnext <数量> - 发送N个未发送的视频"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    count = 1
    if context.args:
        try:
            count = int(context.args[0])
            if count < 1:
                count = 1
            if count > 50:
                count = 50
        except ValueError:
            await update.message.reply_text("用法: /sendnext <数量>\n例: /sendnext 5")
            return

    videos = get_unsent_videos(count)
    if not videos:
        await update.message.reply_text("✅ 没有未发送的视频了！发送 /reload 扫描新视频。")
        return

    await update.message.reply_text(
        f"📤 准备发送 {len(videos)} 个未发送视频...\n"
        f"{'🔹 ' + chr(10).join(os.path.relpath(v['file_path'], VIDEO_ROOT) for v in videos)}"
    )

    # 异步批量发送
    asyncio.create_task(
        send_videos_batch(
            context=context,
            videos=videos,
            admin_user_id=update.effective_user.id
        )
    )


async def cmd_senddir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/senddir <文件夹> - 发送文件夹下所有视频"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    if not context.args:
        await update.message.reply_text("用法: /senddir <文件夹名>\n例: /senddir folder_a\n发送 /dirs 查看文件夹列表。")
        return

    subdir = " ".join(context.args)
    videos = get_videos_in_dir(subdir)

    if not videos:
        await update.message.reply_text(f"❌ 文件夹 '{subdir}' 下没有视频文件。")
        return

    # 确认发送
    lines = [f"📂 文件夹 '{subdir}' 下发现 {len(videos)} 个视频:\n"]
    for v in videos:
        status_icon = "✅" if v['status'] == 'sent' else "⬜"
        lines.append(f"{status_icon} {v['file_name']} ({format_size(v['file_size'])})")

    unsent_count = sum(1 for v in videos if v['status'] == 'unsend')
    lines.append(f"\n⬜ 未发送: {unsent_count} | ✅ 已发送: {len(videos) - unsent_count}")
    lines.append("是否发送？")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 发送全部", callback_data=f"sendall_{subdir}"),
            InlineKeyboardButton("⬜ 仅发未发送", callback_data=f"sendunsent_{subdir}")
        ],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_send")]
    ])

    text = "\n".join(lines)
    # 存储视频信息到 bot_data 供回调使用
    context.bot_data[f'dir_videos_{subdir}'] = videos

    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_senddir_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理发送目录回调"""
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    data = query.data

    if data == "cancel_send":
        await query.edit_message_text("❌ 已取消发送。")
        return

    if data.startswith("sendall_"):
        subdir = data.replace("sendall_", "", 1)
        videos = context.bot_data.get(f'dir_videos_{subdir}', [])
        if not videos:
            videos = get_videos_in_dir(subdir)
    elif data.startswith("sendunsent_"):
        subdir = data.replace("sendunsent_", "", 1)
        all_videos = context.bot_data.get(f'dir_videos_{subdir}', [])
        if not all_videos:
            all_videos = get_videos_in_dir(subdir)
        videos = [v for v in all_videos if v['status'] == 'unsend']
        if not videos:
            await query.edit_message_text("✅ 没有未发送的视频。")
            return
    else:
        return

    await query.edit_message_text(
        f"📤 开始发送 {len(videos)} 个视频..."
    )

    # 异步批量发送
    asyncio.create_task(
        send_videos_batch(
            context=context,
            videos=videos,
            admin_user_id=query.from_user.id
        )
    )


async def cmd_markunsend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/markunsend <文件名> - 标记视频为未发送"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    if not context.args:
        await update.message.reply_text("用法: /markunsend <文件名>")
        return

    file_name = " ".join(context.args)
    video = get_video_by_name(file_name)

    if not video:
        await update.message.reply_text(f"❌ 未找到视频: {file_name}")
        return

    mark_video_unsent(video['id'])
    await update.message.reply_text(
        f"✅ 已标记为未发送: {video['file_name']}\n"
        f"下次 /sendnext 时会被选中。"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats - 查看统计信息"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    user_count = get_user_count()
    video_stats = get_video_stats()

    text = (
        f"📈 **系统统计**\n\n"
        f"👥 **用户:**\n"
        f"  总计: {user_count['total']}\n"
        f"  活跃: {user_count['active']}\n"
        f"  封禁: {user_count['banned']}\n\n"
        f"📹 **视频:**\n"
        f"  总计: {video_stats['total']}\n"
        f"  已发送: {video_stats['sent']}\n"
        f"  未发送: {video_stats['unsent']}\n"
        f"  总大小: {format_size(video_stats['total_size'])}"
    )

    await update.message.reply_text(text, parse_mode='Markdown')