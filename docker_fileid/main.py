"""
FileID Bot - Telegram 文件ID互转机器人
支持图片/视频/音频/文档的ID获取与还原，支持集合管理与分页发送
"""
import os
import re
import string
import random
import sqlite3
import logging
import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from functools import wraps
from typing import Optional, List, Dict, Tuple

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio
)
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from cryptography.fernet import Fernet

# ==================== 配置 ====================

# 加载 .env 文件
env_path = Path('.env')
if env_path.exists():
    with env_path.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', '')
CODE_PREFIX = os.environ.get('CODE_PREFIX', '')  # 自定义代码前缀，默认使用 bot 用户名（不带@）
MAX_COLLECTION_FILES = 999
AUTO_SEND_INTERVAL = 5  # 秒
GROUP_SEND_SIZE = 10  # 每组最多10个
CODE_LENGTH = 32  # 随机码长度

# ==================== 日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== 加密工具 ====================
fernet_cipher = None

def init_encryption():
    """初始化加密器"""
    global fernet_cipher
    if ENCRYPTION_KEY:
        try:
            fernet_cipher = Fernet(ENCRYPTION_KEY.encode())
            logger.info("加密器初始化成功")
        except Exception as e:
            logger.error("加密器初始化失败: %s", e)
            fernet_cipher = None
    else:
        logger.warning("未设置 ENCRYPTION_KEY，文件ID将明文存储")


def encrypt_file_id(file_id: str) -> str:
    """加密 file_id"""
    if fernet_cipher:
        try:
            return fernet_cipher.encrypt(file_id.encode()).decode()
        except Exception as e:
            logger.error("加密失败: %s", e)
    return file_id


def decrypt_file_id(encrypted: str) -> str:
    """解密 file_id"""
    if fernet_cipher:
        try:
            return fernet_cipher.decrypt(encrypted.encode()).decode()
        except Exception as e:
            logger.error("解密失败: %s", e)
    return encrypted


# ==================== 数据库 ====================
DB_PATH = './data/fileid.db'


def get_db():
    """获取数据库连接（启用 WAL 模式和超时）"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_db()
    try:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS file_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                bot_username TEXT,
                file_type TEXT NOT NULL,
                telegram_file_id TEXT NOT NULL,
                encrypted_file_id TEXT,
                file_size INTEGER DEFAULT 0,
                file_unique_id TEXT,
                user_id INTEGER,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_file_code ON file_mappings(code);
            CREATE INDEX IF NOT EXISTS idx_file_user ON file_mappings(user_id);

            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                bot_username TEXT,
                name TEXT DEFAULT '',
                user_id INTEGER,
                file_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'open',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_col_code ON collections(code);
            CREATE INDEX IF NOT EXISTS idx_col_user ON collections(user_id);

            CREATE TABLE IF NOT EXISTS collection_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_code TEXT NOT NULL,
                file_code TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (collection_code) REFERENCES collections(code),
                FOREIGN KEY (file_code) REFERENCES file_mappings(code)
            );
            CREATE INDEX IF NOT EXISTS idx_ci_col ON collection_items(collection_code);
        ''')
        conn.commit()
        logger.info("数据库初始化完成")
    finally:
        conn.close()


# ==================== 代码生成 ====================
def generate_code(length: int = CODE_LENGTH) -> str:
    """生成随机 base62 代码"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


def generate_unique_code(length: int = CODE_LENGTH) -> str:
    """生成唯一代码（确保数据库中不存在）"""
    conn = get_db()
    try:
        while True:
            code = generate_code(length)
            row = conn.execute(
                "SELECT id FROM file_mappings WHERE code = ? UNION SELECT id FROM collections WHERE code = ?",
                (code, code)
            ).fetchone()
            if not row:
                return code
    finally:
        conn.close()


# ==================== 权限检查 ====================
def admin_only(func):
    """管理员权限装饰器"""
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ 此命令仅限管理员使用。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


# ==================== 文件类型判断与发送 ====================
FILE_TYPE_MAP = {
    'photo': '🖼 图片',
    'video': '🎬 视频',
    'audio': '🎵 音频',
    'document': '📄 文档',
    'voice': '🎤 语音',
}

FILE_TYPE_PREFIX = {
    'photo': 'p',
    'video': 'v',
    'document': 'd',
    'audio': 'd',
    'voice': 'd',
}


async def send_file_group(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    files: List[Dict],
    caption: str = ""
) -> int:
    """
    组发送文件（图片+视频用相册，文档用文档组，音频用音频组）
    返回成功发送的数量
    """
    if not files:
        return 0

    # 按类型分组
    photo_video = []  # 可以混排
    documents = []
    audios = []

    for f in files:
        ft = f['file_type']
        if ft in ('photo', 'video'):
            photo_video.append(f)
        elif ft == 'audio':
            audios.append(f)
        else:  # document, voice
            documents.append(f)

    sent_count = 0

    # 1. 发送图片+视频（每10个一组）
    for i in range(0, len(photo_video), GROUP_SEND_SIZE):
        batch = photo_video[i:i + GROUP_SEND_SIZE]
        media_list = []
        for idx, f in enumerate(batch):
            file_id = f['telegram_file_id']
            cap = caption if idx == 0 and not any(m['file_type'] == 'video' for m in batch[:idx]) else ""
            try:
                if f['file_type'] == 'photo':
                    media_list.append(InputMediaPhoto(media=file_id, caption=cap[:1024] if cap else ""))
                else:
                    media_list.append(InputMediaVideo(media=file_id, caption=cap[:1024] if cap else ""))
            except Exception as e:
                logger.error("构建媒体列表失败: %s", e)
        if media_list:
            try:
                await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                sent_count += len(media_list)
            except Exception as e:
                logger.error("发送媒体组失败: %s", e)
                # 降级逐个发送
                for f in batch:
                    try:
                        if f['file_type'] == 'photo':
                            await context.bot.send_photo(chat_id=chat_id, photo=f['telegram_file_id'])
                        else:
                            await context.bot.send_video(chat_id=chat_id, video=f['telegram_file_id'])
                        sent_count += 1
                    except Exception as e2:
                        logger.error("降级发送失败: %s", e2)

    # 2. 发送文档（每10个一组）
    for i in range(0, len(documents), GROUP_SEND_SIZE):
        batch = documents[i:i + GROUP_SEND_SIZE]
        if len(batch) == 1:
            # 单个文档直接发送
            try:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=batch[0]['telegram_file_id'],
                    caption=caption[:1024] if caption else ""
                )
                sent_count += 1
            except Exception as e:
                logger.error("发送文档失败: %s", e)
        else:
            media_list = []
            for f in batch:
                try:
                    media_list.append(InputMediaDocument(media=f['telegram_file_id']))
                except Exception as e:
                    logger.error("构建文档列表失败: %s", e)
            if media_list:
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                    sent_count += len(media_list)
                except Exception as e:
                    logger.error("发送文档组失败: %s", e)
                    # 降级逐个发送
                    for f in batch:
                        try:
                            await context.bot.send_document(chat_id=chat_id, document=f['telegram_file_id'])
                            sent_count += 1
                        except Exception as e2:
                            logger.error("降级发送文档失败: %s", e2)

    # 3. 发送音频（每10个一组）
    for i in range(0, len(audios), GROUP_SEND_SIZE):
        batch = audios[i:i + GROUP_SEND_SIZE]
        if len(batch) == 1:
            try:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=batch[0]['telegram_file_id'],
                    caption=caption[:1024] if caption else ""
                )
                sent_count += 1
            except Exception as e:
                logger.error("发送音频失败: %s", e)
        else:
            media_list = []
            for f in batch:
                try:
                    media_list.append(InputMediaAudio(media=f['telegram_file_id']))
                except Exception as e:
                    logger.error("构建音频列表失败: %s", e)
            if media_list:
                try:
                    await context.bot.send_media_group(chat_id=chat_id, media=media_list)
                    sent_count += len(media_list)
                except Exception as e:
                    logger.error("发送音频组失败: %s", e)
                    for f in batch:
                        try:
                            await context.bot.send_audio(chat_id=chat_id, audio=f['telegram_file_id'])
                            sent_count += 1
                        except Exception as e2:
                            logger.error("降级发送音频失败: %s", e2)

    return sent_count


# ==================== 文件保存 ====================
def get_code_prefix(bot_username: str) -> str:
    """获取代码前缀（自定义或 bot 用户名，不带@）"""
    return CODE_PREFIX if CODE_PREFIX else bot_username


def escape_markdown(text: str) -> str:
    """转义 Markdown 特殊字符（用于用户输入的内容）"""
    # Markdown 模式需要转义的字符: _ * ` [ 
    for char in ['_', '*', '`', '[']:
        text = text.replace(char, f'\\{char}')
    return text


def save_file_to_db(user_id: int, file_type: str, file_id: str,
                    file_size: int, file_unique_id: str, bot_username: str) -> Optional[str]:
    """保存文件到数据库，返回代码"""
    conn = get_db()
    try:
        code = generate_unique_code()
        prefix = FILE_TYPE_PREFIX.get(file_type, 'd')
        code_prefix = get_code_prefix(bot_username)
        full_code = f"{code_prefix}_{prefix}:{code}"

        encrypted_fid = encrypt_file_id(file_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """INSERT INTO file_mappings 
               (code, bot_username, file_type, telegram_file_id, encrypted_file_id, file_size, file_unique_id, user_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (full_code, bot_username, file_type, file_id, encrypted_fid, file_size, file_unique_id, user_id, now)
        )
        conn.commit()
        return full_code
    except sqlite3.IntegrityError:
        logger.error("代码重复（极少发生）: %s", full_code)
        return None
    except Exception as e:
        logger.error("保存文件失败: %s", e)
        return None
    finally:
        conn.close()


def get_file_from_db(code: str) -> Optional[Dict]:
    """根据代码获取文件信息"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM file_mappings WHERE code = ?", (code,)
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def parse_file_code(text: str, bot_username: str) -> List[str]:
    """从文本中解析出所有文件代码"""
    code_prefix = get_code_prefix(bot_username)
    # 匹配 Prefix_p:xxx Prefix_v:xxx Prefix_d:xxx 格式
    pattern = re.compile(rf'{re.escape(code_prefix)}_[pvd]:[A-Za-z0-9]{{{CODE_LENGTH}}}')
    return pattern.findall(text)


def parse_collection_code(text: str, bot_username: str) -> List[str]:
    """从文本中解析出集合代码"""
    code_prefix = get_code_prefix(bot_username)
    pattern = re.compile(rf'{re.escape(code_prefix)}_col:[A-Za-z0-9]{{{CODE_LENGTH}}}')
    return pattern.findall(text)


# ==================== 集合操作 ====================
def get_collection_info(code: str) -> Optional[Dict]:
    """获取集合信息"""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM collections WHERE code = ?", (code,)).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def get_collection_files(code: str) -> List[Dict]:
    """获取集合中的所有文件"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT fm.* FROM file_mappings fm
               JOIN collection_items ci ON fm.code = ci.file_code
               WHERE ci.collection_code = ?
               ORDER BY ci.sort_order""",
            (code,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ==================== 命令处理 ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start 和 /help 命令"""
    bot_username = context.bot.username
    help_text = f"""🤖 *FileID Bot* — 文件ID互转工具

📌 *核心功能：*
• 发送图片/视频/音频/文档 → 获取唯一代码
• 发送代码 → 获取对应文件
• 支持 `send_media_group` 组发送

📦 *集合功能：*
• `/create 名称` — 创建集合（连续发文件）
• `/done` — 完成集合
• `/cancel` — 取消当前操作
• `/mycol` — 查看我的集合
• `/delcol 代码` — 删除集合

🔧 *其他命令：*
• 回复消息 + `/getid` — 获取文件ID
• `/stats` — 管理员统计

📝 *代码格式：*
• `{bot_username}_p:xxx` — 图片
• `{bot_username}_v:xxx` — 视频
• `{bot_username}_d:xxx` — 文档/音频
• `{bot_username}_col:xxx` — 集合

将代码直接发送给 bot 即可获取文件！"""

    await update.message.reply_text(
        help_text, parse_mode="Markdown",
        disable_web_page_preview=True
    )


async def create_collection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/create 创建集合"""
    user_id = update.effective_user.id
    bot_username = context.bot.username

    # 检查是否已有进行中的集合
    if context.user_data.get('creating_collection'):
        await update.message.reply_text(
            "⚠️ 你已有正在创建的集合，请先 `/done` 完成或 `/cancel` 取消。"
        )
        return

    # 集合名称
    name = ' '.join(context.args) if context.args else f"集合_{datetime.now().strftime('%m%d%H%M')}"

    conn = get_db()
    try:
        code = generate_unique_code()
        code_prefix = get_code_prefix(bot_username)
        full_code = f"{code_prefix}_col:{code}"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """INSERT INTO collections (code, bot_username, name, user_id, file_count, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, 'open', ?, ?)""",
            (full_code, bot_username, name, user_id, now, now)
        )
        conn.commit()

        context.user_data['creating_collection'] = full_code
        context.user_data['collection_count'] = 0

        safe_name = escape_markdown(name)
        await update.message.reply_text(
            f"✅ 集合「{safe_name}」创建成功！\n\n"
            f"📦 代码: `{full_code}`\n\n"
            f"👉 请连续发送要添加的文件（图片/视频/音频/文档），"
            f"最多 {MAX_COLLECTION_FILES} 个。\n"
            f"✅ 发送 `/done` 完成添加\n"
            f"❌ 发送 `/cancel` 取消集合",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error("创建集合失败: %s", e)
        await update.message.reply_text(f"❌ 创建集合失败: {e}")
    finally:
        conn.close()


async def done_collection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done 完成集合"""
    user_id = update.effective_user.id
    col_code = context.user_data.get('creating_collection')

    if not col_code:
        await update.message.reply_text("⚠️ 你没有正在创建的集合。发送 `/create 名称` 开始。")
        return

    count = context.user_data.get('collection_count', 0)

    conn = get_db()
    try:
        if count == 0:
            # 空集合，删除
            conn.execute("DELETE FROM collections WHERE code = ?", (col_code,))
            conn.commit()
            await update.message.reply_text("⚠️ 集合为空，已自动取消。")
        else:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE collections SET status = 'completed', file_count = ?, updated_at = ? WHERE code = ?",
                (count, now, col_code)
            )
            conn.commit()

            col_info = conn.execute("SELECT name FROM collections WHERE code = ?", (col_code,)).fetchone()
            col_name = col_info['name'] if col_info else "未命名"
            safe_col_name = escape_markdown(col_name)

            await update.message.reply_text(
                f"🎉 集合「{safe_col_name}」创建完成！\n\n"
                f"📦 代码: `{col_code}`\n"
                f"📊 共 {count} 个文件\n\n"
                f"将代码发送给 bot 即可获取所有文件。",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error("完成集合失败: %s", e)
        await update.message.reply_text(f"❌ 操作失败: {e}")
    finally:
        conn.close()
        context.user_data.pop('creating_collection', None)
        context.user_data.pop('collection_count', None)


async def cancel_collection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cancel 取消当前操作"""
    col_code = context.user_data.get('creating_collection')

    if col_code:
        conn = get_db()
        try:
            # 删除集合项和集合
            conn.execute("DELETE FROM collection_items WHERE collection_code = ?", (col_code,))
            conn.execute("DELETE FROM collections WHERE code = ?", (col_code,))
            conn.commit()
        except Exception as e:
            logger.error("取消集合失败: %s", e)
        finally:
            conn.close()

        context.user_data.pop('creating_collection', None)
        context.user_data.pop('collection_count', None)
        await update.message.reply_text("❌ 已取消当前集合。")
    else:
        # 停止自动发送
        context.user_data['stop_auto_send'] = True
        await update.message.reply_text("❌ 已停止当前操作。")


async def my_collections(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mycol 查看我的集合"""
    user_id = update.effective_user.id
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT code, name, file_count, status, created_at FROM collections WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
            (user_id,)
        ).fetchall()

        if not rows:
            await update.message.reply_text("📦 你还没有创建任何集合。")
            return

        text = "📦 *我的集合列表：*\n\n"
        for r in rows:
            status_icon = "✅" if r['status'] == 'completed' else "🔧"
            safe_r_name = escape_markdown(r['name'])
            text += (
                f"{status_icon} *{safe_r_name}*\n"
                f"  代码: `{r['code']}`\n"
                f"  文件数: {r['file_count']} | 创建于: {r['created_at']}\n\n"
            )

        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error("查询集合列表失败: %s", e)
        await update.message.reply_text(f"❌ 查询失败: {e}")
    finally:
        conn.close()


async def delete_collection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delcol 删除集合"""
    user_id = update.effective_user.id
    if not context.args:
        bot_username = context.bot.username
        code_prefix = get_code_prefix(bot_username)
        await update.message.reply_text(f"请提供集合代码。\n用法: `/delcol {code_prefix}_col:xxx`", parse_mode="Markdown")
        return

    col_code = context.args[0]
    conn = get_db()
    try:
        # 检查权限
        row = conn.execute("SELECT user_id FROM collections WHERE code = ?", (col_code,)).fetchone()
        if not row:
            await update.message.reply_text("❌ 集合不存在。")
            return
        if row['user_id'] != user_id and user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ 你没有权限删除此集合。")
            return

        conn.execute("DELETE FROM collection_items WHERE collection_code = ?", (col_code,))
        conn.execute("DELETE FROM collections WHERE code = ?", (col_code,))
        conn.commit()
        await update.message.reply_text("✅ 集合已删除。")
    except Exception as e:
        logger.error("删除集合失败: %s", e)
        await update.message.reply_text(f"❌ 删除失败: {e}")
    finally:
        conn.close()


async def get_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/getid 回复消息获取文件ID"""
    if not update.message.reply_to_message:
        await update.message.reply_text("请回复一条包含媒体的消息来获取其ID。\n用法: 回复消息 + `/getid`", parse_mode="Markdown")
        return

    replied = update.message.reply_to_message
    bot_username = context.bot.username
    user_id = update.effective_user.id
    result = None
    file_type = None

    if replied.photo:
        photo = replied.photo[-1]
        result = save_file_to_db(user_id, 'photo', photo.file_id, photo.file_size or 0, photo.file_unique_id or '', bot_username)
        file_type = '图片'
    elif replied.video:
        result = save_file_to_db(user_id, 'video', replied.video.file_id, replied.video.file_size or 0, replied.video.file_unique_id or '', bot_username)
        file_type = '视频'
    elif replied.audio:
        result = save_file_to_db(user_id, 'audio', replied.audio.file_id, replied.audio.file_size or 0, replied.audio.file_unique_id or '', bot_username)
        file_type = '音频'
    elif replied.document:
        result = save_file_to_db(user_id, 'document', replied.document.file_id, replied.document.file_size or 0, replied.document.file_unique_id or '', bot_username)
        file_type = '文档'
    elif replied.voice:
        result = save_file_to_db(user_id, 'voice', replied.voice.file_id, replied.voice.file_size or 0, replied.voice.file_unique_id or '', bot_username)
        file_type = '语音'
    else:
        await update.message.reply_text("❌ 回复的消息不包含可识别的媒体文件。")
        return

    if result:
        code_prefix = get_code_prefix(bot_username)
        await update.message.reply_text(
            f"✅ {file_type}ID已保存！\n\n代码: `{result}`\n\n将此代码发送给 `@{bot_username}` 即可获取文件。",
            parse_mode="Markdown",
            reply_to_message_id=update.message.reply_to_message.message_id
        )
    else:
        await update.message.reply_text("❌ 保存失败，请重试。")


@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats 管理员统计"""
    conn = get_db()
    try:
        file_count = conn.execute("SELECT COUNT(*) as c FROM file_mappings").fetchone()['c']
        col_count = conn.execute("SELECT COUNT(*) as c FROM collections").fetchone()['c']
        user_count = conn.execute("SELECT COUNT(DISTINCT user_id) as c FROM file_mappings").fetchone()['c']
        today = datetime.now().strftime("%Y-%m-%d")
        today_files = conn.execute(
            "SELECT COUNT(*) as c FROM file_mappings WHERE created_at LIKE ?", (f"{today}%",)
        ).fetchone()['c']

        # 按类型统计
        type_stats = conn.execute(
            "SELECT file_type, COUNT(*) as c FROM file_mappings GROUP BY file_type"
        ).fetchall()
        type_text = "\n".join(f"  {FILE_TYPE_MAP.get(r['file_type'], r['file_type'])}: {r['c']}" for r in type_stats)

        text = (
            f"📊 *Bot 统计信息*\n\n"
            f"📁 总文件数: {file_count}\n"
            f"📦 总集合数: {col_count}\n"
            f"👥 总用户数: {user_count}\n"
            f"📅 今日新增: {today_files}\n\n"
            f"📋 按类型统计:\n{type_text}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error("统计查询失败: %s", e)
        await update.message.reply_text(f"❌ 查询失败: {e}")
    finally:
        conn.close()


@admin_only
async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/export 管理员导出数据"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT code, file_type, file_size, user_id, created_at FROM file_mappings ORDER BY created_at DESC"
        ).fetchall()

        if not rows:
            await update.message.reply_text("没有数据可导出。")
            return

        import io
        output = io.StringIO()
        output.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        output.write(f"总记录数: {len(rows)}\n\n")
        output.write("code\ttype\tsize\tuser_id\tcreated_at\n")
        for r in rows:
            output.write(f"{r['code']}\t{r['file_type']}\t{r['file_size']}\t{r['user_id']}\t{r['created_at']}\n")

        bytes_io = io.BytesIO(output.getvalue().encode('utf-8'))
        await context.bot.send_document(
            chat_id=update.message.chat_id,
            document=bytes_io,
            filename=f"fileid_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            caption=f"导出完成，共 {len(rows)} 条记录。"
        )
    except Exception as e:
        logger.error("导出失败: %s", e)
        await update.message.reply_text(f"❌ 导出失败: {e}")
    finally:
        conn.close()


# ==================== 附件处理 ====================

async def handle_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理用户发送的图片/视频/音频/文档"""
    message = update.message
    user_id = update.effective_user.id
    bot_username = context.bot.username
    creating_col = context.user_data.get('creating_collection')

    file_id = None
    file_type = None
    file_size = 0
    file_unique_id = ''

    try:
        if message.photo:
            photo = message.photo[-1]
            file_id = photo.file_id
            file_type = 'photo'
            file_size = photo.file_size or 0
            file_unique_id = photo.file_unique_id or ''
        elif message.video:
            file_id = message.video.file_id
            file_type = 'video'
            file_size = message.video.file_size or 0
            file_unique_id = message.video.file_unique_id or ''
        elif message.audio:
            file_id = message.audio.file_id
            file_type = 'audio'
            file_size = message.audio.file_size or 0
            file_unique_id = message.audio.file_unique_id or ''
        elif message.document:
            file_id = message.document.file_id
            file_type = 'document'
            file_size = message.document.file_size or 0
            file_unique_id = message.document.file_unique_id or ''
        elif message.voice:
            file_id = message.voice.file_id
            file_type = 'voice'
            file_size = message.voice.file_size or 0
            file_unique_id = message.voice.file_unique_id or ''
        else:
            await message.reply_text("❌ 不支持的文件类型。支持: 图片、视频、音频、文档。")
            return

        # 保存到数据库
        code = save_file_to_db(user_id, file_type, file_id, file_size, file_unique_id, bot_username)

        if not code:
            await message.reply_text("❌ 保存失败，请重试。")
            return

        type_name = FILE_TYPE_MAP.get(file_type, file_type)
        reply_text = f"✅ {type_name}已保存！\n\n代码: `{code}`"
        reply_kwargs = {
            'text': reply_text,
            'parse_mode': 'Markdown',
            'reply_to_message_id': message.message_id
        }

        # 如果正在创建集合，追加文件
        if creating_col:
            conn = get_db()
            try:
                current_count = context.user_data.get('collection_count', 0)
                if current_count >= MAX_COLLECTION_FILES:
                    await message.reply_text(f"⚠️ 集合已满 {MAX_COLLECTION_FILES} 个文件，请发送 `/done` 完成。")
                    return

                sort_order = current_count + 1
                conn.execute(
                    "INSERT INTO collection_items (collection_code, file_code, sort_order) VALUES (?, ?, ?)",
                    (creating_col, code, sort_order)
                )
                conn.execute(
                    "UPDATE collections SET file_count = ?, updated_at = ? WHERE code = ?",
                    (sort_order, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), creating_col)
                )
                conn.commit()
                context.user_data['collection_count'] = sort_order

                reply_text += f"\n\n📦 已添加到集合 ({sort_order}/{MAX_COLLECTION_FILES})"
                reply_kwargs['text'] = reply_text
            except Exception as e:
                logger.error("添加到集合失败: %s", e)
                reply_kwargs['text'] += f"\n\n⚠️ 添加到集合失败: {e}"
            finally:
                conn.close()

        await message.reply_text(**reply_kwargs)

    except Exception as e:
        logger.error("处理附件失败: %s", e)
        await message.reply_text(f"❌ 处理文件时出错: {e}")


# ==================== 文本处理（代码解析与发送） ====================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理文本消息，解析代码并发送文件"""
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()
    bot_username = context.bot.username

    # 解析文件代码
    file_codes = parse_file_code(text, bot_username)
    # 解析集合代码
    collection_codes = parse_collection_code(text, bot_username)

    # 也支持旧格式兼容: $p $v $d 开头的纯 file_id
    legacy_file_ids = []
    if not file_codes and not collection_codes:
        legacy_pattern = re.compile(r'\$([pvd])(\S+)')
        for m in legacy_pattern.finditer(text):
            prefix = m.group(1)
            fid = m.group(2)
            legacy_file_ids.append((prefix, fid))

    if not file_codes and not collection_codes and not legacy_file_ids:
        # 没有匹配到任何代码
        await message.reply_text(
            f"❓ 未识别的输入。\n\n"
            f"• 发送文件获取代码\n"
            f"• 发送代码获取文件\n"
            f"• `/help` 查看帮助",
        )
        return

    chat_id = message.chat_id
    total_sent = 0

    # 处理单个文件代码
    if file_codes:
        files = []
        not_found = []
        for code in file_codes:
            f = get_file_from_db(code)
            if f:
                files.append(f)
            else:
                not_found.append(code)

        if files:
            # 直接发送（不分组，因为是用户主动请求的）
            try:
                sent = await send_file_group(context, chat_id, files)
                total_sent += sent
            except Exception as e:
                logger.error("发送文件失败: %s", e)
                await message.reply_text(f"❌ 发送文件时出错: {e}")

        if not_found:
            not_found_text = "\n".join(f"• `{c}`" for c in not_found)
            await message.reply_text(
                f"⚠️ 以下代码未找到对应文件:\n{not_found_text}",
                parse_mode="Markdown"
            )

    # 处理集合代码
    for col_code in collection_codes:
        col_info = get_collection_info(col_code)
        if not col_info:
            await message.reply_text(f"❌ 集合不存在: `{col_code}`", parse_mode="Markdown")
            continue

        safe_col_name_1 = escape_markdown(col_info['name'])
        if col_info['status'] != 'completed':
            await message.reply_text(f"⚠️ 集合「{safe_col_name_1}」尚未完成。")
            continue

        files = get_collection_files(col_code)
        if not files:
            await message.reply_text(f"⚠️ 集合「{safe_col_name_1}」为空。")
            continue

        # 如果文件数量较多，使用分页按钮
        total_files = len(files)
        # 按类型统计
        type_counts = {}
        for f in files:
            ft = f['file_type']
            type_counts[ft] = type_counts.get(ft, 0) + 1
        type_stats_text = " ".join(
            f"{FILE_TYPE_MAP.get(k, k)}x{v}" for k, v in type_counts.items()
        )

        # 始终显示集合信息 + 按钮（让用户选择发送方式）
        col_text = (
            f"📦 *集合「{safe_col_name_1}」*\n\n"
            f"📊 共 {total_files} 个文件\n"
            f"📋 {type_stats_text}\n\n"
            f"请选择操作："
        )

        keyboard = [
            [
                InlineKeyboardButton("⬇️ 全部发送", callback_data=f"col_send:{col_code}"),
            ],
            [
                InlineKeyboardButton("▶️ 自动发送", callback_data=f"col_auto:{col_code}"),
            ],
        ]
        if total_files > GROUP_SEND_SIZE:
            keyboard.append([
                InlineKeyboardButton("📖 分页浏览", callback_data=f"col_page:{col_code}:1"),
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(col_text, parse_mode="Markdown", reply_markup=reply_markup)

    # 处理旧格式兼容
    if legacy_file_ids:
        for prefix, fid in legacy_file_ids:
            try:
                if prefix == 'p':
                    await context.bot.send_photo(chat_id=chat_id, photo=fid)
                elif prefix == 'v':
                    await context.bot.send_video(chat_id=chat_id, video=fid)
                elif prefix == 'd':
                    await context.bot.send_document(chat_id=chat_id, document=fid)
                total_sent += 1
            except Exception as e:
                logger.error("旧格式发送失败: %s", e)
                await message.reply_text(f"❌ 发送失败 `{prefix}{fid[:20]}...`: {e}", parse_mode="Markdown")


# ==================== 回调按钮处理 ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理内联按钮回调"""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    try:
        if data.startswith("col_send:"):
            # 全部发送
            col_code = data.split(":", 1)[1]
            await _send_collection_all(context, chat_id, col_code, query)

        elif data.startswith("col_auto:"):
            # 自动发送
            col_code = data.split(":", 1)[1]
            await _auto_send_collection(context, chat_id, col_code, user_id, query)

        elif data.startswith("col_page:"):
            # 分页浏览
            parts = data.split(":")
            col_code = parts[1]
            page = int(parts[2]) if len(parts) > 2 else 1
            await _send_collection_page(context, chat_id, col_code, page, query)

        elif data.startswith("page_send:"):
            # 发送本页文件
            parts = data.split(":")
            col_code = parts[1]
            page = int(parts[2]) if len(parts) > 2 else 1
            await _send_page_files(context, chat_id, col_code, page, query)

        elif data == "stop_auto":
            context.user_data['stop_auto_send'] = True
            await query.edit_message_reply_markup(reply_markup=None)
            await context.bot.send_message(chat_id=chat_id, text="⏹ 已停止自动发送。")

        else:
            await query.edit_message_text("❓ 未知操作。")

    except Exception as e:
        logger.error("按钮回调处理失败: %s", e)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 操作失败: {e}")
        except Exception:
            pass


async def _send_collection_all(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    col_code: str,
    query=None
) -> None:
    """发送集合全部文件（分批组发送）"""
    files = get_collection_files(col_code)
    if not files:
        if query:
            await query.edit_message_text("⚠️ 集合为空。")
        return

    total = len(files)
    sent_count = 0
    error_count = 0

    # 更新消息状态
    if query:
        await query.edit_message_text(f"📤 正在发送... (0/{total})")

    # 按类型分组发送
    photo_video_files = [f for f in files if f['file_type'] in ('photo', 'video')]
    doc_files = [f for f in files if f['file_type'] == 'document']
    audio_files = [f for f in files if f['file_type'] in ('audio', 'voice')]

    batch_num = 0

    # 图片+视频
    for i in range(0, len(photo_video_files), GROUP_SEND_SIZE):
        batch = photo_video_files[i:i + GROUP_SEND_SIZE]
        try:
            sent = await send_file_group(context, chat_id, batch)
            sent_count += sent
        except Exception as e:
            logger.error("批量发送失败: %s", e)
            error_count += len(batch)
        batch_num += 1
        if batch_num % 2 == 0 and i + GROUP_SEND_SIZE < len(photo_video_files):
            await asyncio.sleep(2)  # 防止限流

    # 文档
    for i in range(0, len(doc_files), GROUP_SEND_SIZE):
        batch = doc_files[i:i + GROUP_SEND_SIZE]
        try:
            sent = await send_file_group(context, chat_id, batch)
            sent_count += sent
        except Exception as e:
            logger.error("批量发送文档失败: %s", e)
            error_count += len(batch)
        batch_num += 1
        await asyncio.sleep(2)

    # 音频
    for i in range(0, len(audio_files), GROUP_SEND_SIZE):
        batch = audio_files[i:i + GROUP_SEND_SIZE]
        try:
            sent = await send_file_group(context, chat_id, batch)
            sent_count += sent
        except Exception as e:
            logger.error("批量发送音频失败: %s", e)
            error_count += len(batch)
        batch_num += 1
        await asyncio.sleep(2)

    result_text = f"✅ 发送完成！成功 {sent_count}/{total}"
    if error_count > 0:
        result_text += f"\n⚠️ {error_count} 个文件发送失败"

    if query:
        try:
            await query.edit_message_text(result_text)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=result_text)
    else:
        await context.bot.send_message(chat_id=chat_id, text=result_text)


async def _auto_send_collection(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    col_code: str,
    user_id: int,
    query=None
) -> None:
    """自动发送集合文件（每5秒一组）"""
    files = get_collection_files(col_code)
    if not files:
        if query:
            await query.edit_message_text("⚠️ 集合为空。")
        return

    total = len(files)
    context.user_data['stop_auto_send'] = False

    # 更新消息为控制面板
    keyboard = [[InlineKeyboardButton("⏹ 停止发送", callback_data="stop_auto")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(
            f"▶️ 自动发送中... (0/{total})",
            reply_markup=reply_markup
        )

    # 按类型分组
    photo_video_files = [f for f in files if f['file_type'] in ('photo', 'video')]
    doc_files = [f for f in files if f['file_type'] == 'document']
    audio_files = [f for f in files if f['file_type'] in ('audio', 'voice')]

    sent_count = 0
    all_groups = []

    # 将文件分成发送组
    for i in range(0, len(photo_video_files), GROUP_SEND_SIZE):
        all_groups.append(photo_video_files[i:i + GROUP_SEND_SIZE])
    for i in range(0, len(doc_files), GROUP_SEND_SIZE):
        all_groups.append(doc_files[i:i + GROUP_SEND_SIZE])
    for i in range(0, len(audio_files), GROUP_SEND_SIZE):
        all_groups.append(audio_files[i:i + GROUP_SEND_SIZE])

    for idx, group in enumerate(all_groups):
        # 检查是否停止
        if context.user_data.get('stop_auto_send'):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏹ 已停止。成功发送 {sent_count}/{total} 个文件。"
            )
            return

        try:
            sent = await send_file_group(context, chat_id, group)
            sent_count += sent
        except Exception as e:
            logger.error("自动发送组失败: %s", e)

        # 更新进度
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id if query else None,
                text=f"▶️ 自动发送中... ({sent_count}/{total})",
                reply_markup=reply_markup
            )
        except Exception:
            pass

        # 最后一组不等
        if idx < len(all_groups) - 1:
            await asyncio.sleep(AUTO_SEND_INTERVAL)

    # 完成
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=query.message.message_id if query else None,
            text=f"✅ 自动发送完成！成功 {sent_count}/{total}",
            reply_markup=None
        )
    except Exception:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ 自动发送完成！成功 {sent_count}/{total}"
        )


async def _send_collection_page(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    col_code: str,
    page: int,
    query=None
) -> None:
    """分页浏览集合文件"""
    files = get_collection_files(col_code)
    col_info = get_collection_info(col_code)

    if not files or not col_info:
        if query:
            await query.edit_message_text("⚠️ 集合为空或不存在。")
        return

    total = len(files)
    per_page = 5  # 每页5个文件
    total_pages = (total + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = min(start + per_page, total)
    page_files = files[start:end]

    # 构建信息文本
    safe_col_name_2 = escape_markdown(col_info['name'])
    text = f"📦 *{safe_col_name_2}* (第{page}/{total_pages}页，共{total}个文件)\n\n"

    for i, f in enumerate(page_files, start + 1):
        type_name = FILE_TYPE_MAP.get(f['file_type'], f['file_type'])
        size_mb = f['file_size'] / (1024 * 1024) if f['file_size'] else 0
        size_text = f"{size_mb:.1f}MB" if size_mb >= 1 else f"{f['file_size'] / 1024:.0f}KB" if f['file_size'] else "未知"
        text += f"{i}. {type_name} ({size_text})\n"

    # 按钮
    buttons = []
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"col_page:{col_code}:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"col_page:{col_code}:{page + 1}"))
    buttons.append(nav_buttons)

    # 本页发送按钮
    page_codes = [f['code'] for f in page_files]
    buttons.append([
        InlineKeyboardButton("⬇️ 发送本页文件", callback_data=f"page_send:{col_code}:{page}"),
    ])
    buttons.append([
        InlineKeyboardButton("⬇️ 全部发送", callback_data=f"col_send:{col_code}"),
        InlineKeyboardButton("▶️ 自动发送", callback_data=f"col_auto:{col_code}"),
    ])

    reply_markup = InlineKeyboardMarkup(buttons)

    if query:
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=reply_markup)


async def _send_page_files(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    col_code: str,
    page: int,
    query=None
) -> None:
    """发送指定页的文件"""
    files = get_collection_files(col_code)
    if not files:
        if query:
            await query.edit_message_text("⚠️ 集合为空。")
        return

    total = len(files)
    per_page = 5
    start = (page - 1) * per_page
    end = min(start + per_page, total)
    page_files = files[start:end]

    if not page_files:
        if query:
            await query.edit_message_text("⚠️ 该页没有文件。")
        return

    sent = await send_file_group(context, chat_id, page_files)
    result_text = f"✅ 已发送第{page}页文件 ({sent}/{len(page_files)})"

    if query:
        try:
            await query.edit_message_text(result_text)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=result_text)
    else:
        await context.bot.send_message(chat_id=chat_id, text=result_text)


# ==================== 转发消息处理 ====================

async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理转发的消息（提取文件ID）"""
    message = update.message
    user_id = update.effective_user.id
    bot_username = context.bot.username

    # 转发的消息如果有媒体，和附件处理一样
    if message.document or message.photo or message.video or message.audio or message.voice:
        await handle_attachment(update, context)
    elif message.text:
        # 纯文本转发，检查是否包含代码
        await handle_text(update, context)
    else:
        await message.reply_text(
            "请转发包含媒体（图片/视频/音频/文档）的消息，我会返回其代码。"
        )


# ==================== 群组消息处理 ====================

async def handle_group_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    处理媒体组（用户一次性发送多个媒体）
    Telegram 会为每个媒体发送单独的消息，但带有 media_group_id
    """
    message = update.message
    if not message:
        return

    media_group_id = message.media_group_id

    if media_group_id:
        # 收集同组媒体
        if 'pending_media_groups' not in context.bot_data:
            context.bot_data['pending_media_groups'] = {}

        if media_group_id not in context.bot_data['pending_media_groups']:
            context.bot_data['pending_media_groups'][media_group_id] = {
                'messages': [],
                'timer': None
            }

        group_data = context.bot_data['pending_media_groups'][media_group_id]
        group_data['messages'].append(message)

        # 重置计时器（等所有同组消息到达）
        if group_data['timer']:
            group_data['timer'].cancel()

        async def process_media_group():
            await asyncio.sleep(2)  # 等待2秒收集所有同组消息

            messages = group_data['messages']
            user_id = messages[0].effective_user.id if messages[0].forward_date is None else messages[0].effective_user.id
            bot_username = context.bot.username

            codes = []
            errors = []

            for msg in messages:
                try:
                    if msg.photo:
                        photo = msg.photo[-1]
                        code = save_file_to_db(user_id, 'photo', photo.file_id, photo.file_size or 0, photo.file_unique_id or '', bot_username)
                    elif msg.video:
                        code = save_file_to_db(user_id, 'video', msg.video.file_id, msg.video.file_size or 0, msg.video.file_unique_id or '', bot_username)
                    elif msg.document:
                        code = save_file_to_db(user_id, 'document', msg.document.file_id, msg.document.file_size or 0, msg.document.file_unique_id or '', bot_username)
                    elif msg.audio:
                        code = save_file_to_db(user_id, 'audio', msg.audio.file_id, msg.audio.file_size or 0, msg.audio.file_unique_id or '', bot_username)
                    else:
                        code = None

                    if code:
                        codes.append(code)
                    else:
                        errors.append("未知类型")
                except Exception as e:
                    errors.append(str(e))

            # 回复结果
            if codes:
                creating_col = context.user_data.get('creating_collection')
                if creating_col:
                    # 添加到集合
                    conn = get_db()
                    try:
                        current_count = context.user_data.get('collection_count', 0)
                        for i, code in enumerate(codes):
                            if current_count + i + 1 > MAX_COLLECTION_FILES:
                                break
                            conn.execute(
                                "INSERT INTO collection_items (collection_code, file_code, sort_order) VALUES (?, ?, ?)",
                                (creating_col, code, current_count + i + 1)
                            )
                        new_count = min(current_count + len(codes), MAX_COLLECTION_FILES)
                        conn.execute(
                            "UPDATE collections SET file_count = ?, updated_at = ? WHERE code = ?",
                            (new_count, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), creating_col)
                        )
                        conn.commit()
                        context.user_data['collection_count'] = new_count
                    except Exception as e:
                        logger.error("批量添加到集合失败: %s", e)
                    finally:
                        conn.close()

                    reply = f"✅ 媒体组已保存并添加到集合！\n\n共 {len(codes)} 个文件 ({new_count}/{MAX_COLLECTION_FILES})\n\n"
                    reply += "\n".join(f"`{c}`" for c in codes)
                else:
                    reply = f"✅ 媒体组已保存！共 {len(codes)} 个文件：\n\n"
                    reply += "\n".join(f"`{c}`" for c in codes)

                try:
                    await messages[0].reply_text(reply, parse_mode="Markdown")
                except Exception as e:
                    logger.error("回复媒体组失败: %s", e)

            if errors:
                logger.error("媒体组处理错误: %s", errors)

            # 清理
            if media_group_id in context.bot_data.get('pending_media_groups', {}):
                del context.bot_data['pending_media_groups'][media_group_id]

        group_data['timer'] = asyncio.create_task(process_media_group())
    else:
        # 非媒体组，直接当普通附件处理
        await handle_attachment(update, context)


async def handle_forwarded_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理转发的媒体消息（包括单个和批量转发）"""
    message = update.message
    if not message:
        return

    # 转发的媒体消息直接用附件处理
    if message.document or message.photo or message.video or message.audio or message.voice:
        # 如果有 media_group_id，走媒体组收集逻辑
        if message.media_group_id:
            # 复用 handle_group_media 的收集逻辑
            await handle_group_media(update, context)
        else:
            await handle_attachment(update, context)
    elif message.text:
        await handle_text(update, context)
    else:
        await message.reply_text(
            "请转发包含媒体（图片/视频/音频/文档）的消息，我会返回其代码。"
        )


# ==================== 错误处理 ====================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """全局错误处理"""
    logger.error("异常发生:", exc_info=context.error)

    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ 处理请求时发生内部错误，请稍后重试。"
            )
        except Exception:
            pass


# ==================== Bot 初始化后 ====================

async def post_init(application):
    """Bot 初始化后注册命令"""
    commands = [
        ("start", "开始使用 / 查看帮助"),
        ("help", "查看帮助"),
        ("create", "创建集合 create 名称"),
        ("done", "完成集合"),
        ("cancel", "取消当前操作"),
        ("getid", "回复消息获取文件ID"),
        ("mycol", "查看我的集合"),
        ("delcol", "删除集合 delcol 代码"),
        ("stats", "管理员统计"),
        ("export", "管理员导出"),
    ]
    await application.bot.set_my_commands(commands)
    bot_username = application.bot.username
    logger.info("Bot @%s 已初始化，注册了 %d 个命令", bot_username, len(commands))


# ==================== 主入口 ====================

def main():
    """启动 Bot"""
    if not BOT_TOKEN:
        print("❌ 错误: 未设置 BOT_TOKEN 环境变量")
        return

    # 初始化加密
    init_encryption()

    # 初始化数据库
    init_db()

    logger.info("FileID Bot 启动中...")

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
    application.add_handler(CommandHandler("create", create_collection))
    application.add_handler(CommandHandler("done", done_collection))
    application.add_handler(CommandHandler("cancel", cancel_collection))
    application.add_handler(CommandHandler("getid", get_id_command))
    application.add_handler(CommandHandler("mycol", my_collections))
    application.add_handler(CommandHandler("delcol", delete_collection))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("export", export_command))

    # 转发的媒体消息（优先级最高，在普通媒体处理器之前）
    application.add_handler(MessageHandler(
        filters.FORWARDED & (filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE),
        handle_forwarded_media
    ))

    # 转发的非媒体消息
    application.add_handler(MessageHandler(
        filters.FORWARDED & filters.TEXT & ~filters.COMMAND,
        handle_forward
    ))

    # 媒体组处理（捕获 media_group_id，仅处理非转发的媒体）
    application.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE,
        handle_group_media
    ))

    # 文本消息（代码解析）
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text
    ))

    # 回调按钮
    application.add_handler(CallbackQueryHandler(button_callback))

    # 全局错误处理
    application.add_error_handler(error_handler)

    # 启动
    logger.info("FileID Bot 已启动，开始轮询消息...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()