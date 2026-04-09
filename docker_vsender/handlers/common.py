"""通用命令和用户请求处理器"""
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import ADMIN_USER_ID
from database.users import get_user
from database.requests import add_join_request
from handlers.utils import is_admin

logger = logging.getLogger(__name__)


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
        from database.requests import approve_request
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
        from database.requests import reject_request
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