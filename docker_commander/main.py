"""Commander Bot - 指挥官 Bot 入口"""
import logging
import re
from functools import wraps

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN, ADMIN_IDS, WORK_GROUP_ID, get_enabled_bots, load_skills
from intent_router import IntentRouter
from bot_manager import BotManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# 全局实例
router = IntentRouter()
manager = BotManager()


# ==================== 工具函数 ====================
def escape_markdown(text: str) -> str:
    """转义 MarkdownV2 特殊字符"""
    if not text:
        return text
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\])', r'\\\1', text)


async def forward_response_to_user(update: Update, bot_username: str):
    """将 bot 的回复（含媒体）转发给用户，支持多条消息"""
    messages = manager.pop_response_message(bot_username)
    if messages is None:
        return False

    # 如果是单条消息，转为列表统一处理
    if not isinstance(messages, list):
        messages = [messages]

    chat_id = update.effective_chat.id
    forwarded_any = False

    for i, msg in enumerate(messages):
        if msg.photo:
            photo = msg.photo[-1]
            caption = msg.caption or (f"✅ @{bot_username}" if i == 0 else None)
            await update.message.bot.send_photo(
                chat_id=chat_id,
                photo=photo.file_id,
                caption=caption,
            )
            forwarded_any = True
        elif msg.document:
            caption = msg.caption or (f"✅ @{bot_username}" if i == 0 and not forwarded_any else None)
            await update.message.bot.send_document(
                chat_id=chat_id,
                document=msg.document.file_id,
                caption=caption,
            )
            forwarded_any = True
        elif msg.video:
            caption = msg.caption or (f"✅ @{bot_username}" if i == 0 else None)
            await update.message.bot.send_video(
                chat_id=chat_id,
                video=msg.video.file_id,
                caption=caption,
            )
            forwarded_any = True
        elif msg.animation:
            caption = msg.caption or (f"✅ @{bot_username}" if i == 0 else None)
            await update.message.bot.send_animation(
                chat_id=chat_id,
                animation=msg.animation.file_id,
                caption=caption,
            )
            forwarded_any = True
        elif msg.sticker:
            await update.message.bot.send_sticker(
                chat_id=chat_id,
                sticker=msg.sticker.file_id,
            )
            forwarded_any = True

    return forwarded_any


# ==================== 权限检查 ====================
def admin_only(func):
    """管理员权限检查装饰器"""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ 此 bot 仅限管理员使用。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


# ==================== 命令处理器 ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 和 /help 命令"""
    enabled = get_enabled_bots()
    bot_list = ""
    for key, info in enabled.items():
        bot_list += f"  • {info.get('name', key)} (@{info.get('username', '?')})\n"

    text = f"""🤖 *Commander Bot — 指挥官*

我是你的智能 Bot 指挥官，可以根据你的意图自动调用合适的 bot 来处理。

📋 *当前已启用的 Bot:*
{bot_list or "  暂无已启用的 bot"}

🎯 *使用方式:*
• 直接发送消息给我，我会判断意图并路由到合适的 bot
• 发送贴纸 → 自动转为图片
• 发送文本 → 智能判断并调用对应 bot

🔧 *管理命令:*
• /bots — 查看所有 bot 状态
• /status — 查看当前路由状态
• /reload — 重新加载技能配置
• /dispatch \\<bot_key> \\<command> — 手动向指定 bot 发送命令"""

    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/bots 查看所有 bot 状态"""
    skills = load_skills()
    status = manager.get_status()

    text = "📋 *所有 Bot 列表:*\n\n"
    for key, info in skills.items():
        enabled_icon = "✅" if info.get("enabled") else "❌"
        username = info.get("username", "?")
        name = info.get("name", key)

        text += f"{enabled_icon} *{name}* (@{username})\n"
        if key in status:
            s = status[key]
            text += f"  深度: {s['interaction_depth']} | 等待: {'是' if s['pending'] else '否'}\n"
        text += "\n"

    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/status 查看当前状态"""
    status = manager.get_status()
    if not status:
        await update.message.reply_text("当前没有活跃的 bot 任务。")
        return

    text = "📊 *当前状态:*\n\n"
    for key, s in status.items():
        text += f"• {s['name']} ({s['username']})\n"
        text += f"  交互深度: {s['interaction_depth']} | 等待中: {'是' if s['pending'] else '否'}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def reload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reload 重新加载技能配置"""
    router.reload_skills()
    skills = load_skills()
    enabled = {k: v for k, v in skills.items() if v.get("enabled")}
    await update.message.reply_text(
        f"✅ 配置已重新加载。\n"
        f"总技能数: {len(skills)}\n"
        f"已启用: {len(enabled)}"
    )


@admin_only
async def dispatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/dispatch 手动向指定 bot 发送命令"""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "用法: `/dispatch <bot_key> <命令>`\n\n"
            "例如: `/dispatch sticker2img /start`",
            parse_mode="Markdown",
        )
        return

    bot_key = args[0]
    command = " ".join(args[1:])

    # 查找 bot 信息
    skills = load_skills()
    if bot_key not in skills:
        await update.message.reply_text(f"❌ 未找到 bot: {bot_key}")
        return

    info = skills[bot_key]
    if not info.get("enabled"):
        await update.message.reply_text(f"❌ bot {bot_key} 未启用")
        return

    username = info.get("username", "")
    msg_id = await manager.send_to_bot(context, username, command)

    if msg_id:
        await update.message.reply_text(
            f"✅ 已发送到 @{username}\n命令: `{command}`",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(f"❌ 发送失败，请检查配置和限制。")


# ==================== 消息处理器 ====================
@admin_only
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户发送的文本消息"""
    text = update.message.text
    if not text:
        return

    user_id = update.effective_user.id
    logger.info("收到用户 %d 的文本消息: %s", user_id, text[:100])

    # 使用意图路由器分析
    result = await router.route(text, input_type="text")
    action = result.get("action", "unknown")
    reason = result.get("reason", "")

    logger.info("路由结果: action=%s, reason=%s", action, reason)

    if action == "route_to_bot":
        bot_key = result.get("bot_key", "")
        bot_username = result.get("bot_username", "")
        command = result.get("command", text)

        # 发送通知给用户
        await update.message.reply_text(
            f"🔄 正在调用 @{escape_markdown(bot_username)} 处理...\n"
            f"_原因: {escape_markdown(reason)}_",
            parse_mode="MarkdownV2",
        )

        # 发送到工作群
        msg_id = await manager.send_to_bot(context, bot_username, command)
        if msg_id:
            # 等待响应
            response = await manager.wait_for_response(context, bot_username)
            if response:
                # 尝试转发媒体内容（图片/文件等）
                forwarded = await forward_response_to_user(update, bot_username)
                if not forwarded:
                    # 纯文本回复
                    await update.message.reply_text(f"✅ @{bot_username} 回复:\n\n{response[:4000]}")
            else:
                await update.message.reply_text(f"⏳ @{bot_username} 处理中，暂未收到回复。")
        else:
            await update.message.reply_text("❌ 发送失败，请检查配置。")

    elif action == "chat_reply":
        reply = result.get("reply", "抱歉，我无法理解你的请求。")
        await update.message.reply_text(reply)

    else:
        await update.message.reply_text(
            f"🤔 无法确定你的意图。\n\n"
            f"原因: {reason}\n\n"
            f"你可以使用 /dispatch 命令手动指定 bot。",
        )


@admin_only
async def handle_sticker_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户发送的贴纸"""
    sticker = update.message.sticker
    if not sticker:
        return

    user_id = update.effective_user.id
    logger.info("收到用户 %d 的贴纸: %s", user_id, sticker.file_id)

    # 直接路由到 sticker2img
    result = await router.route("", input_type="sticker")

    if result.get("action") == "route_to_bot":
        bot_username = result.get("bot_username", "")

        await update.message.reply_text(
            f"🔄 正在将贴纸转发给 @{bot_username} 处理..."
        )

        # 发送贴纸到工作群
        msg_id = await manager.send_to_bot(
            context, bot_username, "forward_sticker",
            sticker_file_id=sticker.file_id,
        )

        if msg_id:
            # 等待响应（贴纸转换需要较长时间，使用120秒超时）
            response = await manager.wait_for_response(context, bot_username, timeout=120)
            if response:
                # 尝试转发媒体内容（图片/文件等）
                forwarded = await forward_response_to_user(update, bot_username)
                if not forwarded:
                    # 纯文本回复
                    await update.message.reply_text(f"✅ @{bot_username} 回复:\n\n{response[:4000]}")
            else:
                await update.message.reply_text(
                    f"⏳ @{bot_username} 处理超时。\n"
                    f"💡 提示: 请确保在工作群组中给 @{bot_username} 设置了管理员权限，"
                    f"否则 bot 在群组隐私模式下无法收到贴纸等非文本消息。"
                )
        else:
            await update.message.reply_text("❌ 贴纸转发失败，请检查配置。")
    else:
        await update.message.reply_text(
            "⚠️ 收到贴纸，但贴纸转图片 bot 未启用。\n"
            "请在 skills.yml 中启用 sticker2img。"
        )


async def handle_work_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理工作群中的消息（收集其他 bot 的回复）"""
    # 只处理来自 bot 的消息
    from_user = update.effective_user
    if not from_user or not from_user.is_bot:
        return

    # 忽略自己发的消息
    me = await context.bot.get_me()
    if from_user.id == me.id:
        return

    await manager.handle_bot_response(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """全局错误处理"""
    logger.error("异常: %s", context.error, exc_info=context.error)


# ==================== 启动 ====================
def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN 未设置！")
        return

    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS 未设置，任何人都可以使用此 bot！")

    if not WORK_GROUP_ID:
        logger.warning("WORK_GROUP_ID 未设置，Bot-to-Bot 通信将无法工作！")

    # 打印启动信息
    enabled = get_enabled_bots()
    logger.info("已启用的 bot: %s", list(enabled.keys()))

    # 构建 Application
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ==================== 注册处理器 ====================

    # 命令
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("bots", bots_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reload", reload_command))
    application.add_handler(CommandHandler("dispatch", dispatch_command))

    # 私聊/群聊消息（非工作群）
    # 需要判断 chat_id != WORK_GROUP_ID 才作为用户消息处理
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            handle_text_message,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Sticker.ALL,
            handle_sticker_message,
        )
    )

    # 工作群消息（收集 bot 回复）
    if WORK_GROUP_ID:
        application.add_handler(
            MessageHandler(
                filters.Chat(WORK_GROUP_ID) & ~filters.COMMAND,
                handle_work_group_message,
            )
        )

    # 错误处理
    application.add_error_handler(error_handler)

    # 启动
    logger.info("Commander Bot 启动中...")
    application.run_polling(drop_pending_updates=True)


async def post_init(application):
    """Bot 初始化后注册命令"""
    commands = [
        ("start", "查看帮助"),
        ("help", "查看帮助"),
        ("bots", "查看所有 bot"),
        ("status", "查看当前状态"),
        ("reload", "重新加载配置"),
        ("dispatch", "手动发送命令到 bot"),
    ]
    await application.bot.set_my_commands(commands)
    me = await application.bot.get_me()
    logger.info("Commander Bot @%s 已启动", me.username)


if __name__ == "__main__":
    main()