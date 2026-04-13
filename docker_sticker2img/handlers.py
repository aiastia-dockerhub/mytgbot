"""贴纸消息处理"""
import io
import logging
import os
import tempfile
import zipfile

from PIL import Image
from telegram import Update
from telegram.ext import ContextTypes

from converters import (
    buf_to_cropped_png,
    buf_to_jpg,
    crop_transparent,
    tgs_to_gif,
    webm_to_gif,
)

logger = logging.getLogger(__name__)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收到贴纸 → 转为常见格式发送"""
    message = update.message
    sticker = message.sticker

    file = await context.bot.get_file(sticker.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(out=buf)
    buf.seek(0)

    # ===== 静态贴纸 → PNG（图片）+ JPG（文件）=====
    if not sticker.is_animated and not sticker.is_video:
        # 以图片形式发送裁剪后的 PNG
        png_buf = buf_to_cropped_png(buf)
        await message.reply_photo(photo=png_buf)
        # 以文件形式发送裁剪后的 JPG
        jpg_buf = buf_to_jpg(buf)
        await message.reply_document(document=jpg_buf, filename="sticker.jpg")
        buf.close()
        return

    # ===== 动画贴纸（TGS）→ GIF + TGS 源文件 =====
    if sticker.is_animated and not sticker.is_video:
        with tempfile.NamedTemporaryFile(suffix=".tgs", delete=False) as tmp:
            tmp.write(buf.getvalue())
            tmp_path = tmp.name
        try:
            gif_path = tmp_path.replace(".tgs", ".gif")
            tgs_to_gif(tmp_path, gif_path)
            try:
                with open(gif_path, "rb") as f:
                    await message.reply_document(document=f, filename="sticker.gif")
            except Exception:
                logger.warning("发送 GIF 失败", exc_info=True)
            if os.path.exists(gif_path):
                os.remove(gif_path)
        except Exception:
            logger.exception("TGS 转换失败")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        buf.seek(0)
        await message.reply_document(document=buf, filename="sticker.tgs")
        buf.close()
        return

    # ===== 视频贴纸（webm）→ webm + GIF =====
    buf.name = "sticker.webm"
    await message.reply_document(document=buf, filename="sticker.webm")

    buf.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(buf.read())
        tmp_path = tmp.name
    try:
        gif_path = tmp_path.replace(".webm", ".gif")
        webm_to_gif(tmp_path, gif_path)
        try:
            with open(gif_path, "rb") as f:
                await message.reply_document(document=f, filename="sticker.gif")
        except Exception:
            logger.warning("发送 GIF 失败", exc_info=True)
        if os.path.exists(gif_path):
            os.remove(gif_path)
    except Exception:
        logger.exception("webm 转 GIF 失败")
    finally:
        os.remove(tmp_path)

    buf.close()


async def handle_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """回复一个贴纸发送 /pack → 下载整个表情包为 ZIP"""
    message = update.message

    if not message.reply_to_message or not message.reply_to_message.sticker:
        await message.reply_text("❌ 请回复一个贴纸消息来使用 /pack 命令")
        return

    sticker = message.reply_to_message.sticker
    sticker_set_name = sticker.set_name

    if not sticker_set_name:
        await message.reply_text("❌ 该贴纸不属于任何表情包")
        return

    status_msg = await message.reply_text("📦 正在下载表情包，请稍候...")

    try:
        sticker_set = await context.bot.get_sticker_set(sticker_set_name)
        pack_name = sticker_set.name
        stickers = sticker_set.stickers

        is_animated = stickers[0].is_animated if stickers else False
        is_video = stickers[0].is_video if stickers else False

        zip_buf = io.BytesIO()

        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, stk in enumerate(stickers):
                try:
                    stk_file = await context.bot.get_file(stk.file_id)
                    stk_buf = io.BytesIO()
                    await stk_file.download_to_memory(out=stk_buf)

                    if not is_animated and not is_video:
                        _pack_static(zf, stk_buf, pack_name, i)
                    elif is_animated:
                        _pack_tgs(zf, stk_buf, pack_name, i)
                    else:
                        _pack_webm(zf, stk_buf, pack_name, i)

                except Exception:
                    logger.warning("下载贴纸 %d 失败，跳过", i)
                    continue

        zip_buf.seek(0)
        zip_buf.name = f"{pack_name}.zip"
        await message.reply_document(
            document=zip_buf,
            filename=f"{pack_name}.zip",
            caption=f"📦 {sticker_set.title}（{len(stickers)} 个贴纸）",
        )

    except Exception:
        logger.exception("下载表情包失败")
        await message.reply_text("❌ 下载表情包失败，请稍后重试")
    finally:
        try:
            await status_msg.delete()
        except Exception:
            pass


def _pack_static(zf: zipfile.ZipFile, stk_buf: io.BytesIO, pack_name: str, idx: int):
    """静态贴纸 → 裁剪白边后的 PNG + JPG 写入 ZIP"""
    stk_buf.seek(0)
    img = Image.open(stk_buf)
    img = crop_transparent(img) if img.mode == "RGBA" else img

    png_buf = io.BytesIO()
    img.save(png_buf, format="PNG")
    zf.writestr(f"{pack_name}/{idx:03d}.png", png_buf.getvalue())

    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    else:
        img = img.convert("RGB")
    jpg_buf = io.BytesIO()
    img.save(jpg_buf, format="JPEG", quality=95)
    zf.writestr(f"{pack_name}/{idx:03d}.jpg", jpg_buf.getvalue())


def _pack_tgs(zf: zipfile.ZipFile, stk_buf: io.BytesIO, pack_name: str, idx: int):
    """动画贴纸 → TGS + GIF 写入 ZIP"""
    stk_buf.seek(0)
    zf.writestr(f"{pack_name}/{idx:03d}.tgs", stk_buf.read())

    try:
        with tempfile.NamedTemporaryFile(suffix=".tgs", delete=False) as tmp:
            tmp.write(stk_buf.getvalue())
            tmp_path = tmp.name
        try:
            gif_path = tmp_path.replace(".tgs", ".gif")
            tgs_to_gif(tmp_path, gif_path)
            with open(gif_path, "rb") as f:
                zf.writestr(f"{pack_name}/{idx:03d}.gif", f.read())
            if os.path.exists(gif_path):
                os.remove(gif_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    except Exception:
        logger.warning("贴纸 %d TGS 转换失败，跳过", idx)


def _pack_webm(zf: zipfile.ZipFile, stk_buf: io.BytesIO, pack_name: str, idx: int):
    """视频贴纸 → webm + GIF 写入 ZIP"""
    stk_buf.seek(0)
    zf.writestr(f"{pack_name}/{idx:03d}.webm", stk_buf.read())

    try:
        stk_buf.seek(0)
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(stk_buf.read())
            tmp_path = tmp.name
        try:
            gif_path = tmp_path.replace(".webm", ".gif")
            webm_to_gif(tmp_path, gif_path)
            with open(gif_path, "rb") as f:
                zf.writestr(f"{pack_name}/{idx:03d}.gif", f.read())
            os.remove(gif_path)
        finally:
            os.remove(tmp_path)
    except Exception:
        logger.warning("贴纸 %d webm 转 GIF 失败，跳过", idx)