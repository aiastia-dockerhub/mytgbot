"""贴纸消息处理"""
import io
import os
import tempfile

from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import Update
from telegram.ext import ContextTypes


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收到贴纸 → 转为图片/文件发送"""
    message = update.message
    sticker = message.sticker

    # 下载贴纸到内存
    file = await context.bot.get_file(sticker.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(out=buf)
    buf.seek(0)

    # 静态贴纸 → 直接发送为图片
    if not sticker.is_animated and not sticker.is_video:
        buf.name = "sticker.png"
        await message.reply_photo(photo=buf)
        buf.close()
        return

    # 视频/动画贴纸 → 发送原始文件
    buf.name = "sticker.webm"
    await message.reply_document(document=buf, filename="sticker.webm")

    # 视频贴纸额外转换为 GIF
    if sticker.is_video:
        buf.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(buf.read())
            tmp_path = tmp.name
        try:
            gif_path = tmp_path.replace(".webm", ".gif")
            clip = VideoFileClip(tmp_path)
            clip.write_gif(gif_path, logger=None)
            clip.close()
            with open(gif_path, "rb") as f:
                await message.reply_document(document=f, filename="sticker.gif")
            os.remove(gif_path)
        finally:
            os.remove(tmp_path)

    buf.close()