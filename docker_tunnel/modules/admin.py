import logging
from functools import wraps
from telegram import Update
from telegram.ext import CallbackContext
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


def admin_only(func):
    """管理员权限检查装饰器"""
    @wraps(func)
    async def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ 此命令仅限管理员使用。")
            return
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"命令 {func.__name__} 执行出错: {e}", exc_info=True)
            try:
                await update.message.reply_text(f"❌ 命令执行出错: {str(e)}")
            except:
                pass
    return wrapped
