"""管理员 - 用户管理命令处理器"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.users import (
    add_user, remove_user, ban_user, unban_user,
    get_all_users, get_user_count
)
from database.requests import get_pending_requests
from handlers.utils import is_admin

logger = logging.getLogger(__name__)


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