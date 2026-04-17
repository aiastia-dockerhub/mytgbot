"""命令处理器模块"""
import io
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from config import MAX_COLLECTION_FILES, FILE_TYPE_MAP
from database import (
    save_file, get_file, get_collection, create_collection,
    add_file_to_collection, complete_collection, delete_collection,
    get_user_collections, get_stats, get_all_files_for_export
)
from utils import get_code_prefix, escape_markdown, generate_raw_code, admin_only

logger = logging.getLogger(__name__)


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

    await update.message.reply_text(help_text, parse_mode="Markdown", disable_web_page_preview=True)


async def create_collection_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/create 创建集合"""
    user_id = update.effective_user.id
    bot_username = context.bot.username

    if context.user_data.get('creating_collection'):
        await update.message.reply_text("⚠️ 你已有正在创建的集合，请先 `/done` 完成或 `/cancel` 取消。")
        return

    name = ' '.join(context.args) if context.args else f"集合_{datetime.now().strftime('%m%d%H%M')}"
    code_prefix = get_code_prefix(bot_username)
    raw_code = generate_raw_code()
    full_code = f"{code_prefix}_col:{raw_code}"

    if create_collection(full_code, bot_username, name, user_id):
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
    else:
        await update.message.reply_text("❌ 创建集合失败，请重试。")


async def done_collection_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done 完成集合"""
    col_code = context.user_data.get('creating_collection')
    if not col_code:
        await update.message.reply_text("⚠️ 你没有正在创建的集合。发送 `/create 名称` 开始。")
        return

    count = context.user_data.get('collection_count', 0)
    if count == 0:
        delete_collection(col_code)
        await update.message.reply_text("⚠️ 集合为空，已自动取消。")
    else:
        complete_collection(col_code, count)
        col_info = get_collection(col_code)
        col_name = col_info['name'] if col_info else "未命名"
        safe_name = escape_markdown(col_name)
        await update.message.reply_text(
            f"🎉 集合「{safe_name}」创建完成！\n\n"
            f"📦 代码: `{col_code}`\n"
            f"📊 共 {count} 个文件\n\n"
            f"将代码发送给 bot 即可获取所有文件。",
            parse_mode="Markdown"
        )

    context.user_data.pop('creating_collection', None)
    context.user_data.pop('collection_count', None)


async def cancel_collection_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cancel 取消当前操作"""
    col_code = context.user_data.get('creating_collection')
    if col_code:
        delete_collection(col_code)
        context.user_data.pop('creating_collection', None)
        context.user_data.pop('collection_count', None)
        await update.message.reply_text("❌ 已取消当前集合。")
    else:
        context.user_data['stop_auto_send'] = True
        await update.message.reply_text("❌ 已停止当前操作。")


async def my_collections_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mycol 查看我的集合"""
    user_id = update.effective_user.id
    rows = get_user_collections(user_id)

    if not rows:
        await update.message.reply_text("📦 你还没有创建任何集合。")
        return

    text = "📦 *我的集合列表：*\n\n"
    for r in rows:
        status_icon = "✅" if r['status'] == 'completed' else "🔧"
        safe_name = escape_markdown(r['name'])
        text += (
            f"{status_icon} *{safe_name}*\n"
            f"  代码: `{r['code']}`\n"
            f"  文件数: {r['file_count']} | 创建于: {r['created_at']}\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")


async def delete_collection_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/delcol 删除集合"""
    user_id = update.effective_user.id
    if not context.args:
        code_prefix = get_code_prefix(context.bot.username)
        await update.message.reply_text(f"请提供集合代码。\n用法: `/delcol {code_prefix}_col:xxx`", parse_mode="Markdown")
        return

    col_code = context.args[0]
    col_info = get_collection(col_code)
    if not col_info:
        await update.message.reply_text("❌ 集合不存在。")
        return
    from config import ADMIN_IDS
    if col_info['user_id'] != user_id and user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ 你没有权限删除此集合。")
        return

    delete_collection(col_code)
    await update.message.reply_text("✅ 集合已删除。")


async def get_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/getid 回复消息获取文件ID"""
    if not update.message.reply_to_message:
        await update.message.reply_text("请回复一条包含媒体的消息来获取其ID。\n用法: 回复消息 + `/getid`", parse_mode="Markdown")
        return

    replied = update.message.reply_to_message
    bot_username = context.bot.username
    user_id = update.effective_user.id
    code_prefix = get_code_prefix(bot_username)
    result = None
    file_type = None

    if replied.photo:
        photo = replied.photo[len(replied.photo) - 1]
        result = save_file(user_id, 'photo', photo.file_id, photo.file_size or 0, photo.file_unique_id or '', bot_username, code_prefix)
        file_type = '图片'
    elif replied.video:
        result = save_file(user_id, 'video', replied.video.file_id, replied.video.file_size or 0, replied.video.file_unique_id or '', bot_username, code_prefix)
        file_type = '视频'
    elif replied.audio:
        result = save_file(user_id, 'audio', replied.audio.file_id, replied.audio.file_size or 0, replied.audio.file_unique_id or '', bot_username, code_prefix)
        file_type = '音频'
    elif replied.document:
        result = save_file(user_id, 'document', replied.document.file_id, replied.document.file_size or 0, replied.document.file_unique_id or '', bot_username, code_prefix)
        file_type = '文档'
    elif replied.voice:
        result = save_file(user_id, 'voice', replied.voice.file_id, replied.voice.file_size or 0, replied.voice.file_unique_id or '', bot_username, code_prefix)
        file_type = '语音'
    else:
        await update.message.reply_text("❌ 回复的消息不包含可识别的媒体文件。")
        return

    if result:
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
    stats = get_stats()
    type_text = "\n".join(f"  {FILE_TYPE_MAP.get(r['file_type'], r['file_type'])}: {r['c']}" for r in stats['type_stats'])
    text = (
        f"📊 *Bot 统计信息*\n\n"
        f"📁 总文件数: {stats['file_count']}\n"
        f"📦 总集合数: {stats['col_count']}\n"
        f"👥 总用户数: {stats['user_count']}\n"
        f"📅 今日新增: {stats['today_files']}\n\n"
        f"📋 按类型统计:\n{type_text}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/export 管理员导出数据"""
    rows = get_all_files_for_export()
    if not rows:
        await update.message.reply_text("没有数据可导出。")
        return

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