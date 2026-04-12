"""贴纸消息处理"""
import io
import logging
import os
import tempfile

from PIL import Image
from moviepy.video.io.VideoFileClip import VideoFileClip
from rlottie_python import LottieAnimation
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def _buf_to_jpg(buf: io.BytesIO) -> io.BytesIO:
    """将图像转为 JPG BytesIO"""
    buf.seek(0)
    img = Image.open(buf).convert("RGB")
    jpg_buf = io.BytesIO()
    img.save(jpg_buf, format="JPEG", quality=95)
    jpg_buf.seek(0)
    return jpg_buf


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收到贴纸 → 转为常见格式发送"""
    message = update.message
    sticker = message.sticker

    # 下载贴纸到内存
    file = await context.bot.get_file(sticker.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(out=buf)
    buf.seek(0)

    # ===== 静态贴纸 → PNG + JPG =====
    if not sticker.is_animated and not sticker.is_video:
        # 发送 PNG 图片（聊天中直接查看）
        buf.seek(0)
        buf.name = "sticker.png"
        await message.reply_photo(photo=buf)
        # 发送 JPG 源文件（可下载）
        jpg_buf = _buf_to_jpg(buf)
        await message.reply_document(document=jpg_buf, filename="sticker.jpg")
        buf.close()
        return

    # ===== 动画贴纸（TGS）→ GIF + TGS 源文件 =====
    if sticker.is_animated and not sticker.is_video:
        # 保存 TGS 到临时文件
        with tempfile.NamedTemporaryFile(suffix=".tgs", delete=False) as tmp:
            tmp.write(buf.getvalue())
            tmp_path = tmp.name
        try:
            anim = LottieAnimation.from_tgs(tmp_path)
            # 生成 GIF
            gif_path = tmp_path.replace(".tgs", ".gif")
            anim.save_animation(gif_path)
            anim.dispose()

            # 发送 GIF 动图（可下载）
            with open(gif_path, "rb") as f:
                await message.reply_document(document=f, filename="sticker.gif")

            os.remove(gif_path)
        except Exception:
            logger.exception("TGS 转 GIF 失败")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # 发送 TGS 源文件
        buf.seek(0)
        await message.reply_document(document=buf, filename="sticker.tgs")
        buf.close()
        return

    # ===== 视频贴纸（webm）→ webm + GIF =====
    # 发送原始 webm 文件
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