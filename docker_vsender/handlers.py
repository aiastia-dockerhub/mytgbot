"""命令和消息处理器"""
import logging
import asyncio
import os
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_USER_ID, VIDEO_ROOT, LIST_PAGE_SIZE, VIDEO_EXTS
from database import (
    add_user, remove_user, ban_user, unban_user, get_user,
    get_active_users, get_all_users, update_user_status, get_user_count,
    add_join_request, get_pending_requests, approve_request, reject_request,
    scan_video_files, get_video_files, get_video_by_name, get_unsent_videos,
    get_videos_in_dir, mark_video_unsent, get_video_stats, get_subdirs
)
from sender import broadcast_video, send_videos_batch, format_size

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    """检查是否是管理员"""
    return user_id in ADMIN_USER_ID


# ===================== 通用命令 =====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start - 欢迎信息"""
    user = update.effective_user
    user_info = get_user(user.id)

    if user_info:
        if user_info['status'] == 'active':
            text = (
                f"👋 你好 {user.first_name}！\n\n"
                f"✅ 你已在白名单中，可以正常接收视频。\n\n"
                f"📌 命令列表：\n"
                f"/status - 查看你的状态\n"
                f"/request - 请求加入白名单\n"
                f"/help - 查看帮助"
            )
        elif user_info['status'] == 'banned':
            text = "❌ 你已被管理员封禁。"
        elif user_info['status'] == 'stopped':
            text = (
                f"👋 你好 {user.first_name}！\n\n"
                f"⚠️ 你的状态为已停止（可能因为你拉黑了Bot）。\n"
                f"请联系管理员恢复。"
            )
        else:
            text = (
                f"👋 你好 {user.first_name}！\n\n"
                f"📌 可用命令：\n"
                f"/request - 请求加入白名单\n"
                f"/help - 查看帮助"
            )
    else:
        text = (
            f"👋 你好 {user.first_name}！\n\n"
            f"📢 这是一个视频分发 Bot。\n"
            f"你还未加入白名单，发送 /request 请求加入。\n\n"
            f"📌 命令列表：\n"
            f"/request - 请求加入白名单\n"
            f"/status - 查看你的状态\n"
            f"/help - 查看帮助"
        )

    await update.message.reply_text(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help - 帮助信息"""
    user_id = update.effective_user.id

    text = (
        "📖 **帮助信息**\n\n"
        "📌 **用户命令：**\n"
        "/start - 开始\n"
        "/status - 查看你的状态\n"
        "/request - 请求加入白名单\n"
        "/myid - 查看你的用户ID\n"
    )

    if is_admin(user_id):
        text += (
            "\n👑 **管理员命令：**\n"
            "/send <文件名> - 发送指定视频\n"
            "/sendnext <数量> - 发送N个未发送视频\n"
            "/senddir <文件夹> - 发送文件夹下所有视频\n"
            "/listvideos [页码] - 列出视频文件\n"
            "/listunsend [页码] - 列出未发送视频\n"
            "/dirs - 列出子文件夹\n"
            "/markunsend <文件名> - 标记视频为未发送\n"
            "/reload - 重新扫描视频目录\n"
            "/stats - 查看统计信息\n"
            "/adduser <ID> [备注] - 添加用户\n"
            "/removeuser <ID> - 移除用户\n"
            "/ban <ID> - 封禁用户\n"
            "/unban <ID> - 解封用户\n"
            "/listusers - 列出所有用户\n"
            "/pending - 查看待审批请求\n"
        )

    await update.message.reply_text(text)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/myid - 查看自己的用户ID"""
    user = update.effective_user
    await update.message.reply_text(
        f"🆔 你的用户ID: `{user.id}`", parse_mode='Markdown'
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status - 查看自己的状态"""
    user_id = update.effective_user.id
    user_info = get_user(user_id)

    if not user_info:
        await update.message.reply_text("❌ 你还未注册。发送 /request 请求加入白名单。")
        return

    status_map = {
        'active': '✅ 活跃',
        'stopped': '⏸️ 已停止',
        'banned': '🚫 已封禁'
    }
    status_text = status_map.get(user_info['status'], user_info['status'])

    text = (
        f"📊 **你的状态**\n\n"
        f"状态：{status_text}\n"
        f"用户名：{user_info.get('username', '未知')}\n"
        f"注册时间：{user_info.get('registered_at', '未知')}"
    )

    await update.message.reply_text(text)


# ===================== 用户请求 =====================

async def cmd_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/request - 请求加入白名单"""
    user = update.effective_user

    # 检查是否已在白名单
    user_info = get_user(user.id)
    if user_info:
        if user_info['status'] == 'active':
            await update.message.reply_text("✅ 你已在白名单中！")
        elif user_info['status'] == 'banned':
            await update.message.reply_text("❌ 你已被封禁，请联系管理员。")
        else:
            await update.message.reply_text("⚠️ 你的状态异常，请联系管理员。")
        return

    # 添加请求
    request_id = add_join_request(user.id, user.username or "")
    if request_id is None:
        await update.message.reply_text("⏳ 你已提交过请求，请等待管理员审批。")
        return

    await update.message.reply_text(
        "✅ 请求已提交！请等待管理员审批。"
    )

    # 通知管理员
    for admin_id in ADMIN_USER_ID:
        try:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ 批准", callback_data=f"approve_{request_id}"),
                    InlineKeyboardButton("❌ 拒绝", callback_data=f"reject_{request_id}")
                ]
            ])
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"📥 **新的加入请求**\n\n"
                    f"用户ID: `{user.id}`\n"
                    f"用户名: @{user.username or '未知'}\n"
                    f"姓名: {user.first_name} {user.last_name or ''}"
                ),
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error("通知管理员 %s 失败: %s", admin_id, e)


async def handle_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理审批回调"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if not is_admin(user_id):
        await query.answer("❌ 仅管理员可用", show_alert=True)
        return

    data = query.data

    if data.startswith("approve_"):
        request_id = int(data.split("_")[1])
        req = approve_request(request_id, user_id)
        if req:
            # 更新管理员消息
            await query.edit_message_text(
                f"✅ 已批准\n\n"
                f"用户ID: `{req['user_id']}`\n"
                f"用户名: @{req['username'] or '未知'}\n"
                f"审批人: `{user_id}`",
                parse_mode='Markdown'
            )
            # 通知用户
            try:
                await context.bot.send_message(
                    chat_id=req['user_id'],
                    text="🎉 你的加入请求已被批准！现在可以接收视频了。"
                )
            except Exception:
                pass
        else:
            await query.edit_message_text("❌ 请求不存在或已处理。")

    elif data.startswith("reject_"):
        request_id = int(data.split("_")[1])
        req = reject_request(request_id, user_id)
        if req:
            await query.edit_message_text(
                f"❌ 已拒绝\n\n"
                f"用户ID: `{req['user_id']}`\n"
                f"用户名: @{req['username'] or '未知'}\n"
                f"审批人: `{user_id}`",
                parse_mode='Markdown'
            )
            # 通知用户
            try:
                await context.bot.send_message(
                    chat_id=req['user_id'],
                    text="❌ 你的加入请求已被拒绝。"
                )
            except Exception:
                pass
        else:
            await query.edit_message_text("❌ 请求不存在或已处理。")


# ===================== 管理员 - 用户管理 =====================

async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/adduser <ID> [备注] - 添加用户到白名单"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    if not context.args:
        await update.message.reply_text("用法: /adduser <用户ID> [备注]")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 无效的用户ID")
        return

    notes = " ".join(context.args[1:]) if len(context.args) > 1 else ""

    success = add_user(target_id, "", added_by=update.effective_user.id, notes=notes)
    if success:
        await update.message.reply_text(f"✅ 已添加用户 `{target_id}` 到白名单。", parse_mode='Markdown')
        # 通知用户
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 你已被管理员添加到视频分发白名单！发送 /start 开始。"
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(f"⚠️ 用户 `{target_id}` 已在白名单中。", parse_mode='Markdown')


async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/removeuser <ID> - 移除用户"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    if not context.args:
        await update.message.reply_text("用法: /removeuser <用户ID>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 无效的用户ID")
        return

    success = remove_user(target_id)
    if success:
        await update.message.reply_text(f"✅ 已移除用户 `{target_id}`。", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"⚠️ 用户 `{target_id}` 不在白名单中。", parse_mode='Markdown')


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ban <ID> - 封禁用户"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    if not context.args:
        await update.message.reply_text("用法: /ban <用户ID>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 无效的用户ID")
        return

    success = ban_user(target_id)
    if success:
        await update.message.reply_text(f"🚫 已封禁用户 `{target_id}`。", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"⚠️ 用户 `{target_id}` 不存在。", parse_mode='Markdown')


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/unban <ID> - 解封用户"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    if not context.args:
        await update.message.reply_text("用法: /unban <用户ID>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ 无效的用户ID")
        return

    success = unban_user(target_id)
    if success:
        await update.message.reply_text(f"✅ 已解封用户 `{target_id}`。", parse_mode='Markdown')
    else:
        await update.message.reply_text(f"⚠️ 用户 `{target_id}` 不存在。", parse_mode='Markdown')


async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/listusers - 列出所有用户"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    users = get_all_users()
    if not users:
        await update.message.reply_text("📋 用户列表为空。")
        return

    count = get_user_count()
    status_map = {'active': '✅', 'stopped': '⏸️', 'banned': '🚫'}

    lines = [f"📋 **用户列表** (总计: {count['total']} / 活跃: {count['active']} / 封禁: {count['banned']})\n"]
    for u in users:
        status_icon = status_map.get(u['status'], '❓')
        username = f"@{u['username']}" if u['username'] else "无用户名"
        lines.append(f"{status_icon} `{u['user_id']}` {username}")

    text = "\n".join(lines)
    # Telegram 消息长度限制
    if len(text) > 4096:
        # 分段发送
        chunks = []
        current = lines[0] + "\n"
        for line in lines[1:]:
            if len(current) + len(line) + 1 > 4000:
                chunks.append(current)
                current = line + "\n"
            else:
                current += line + "\n"
        chunks.append(current)

        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, parse_mode='Markdown')


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pending - 查看待审批请求"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 仅管理员可用")
        return

    requests = get_pending_requests()
    if not requests:
        await update.message.reply_text("📋 没有待审批的请求。")
        return

    lines = [f"📥 **待审批请求** ({len(requests)} 个)\n"]
    for req in requests:
        lines.append(
            f"#{req['id']} - `{req['user_id']}` @{req['username'] or '未知'} ({req['created_at']})"
        )

    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode='Markdown')


# ===================== 管理员 - 视频发送 =====================

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