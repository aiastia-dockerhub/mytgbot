"""
Bot 命令与消息处理器

调用 register_all(app) 一行完成所有 handler 注册。
"""
import logging
import os
import tempfile
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    filters,
)

import database as db
from decorators import admin_only
from patterns import classify_message, extract_messages

logger = logging.getLogger(__name__)


# ── 处理普通消息（提取 & 保存）───────────────────────────

async def handle_message(update: Update, context: CallbackContext):
    text = update.message.text
    message_id = update.message.message_id
    extracted = extract_messages(text)

    if not extracted:
        await update.message.reply_text("未找到可提取的内容。", reply_to_message_id=message_id)
        return

    user_id = update.effective_user.id
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    saved_count = 0

    for message in set(extracted):
        msg_type = classify_message(message)
        if msg_type is None:
            continue

        try:
            db.execute(
                "INSERT INTO messages (user_id, content, type, created_at) VALUES (?, ?, ?, ?)",
                (user_id, message, msg_type, now),
            )
            saved_count += 1
        except Exception:
            pass  # 忽略重复内容（UNIQUE 约束）

    context.user_data["save_count"] = context.user_data.get("save_count", 0) + saved_count
    await update.message.reply_text(
        f"提取到以下内容：\n{chr(10).join(extracted)}",
        reply_to_message_id=message_id,
    )


# ── /save ─────────────────────────────────────────────────

async def save_messages(update: Update, context: CallbackContext):
    save_count = context.user_data.get("save_count", 0)
    await update.message.reply_text(f"成功保存 {save_count} 条消息。")
    context.user_data["save_count"] = 0


# ── /send ─────────────────────────────────────────────────

async def send_messages(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    now = datetime.now().isoformat(sep=" ", timespec="seconds")

    row = db.query_one("SELECT last_send_time FROM user_status WHERE user_id = ?", (user_id,))
    last_send_time = row[0] if row and row[0] else None

    if last_send_time:
        rows = db.query(
            "SELECT content, type, created_at FROM messages WHERE user_id = ? AND created_at > ? ORDER BY created_at",
            (user_id, last_send_time),
        )
    else:
        rows = db.query(
            "SELECT content, type, created_at FROM messages WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        )

    if not rows:
        await update.message.reply_text("没有可发送的内容。")
        db.execute(
            "INSERT OR REPLACE INTO user_status (user_id, last_send_time) VALUES (?, ?)",
            (user_id, now),
        )
        return

    # 按类型分组
    grouped: dict[str, list[tuple]] = {}
    total_length = 0
    for content, msg_type, created_at in rows:
        grouped.setdefault(msg_type, []).append((content, created_at))
        total_length += len(content) + 1

    if total_length > 4000:
        # 内容过长 → 发送文件
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        ) as tmp:
            tmp.write(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            tmp.write(f"总消息数：{len(rows)}\n\n")
            for msg_type, messages in grouped.items():
                tmp.write(f"\n=== {msg_type} (共 {len(messages)} 条) ===\n")
                for content, created_at in messages:
                    tmp.write(f"{created_at}: {content}\n")
                tmp.write("\n")

        with open(tmp.name, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"new_messages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                caption="这是您的新消息",
            )
        os.unlink(tmp.name)
    else:
        for msg_type, messages in grouped.items():
            contents = [f"{created_at}: {content}" for content, created_at in messages]
            await update.message.reply_text(f"类型：{msg_type}\n{chr(10).join(contents)}")

    db.execute(
        "INSERT OR REPLACE INTO user_status (user_id, last_send_time) VALUES (?, ?)",
        (user_id, now),
    )


# ── /all / /send_all ─────────────────────────────────────

async def send_all_messages(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    rows = db.query(
        "SELECT content, type, created_at FROM messages WHERE user_id = ? ORDER BY created_at",
        (user_id,),
    )

    if not rows:
        await update.message.reply_text("没有保存的消息。")
        return

    grouped: dict[str, list[tuple]] = {}
    for content, msg_type, created_at in rows:
        grouped.setdefault(msg_type, []).append((content, created_at))

    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".txt", encoding="utf-8"
    ) as tmp:
        tmp.write(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        tmp.write(f"总消息数：{len(rows)}\n\n")
        for msg_type, messages in grouped.items():
            tmp.write(f"\n=== {msg_type} (共 {len(messages)} 条) ===\n")
            for content, created_at in messages:
                tmp.write(f"{created_at}: {content}\n")
            tmp.write("\n")

    with open(tmp.name, "rb") as file:
        await update.message.reply_document(
            document=file,
            filename=f"messages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            caption="这是您保存的所有消息",
        )
    os.unlink(tmp.name)


# ── 管理员命令 ────────────────────────────────────────────

@admin_only
async def get_user_stats(update: Update, context: CallbackContext):
    """获取所有用户的统计信息"""
    stats = db.query(
        "SELECT user_id, COUNT(*) as message_count FROM messages GROUP BY user_id"
    )
    if not stats:
        await update.message.reply_text("目前还没有任何用户数据。")
        return

    lines = ["用户统计信息：\n"]
    for user_id, count in stats:
        lines.append(f"用户 ID: {user_id}\n消息数量: {count}\n")
    await update.message.reply_text("\n".join(lines))


@admin_only
async def get_user_messages(update: Update, context: CallbackContext):
    """获取指定用户的消息历史"""
    args = context.args
    if not args:
        await update.message.reply_text("请提供用户ID。\n用法: /user_messages <用户ID> [YYYY-MM-DD]")
        return

    try:
        user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("无效的用户ID。请提供一个数字ID。")
        return

    date_filter = None
    if len(args) > 1:
        try:
            date_filter = datetime.strptime(args[1], "%Y-%m-%d")
        except ValueError:
            await update.message.reply_text("日期格式无效。请使用 YYYY-MM-DD 格式。")
            return

    if date_filter:
        messages = db.query(
            "SELECT content, created_at FROM messages WHERE user_id = ? AND date(created_at) = date(?) ORDER BY created_at DESC",
            (user_id, date_filter.strftime("%Y-%m-%d")),
        )
    else:
        messages = db.query(
            "SELECT content, created_at FROM messages WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user_id,),
        )

    if not messages:
        await update.message.reply_text(f"未找到用户 {user_id} 的消息记录。")
        return

    lines = [f"用户 {user_id} 的消息历史：\n"]
    for msg_text, created_at in messages:
        dt = datetime.fromisoformat(created_at)
        lines.append(f"{dt.strftime('%Y-%m-%d %H:%M:%S')}: {msg_text}\n")
    await update.message.reply_text("\n".join(lines))


# ── 统一注册 ──────────────────────────────────────────────

def register_all(app: Application) -> None:
    """将所有 handler 注册到 Application"""
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("save", save_messages))
    app.add_handler(CommandHandler("send", send_messages))
    app.add_handler(CommandHandler("all", send_all_messages))
    app.add_handler(CommandHandler("send_all", send_all_messages))
    app.add_handler(CommandHandler("users", get_user_stats))
    app.add_handler(CommandHandler("user_messages", get_user_messages))
    app.add_handler(CommandHandler("user_message", get_user_messages))
    logger.info("所有 handler 注册完成")