"""贴纸消息处理"""
import io
import os
import tempfile

from PIL import Image
from moviepy.video.io.VideoFileClip import VideoFileClip
from telegram import Update
from telegram.ext import ContextTypes


def _send_jpg(buf: io.BytesIO) -> io.BytesIO:
    """将图像转为 JPG BytesIO（用于 photo 和 document 复用）"""
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    jpg_buf = io.BytesIO()
    img.save(jpg_buf, format="JPEG", quality=95)
    jpg_buf.seek(0)
    return jpg_buf


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收到贴纸 → 转为 JPG 图片 + JPG 源文件发送"""
    message = update.message
    sticker = message.sticker

    # 下载贴纸到内存
    file = await context.bot.get_file(sticker.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(out=buf)
    buf.seek(0)

    # ===== 静态贴纸 =====
    if not sticker.is_animated and not sticker.is_video:
        # 发送 PNG 图片（聊天中直接查看）
        buf.seek(0)
        buf.name = "sticker.png"
        await message.reply_photo(photo=buf)
        # 发送 PNG 源文件（可下载）
        buf.seek(0)
        await message.reply_document(document=buf, filename="sticker.png")
        # 发送 JPG 源文件（可下载）
        jpg_buf = _send_jpg(buf)
        await message.reply_document(document=jpg_buf, filename="sticker.jpg")
        buf.close()
        return

    # ===== 视频/动画贴纸 =====
    # 先发送原始 webm 文件
    buf.name = "sticker.webm"
    await message.reply_document(document=buf, filename="sticker.webm")

    # 转为 GIF 动图
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
            # 发送 GIF 动图源文件（可下载）
            await message.reply_document(document=f, filename="sticker.gif")
        os.remove(gif_path)
    finally:
        os.remove(tmp_path)

    buf.close()
