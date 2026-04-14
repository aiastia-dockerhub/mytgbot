"""
详情类命令处理器：影片详情、演员信息、番号列表
"""
import io
import logging
import aiohttp
from html import escape as html_escape
from telegram import Update
from telegram.ext import ContextTypes
from functools import wraps
from config import ADMIN_IDS
from modules.javbus_api import (
    get_single_movie_magnet,
    get_star_info,
    get_star_movie_list,
)

logger = logging.getLogger(__name__)


def admin_only(func):
    """管理员权限装饰器（ADMIN_IDS 为空时所有人可用）"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes, *args, **kwargs):
        if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
            await update.effective_message.reply_text("⛔ 仅管理员可使用此 Bot。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


@admin_only
async def movie_command(update: Update, context: ContextTypes):
    """查看影片详情"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "用法: <code>/movie [番号]</code>\n示例: <code>/movie SSIS-406</code>",
            parse_mode="HTML"
        )
        return

    movie_id = context.args[0].upper()
    await update.message.reply_text(
        f"🔍 正在获取 <code>{html_escape(movie_id)}</code> 详情...",
        parse_mode="HTML"
    )

    result = await get_single_movie_magnet(movie_id)
    if not result:
        await update.message.reply_text(
            f"❌ 未找到影片 <code>{html_escape(movie_id)}</code>",
            parse_mode="HTML"
        )
        return

    detail = result["detail"]

    lines = [f"🎬 <b>{html_escape(detail.get('id', movie_id))}</b>"]
    lines.append(f"📝 {html_escape(detail.get('title', ''))}")
    lines.append(f"📅 日期: {html_escape(detail.get('date', 'N/A'))}")
    lines.append(f"⏱ 时长: {html_escape(str(detail.get('videoLength', 'N/A')))} 分钟")

    if detail.get('director'):
        lines.append(f"🎬 导演: {html_escape(detail['director'].get('name', 'N/A'))}")
    if detail.get('producer'):
        lines.append(f"🏭 制作商: {html_escape(detail['producer'].get('name', 'N/A'))}")
    if detail.get('publisher'):
        lines.append(f"📦 发行商: {html_escape(detail['publisher'].get('name', 'N/A'))}")
    if detail.get('series'):
        lines.append(f"📚 系列: {html_escape(detail['series'].get('name', 'N/A'))}")

    stars = detail.get('stars', [])
    if stars:
        star_names = ", ".join(html_escape(s.get('name', '')) for s in stars)
        lines.append(f"👩 演员: {star_names}")

    genres = detail.get('genres', [])
    if genres:
        genre_names = ", ".join(html_escape(g.get('name', '')) for g in genres)
        lines.append(f"🏷 类别: {genre_names}")

    img_url = detail.get('img', '')
    if img_url:
        cover_url = img_url.replace('/thumb/', '/cover/').replace('.jpg', '_b.jpg')
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        img_data = io.BytesIO(await resp.read())
                        img_data.seek(0)
                        caption = "\n".join(lines[:8])
                        if len(caption) > 1024:
                            caption = caption[:1020] + "..."
                        await update.message.reply_photo(
                            photo=img_data,
                            caption=caption,
                            parse_mode="HTML"
                        )
                        return
        except Exception as e:
            logger.warning("发送封面图失败: %s", e)

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3996] + "..."
    await update.message.reply_text(text, parse_mode="HTML")


@admin_only
async def star_command(update: Update, context: ContextTypes):
    """查看演员信息"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "用法: <code>/star [演员id]</code>\n示例: <code>/star 2xi</code>\n\n"
            "演员ID 获取: 访问 javbus.com/star 页面 URL 中的ID",
            parse_mode="HTML"
        )
        return

    star_id = context.args[0]
    await update.message.reply_text(
        f"🔍 正在获取演员 <code>{html_escape(star_id)}</code> 信息...",
        parse_mode="HTML"
    )

    headers = {}
    from config import JAVBUS_AUTH_TOKEN
    if JAVBUS_AUTH_TOKEN:
        headers['j-auth-token'] = JAVBUS_AUTH_TOKEN

    async with aiohttp.ClientSession(headers=headers) as session:
        info = await get_star_info(session, star_id)

    if not info:
        await update.message.reply_text(
            f"❌ 未找到演员 <code>{html_escape(star_id)}</code>",
            parse_mode="HTML"
        )
        return

    lines = [
        f"👩 <b>{html_escape(info.get('name', 'N/A'))}</b>",
        f"🆔 ID: <code>{html_escape(info.get('id', 'N/A'))}</code>",
    ]
    if info.get('birthday'):
        lines.append(f"🎂 生日: {html_escape(info['birthday'])}")
    if info.get('age'):
        lines.append(f"📐 年龄: {html_escape(str(info['age']))}")
    if info.get('height'):
        lines.append(f"📏 身高: {html_escape(str(info['height']))}")
    if info.get('bust'):
        lines.append(f" bust: {html_escape(str(info['bust']))}")
    if info.get('waistline'):
        lines.append(f"💪 腰围: {html_escape(str(info['waistline']))}")
    if info.get('hipline'):
        lines.append(f"🍑 臀围: {html_escape(str(info['hipline']))}")
    if info.get('birthplace'):
        lines.append(f"🏠 出生地: {html_escape(info['birthplace'])}")
    if info.get('hobby'):
        lines.append(f"🎯 爱好: {html_escape(info['hobby'])}")

    avatar_url = info.get('avatar', '')
    if avatar_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status == 200:
                        img_data = io.BytesIO(await resp.read())
                        img_data.seek(0)
                        caption = "\n".join(lines)
                        if len(caption) > 1024:
                            caption = caption[:1020] + "..."
                        await update.message.reply_photo(
                            photo=img_data,
                            caption=caption,
                            parse_mode="HTML"
                        )
                        return
        except Exception as e:
            logger.warning("发送头像失败: %s", e)

    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="HTML")


@admin_only
async def codes_command(update: Update, context: ContextTypes):
    """列出女优的全部影片番号（不含磁力）"""
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "用法: <code>/codes [演员id]</code>\n示例: <code>/codes 2xi</code>\n\n"
            "演员ID 获取: 访问 javbus.com/star 页面 URL 中的ID",
            parse_mode="HTML"
        )
        return

    star_id = context.args[0]
    status_msg = await update.message.reply_text(
        f"🔍 正在获取演员 <code>{html_escape(star_id)}</code> 的影片列表...",
        parse_mode="HTML"
    )

    movies = await get_star_movie_list(star_id)
    if not movies:
        await status_msg.edit_text(
            f"❌ 未找到演员 <code>{html_escape(star_id)}</code> 的影片",
            parse_mode="HTML"
        )
        return

    total = len(movies)

    # 构建番号列表：番号 + 日期
    code_lines = []
    for m in movies:
        movie_id = html_escape(m.get("id", ""))
        date = html_escape(m.get("date", ""))
        if date:
            code_lines.append(f"<code>{movie_id}</code>  {date}")
        else:
            code_lines.append(f"<code>{movie_id}</code>")

    # Telegram 消息限制 4096 字符，分批发送
    header = f"📋 <b>{html_escape(star_id)}</b> 共 <b>{total}</b> 部影片：\n\n"
    chunk_size = 3800
    chunks = []
    current_chunk = header

    for line in code_lines:
        if len(current_chunk) + len(line) + 2 > chunk_size:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        if len(chunk) > 4096:
            chunk = chunk[:4092] + "\n..."
        if i == 0:
            await status_msg.edit_text(chunk, parse_mode="HTML")
        else:
            await update.message.reply_text(chunk, parse_mode="HTML")

    # 数量较多时，额外发送纯文本番号文件
    if total > 30:
        file_content = "\n".join(m.get("id", "") for m in movies)
        bytes_io = io.BytesIO(file_content.encode("utf-8"))
        bytes_io.seek(0)
        try:
            await context.bot.send_document(
                chat_id=update.message.chat_id,
                document=bytes_io,
                filename=f"codes_{star_id}.txt",
                caption=f"📋 {html_escape(star_id)} 共 {total} 部影片番号",
                reply_to_message_id=update.effective_message.message_id
            )
            bytes_io.close()
        except Exception as e:
            logger.error("发送番号文件失败: %s", e)