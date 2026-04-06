"""工具函数模块"""
import re
import string
import random
import logging
from functools import wraps
from typing import List

from config import CODE_PREFIX, CODE_LENGTH
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def get_code_prefix(bot_username: str) -> str:
    """获取代码前缀（自定义或 bot 用户名，不带@）"""
    return CODE_PREFIX if CODE_PREFIX else bot_username


def escape_markdown(text: str) -> str:
    """转义 Markdown 特殊字符（用于用户输入的内容）"""
    for char in ['_', '*', '`', '[']:
        text = text.replace(char, f'\\{char}')
    return text


def generate_raw_code(length: int = CODE_LENGTH) -> str:
    """生成随机 base62 代码"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


def parse_file_code(text: str, bot_username: str) -> List[str]:
    """从文本中解析出所有文件代码"""
    code_prefix = get_code_prefix(bot_username)
    pattern = re.compile(rf'{re.escape(code_prefix)}_[pvd]:[A-Za-z0-9]{{{CODE_LENGTH}}}')
    return pattern.findall(text)


def parse_collection_code(text: str, bot_username: str) -> List[str]:
    """从文本中解析出集合代码"""
    code_prefix = get_code_prefix(bot_username)
    pattern = re.compile(rf'{re.escape(code_prefix)}_col:[A-Za-z0-9]{{{CODE_LENGTH}}}')
    return pattern.findall(text)


def admin_only(func):
    """管理员权限装饰器"""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        from config import ADMIN_IDS
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ 此命令仅限管理员使用。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped