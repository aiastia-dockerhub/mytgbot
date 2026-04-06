"""
Telegram 命令处理器
"""
import io
import logging
import aiohttp
from html import escape as html_escape
from telegram import Update
from telegram.ext import ContextTypes
from functools import wraps
from config import ADMIN_IDS, JAVBUS_API_URL
from modules.javbus_api import (
    get_single_movie_magnet,
    get_all_movie_ids_by_filter,
    search_all_movie_ids,
    get_magnets_for_movie_list,
    get_star_info,
)

logger = logging.getLogger(__name__)


def admin_only(func):
    """管理员权限装饰器"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.effective_message.reply_text("⛔ 仅管理员可使用此 Bot。")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


@admin_only
async def help_command(update: Update, context: ContextTypes):
    """帮助命令"""
    text = (
        "🔞 <b>JavBus 磁力搜索 Bot</b>\n\n"
        "📋 <b>命令列表:</b>\n"
        "<code>/jav <番号></code> — 查询单个影片磁力链接\n"
        "  示例: <code>/jav SSIS-406</code>\n\n"
        "<code>/jav_star <演员id></code> — 获取演员全部影片磁力链接\n"
        "  示例: <code>/jav_star 2xi</code>\n\n"
        "<code>/jav_filter <类型> <值></code> — 按类型筛选影片\n"
        "  类型: <code>star</code> <code>genre</code> <code>director</code> <code>studio</code> <code>label</code> <code>series</code>\n"
        "  示例: <code>/jav_filter star 2xi</code>\n\n"
        "<code>/jav_search <关键词></code> — 搜索影片\n"
        "  示例: <code>/jav_search 三上</code>\n\n"
        "<code>/movie <番号></code> — 查看影片详情（封面、演员、类别等）\n"
        "  示例: <code>/movie SSIS-406</code>\n\n"
        "<code>/star <演员id></code> — 查看演员信息\n"
        "  示例: <code>/star 2xi</code>\n\n"
        "📖 <b>说明:</b>\n"
        "• 演员ID 获取: 访问 javbus.com/star 页面，URL 中的ID\n"
        "• <code>/jav_star</code> 和 <code>/jav_filter</code> 结果以文件形式发送\n"
        "• <code>/jav</code> 直接返回磁力链接文本"
    )
    await update.message.reply_text(text, parse_mode="HTML")


@admin_only
async def jav_command(update: Update, context: ContextTypes):
    """查询单个影片的磁力链接: /jav <番号>"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "用法: <code>/jav <番号></code>\n示例: <code>/jav SSIS-406</code>",
            parse_mode="HTML"
        )
        return

    movie_id = context.args[0].upper()
    await update.message.reply_text(f"🔍 正在查询 <code>{html_escape(movie_id)}</code> ...", parse_mode="HTML")

    result = await get_single_movie_magnet(movie_id)
    if not result:
        await update.message.reply_text(f"❌ 未找到影片 <code>{html_escape(movie_id)}</code>", parse_mode="HTML")
        return

    detail = result["detail"]
    magnets = result["magnets"]

    if not magnets:
        await update.message.reply_text(f"❌ 影片 <code>{html_escape(movie_id)}</code> 暂无磁力链接", parse_mode="HTML")
        return

    # 构建回复消息
    title = html_escape(detail.get("title", movie_id))
    lines = [f"🎬 <b>{html_escape(movie_id)}</b>\n{title}\n"]

    for i, m in enumerate(magnets[:5], 1):
        size = html_escape(m.get("size", "?"))
        hd = "🎬" if m.get("isHD") else ""
        sub = "📝" if m.get("hasSubtitle") else ""
        link = html_escape(m['link'])
        lines.append(f"<code>{i}. [{size}] {hd}{sub}</code> {link}")

    if len(magnets) > 5:
        lines.append(f"\n... 共 {len(magnets)} 个磁力链接")

    text = "\n".join(lines)
    # Telegram 消息长度限制
    if len(text) > 4000:
        # 太长则只发最大的
        best = max(magnets, key=lambda x: x.get('numberSize', 0) or 0)
        text = (f"🎬 <b>{html_escape(movie_id)}</b>\n{title}\n\n"
                f"🏆 最大文件: {html_escape(best.get('size', ''))}\n<code>{html_escape(best['link'])}</code>")

    await update.message.reply_text(text, parse_mode="HTML")


@admin_only
async def jav_star_command(update: Update, context: ContextTypes):
    """获取演员全部影片磁力链接: /jav_star <演员id>"""
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "用法: <code>/jav_star <演员id></code>\n示例: <code>/jav_star 2xi</code>",
            parse_mode="HTML"
        )
        return

    star_id = context.args[0]
    await update.message.reply_text(
        f"🔍 正在获取演员 <code>{html_escape(star_id)}</code> 的全部影片，请稍候...",
        parse_mode="HTML"
    )

    movie_ids = await get_all_movie_ids_by_filter("star", star_id)
    if not movie_ids:
        await update.message.reply_text(f"❌ 未找到演员 <code>{html_escape(star_id)}</code> 的影片", parse_mode="HTML")
        return

    results = await get_magnets_for_movie_list(movie_ids)
    if not results:
        await update.message.reply_text("❌ 未能获取到磁力链接")
        return

    # 生成 txt 文件
    lines = [f"{r['id']} | {r['size']} | {r['link']}" for r in results]
    content = "\n".join(lines)
    await _send_magnet_file(update, context, content, f"star_{star_id}.txt", len(results))


@admin_only
async def jav_filter_command(update: Update, context: ContextTypes):
    """按类型筛选: /jav_filter <类型> <值>"""
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "用法: <code>/jav_filter <类型> <值></code>\n"
            "类型: <code>star</code> <code>genre</code> <code>director</code> <code>studio</code> <code>label</code> <code>series</code>\n"
            "示例: <code>/jav_filter star 2xi</code>",
            parse_mode="HTML"
        )
        return

    filter_type = context.args[0]
    filter_value = context.args[1]

    valid_types = ("star", "genre", "director", "studio", "label", "series")
    if filter_type not in valid_types:
        types_str = ", ".join(f"<code>{t}</code>" for t in valid_types)
        await update.message.reply_text(
            f"❌ 无效类型 <code>{html_escape(filter_type)}</code>，可选: {types_str}",
            parse_mode="HTML"
        )
        return

    await update.message.reply_text(
        f"🔍 正在按 <code>{html_escape(filter_type)}={html_escape(filter_value)}</code> 筛选，请稍候...",
        parse_mode="HTML"
    )

    movie_ids = await get_all_movie_ids_by_filter(filter_type, filter_value)
    if not movie_ids:
        await update.message.reply_text("❌ 未找到符合条件的影片")
        return

    results = await get_magnets_for_movie_list(movie_ids)
    if not results:
        await update.message.reply_text("❌ 未能获取到磁力链接")
        return

    lines = [f"{r['id']} | {r['size']} | {r['link']}" for r in results]
    content = "\n".join(lines)
    await _send_magnet_file(update, context, content, f"{filter_type}_{filter_value}.txt", len(results))


@admin_only
async def jav_search_command(update: Update, context: ContextTypes):
    """搜索影片: /jav_search <关键词>"""
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            "用法: <code>/jav_search <关键词></code>\n示例: <code>/jav_search 三上</code>",
            parse_mode="HTML"
        )
        return

    keyword = " ".join(context.args)
    await update.message.reply_text(
        f"🔍 正在搜索 <code>{html_escape(keyword)}</code>，请稍候...",
        parse_mode="HTML"
    )

    movie_ids = await search_all_movie_ids(keyword)
    if not movie_ids:
        await update.message.reply_text(f"❌ 未找到关键词 <code>{html_escape(keyword)}</code> 的影片", parse_mode="HTML")
        return

    results = await get_magnets_for_movie_list(movie_ids)
    if not results:
        await update.message.reply_text("❌ 未能获取到磁力链接")
        return

    lines = [f"{r['id']} | {r['size']} | {r['link']}" for r in results]
    content = "\n".join(lines)
    await _send_magnet_file(update, context, content, f"search_{keyword}.txt", len(results))


@admin_only
async def movie_command(update: Update, context: ContextTypes):
    """查看影片详情: /movie <番号>"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "用法: <code>/movie <番号></code>\n示例: <code>/movie SSIS-406</code>",
            parse_mode="HTML"
        )
        return

    movie_id = context.args[0].upper()
    await update.message.reply_text(f"🔍 正在获取 <code>{html_escape(movie_id)}</code> 详情...", parse_mode="HTML")

    result = await get_single_movie_magnet(movie_id)
    if not result:
        await update.message.reply_text(f"❌ 未找到影片 <code>{html_escape(movie_id)}</code>", parse_mode="HTML")
        return

    detail = result["detail"]

    # 构建详情消息
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

    # 尝试发送封面图
    img_url = detail.get('img', '')
    if img_url:
        # 替换为封面大图
        cover_url = img_url.replace('/thumb/', '/cover/').replace('.jpg', '_b.jpg')
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        img_data = io.BytesIO(await resp.read())
                        img_data.seek(0)
                        caption = "\n".join(lines[:8])  # 限制 caption 长度
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

    # 如果图片发送失败，纯文本发送
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3996] + "..."
    await update.message.reply_text(text, parse_mode="HTML")


@admin_only
async def star_command(update: Update, context: ContextTypes):
    """查看演员信息: /star <演员id>"""
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "用法: <code>/star <演员id></code>\n示例: <code>/star 2xi</code>\n\n"
            "演员ID 获取: 访问 javbus.com/star 页面 URL 中的ID",
            parse_mode="HTML"
        )
        return

    star_id = context.args[0]
    await update.message.reply_text(f"🔍 正在获取演员 <code>{html_escape(star_id)}</code> 信息...", parse_mode="HTML")

    headers = {}
    from config import JAVBUS_AUTH_TOKEN
    if JAVBUS_AUTH_TOKEN:
        headers['j-auth-token'] = JAVBUS_AUTH_TOKEN

    async with aiohttp.ClientSession(headers=headers) as session:
        info = await get_star_info(session, star_id)

    if not info:
        await update.message.reply_text(f"❌ 未找到演员 <code>{html_escape(star_id)}</code>", parse_mode="HTML")
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

    # 尝试发送头像
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


async def _send_magnet_file(update, context, content, filename, count):
    """发送磁力链接 txt 文件"""
    bytes_io = io.BytesIO(content.encode('utf-8'))
    bytes_io.seek(0)
    try:
        await context.bot.send_document(
            chat_id=update.message.chat_id,
            document=bytes_io,
            filename=filename,
            caption=f"✅ 共获取到 {count} 个磁力链接",
            reply_to_message_id=update.effective_message.message_id
        )
        bytes_io.close()
    except Exception as e:
        logger.error("发送文件失败: %s", e)
        await update.message.reply_text(f"❌ 发送文件失败: {e}")