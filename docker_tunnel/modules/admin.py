from functools import wraps
from telegram import Update
from telegram.ext import CallbackContext
from config import ADMIN_IDS


def admin_only(func):
    """管理员权限检查装饰器"""
    @wraps(func)
    async def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ 此命令仅限管理员使用。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped