"""贴纸消息处理"""
import io
import logging
import os
import shutil
import subprocess
import tempfile
import zipfile

from PIL import Image
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


def _webm_to_gif(webm_path: str, gif_path: str) -> None:
    """webm → GIF（两阶段调色板 + 白色背景）"""
    palette_path = webm_path + ".palette.png"
    try:
        # 阶段1: 生成调色板（白色背景）
        subprocess.run([
            "ffmpeg", "-y", "-i", webm_path,
            "-vf", "fps=15,scale=300:-1:flags=lanczos,format=rgba,drawbox=color=white@1:t=fill,palettegen",
            palette_path,
        ], check=True, capture_output=True)
        # 阶段2: 使用调色板生成 GIF（白色背景）
        subprocess.run([
            "ffmpeg", "-y", "-i", webm_path, "-i", palette_path,
            "-filter_complex", "fps=15,scale=300:-1:flags=lanczos,format=rgba,drawbox=color=white@1:t=fill[x];[x][1:v]paletteuse",
            gif_path,
        ], check=True, capture_output=True)
    finally:
        if os.path.exists(palette_path):
            os.remove(palette_path)


def _tgs_to_webp(tgs_path: str, webp_path: str) -> None:
    """TGS → 逐帧渲染 RGBA PNG → ffmpeg 合成动态 WebP（保留透明通道）"""
    anim = LottieAnimation.from_tgs(tgs_path)
    total_frames = anim.lottie_animation_get_totalframe()
    fps = anim.lottie_animation_get_framerate() or 30

    frames_dir = tempfile.mkdtemp()
    try:
        for frame_num in range(total_frames):
            frame = anim.render_pillow_frame(frame_num=frame_num)
            frame.save(os.path.join(frames_dir, f"frame_{frame_num:04d}.png"))
        anim.dispose()

        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "frame_%04d.png"),
            "-vcodec", "libwebp",
            "-lossless", "0",
            "-compression_level", "4",
            "-quality", "75",
            "-loop", "0",
            "-preset", "default",
            "-an",
            webp_path,
        ], check=True, capture_output=True)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


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

    # ===== 动画贴纸（TGS）→ GIF + WebP + TGS 源文件 =====
    if sticker.is_animated and not sticker.is_video:
        with tempfile.NamedTemporaryFile(suffix=".tgs", delete=False) as tmp:
            tmp.write(buf.getvalue())
            tmp_path = tmp.name
        try:
            anim = LottieAnimation.from_tgs(tmp_path)
            gif_path = tmp_path.replace(".tgs", ".gif")
            anim.save_animation(gif_path)
            anim.dispose()

            # TGS → WebP（逐帧渲染，保留透明通道）
            webp_path = tmp_path.replace(".tgs", ".webp")
            try:
                _tgs_to_webp(tmp_path, webp_path)
            except Exception:
                logger.warning("TGS 转 WebP 失败", exc_info=True)
                webp_path = None

            # 发送 GIF 动图
            try:
                with open(gif_path, "rb") as f:
                    await message.reply_document(document=f, filename="sticker.gif")
            except Exception:
                logger.warning("发送 GIF 失败", exc_info=True)
            os.remove(gif_path)

            # 发送 WebP 动图
            if webp_path and os.path.exists(webp_path):
                try:
                    with open(webp_path, "rb") as f:
                        await message.reply_document(document=f, filename="sticker.webp")
                except Exception:
                    logger.warning("发送 WebP 失败", exc_info=True)
                os.remove(webp_path)

        except Exception:
            logger.exception("TGS 转换失败")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # 发送 TGS 源文件
        buf.seek(0)
        await message.reply_document(document=buf, filename="sticker.tgs")
        buf.close()
        return

    # ===== 视频贴纸（webm）→ webm + GIF + WebP =====
    # 发送原始 webm 文件
    buf.name = "sticker.webm"
    await message.reply_document(document=buf, filename="sticker.webm")

    # 转为 GIF 和 WebP
    buf.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(buf.read())
        tmp_path = tmp.name
    try:
        gif_path = tmp_path.replace(".webm", ".gif")
        webp_path = tmp_path.replace(".webm", ".webp")

        # webm → GIF（两阶段调色板 + 白色背景）
        _webm_to_gif(tmp_path, gif_path)

        # webm → WebP（ffmpeg，lossy 压缩保留透明通道）
        subprocess.run([
            "ffmpeg", "-y", "-i", tmp_path,
            "-vcodec", "libwebp", "-lossless", "0",
            "-compression_level", "4", "-quality", "75",
            "-loop", "0", "-preset", "default", "-an", "-vsync", "0",
            webp_path,
        ], check=True, capture_output=True)

        # 发送 GIF 动图
        try:
            with open(gif_path, "rb") as f:
                await message.reply_document(document=f, filename="sticker.gif")
        except Exception:
            logger.warning("发送 GIF 失败", exc_info=True)

        # 发送 WebP 动图
        try:
            with open(webp_path, "rb") as f:
                await message.reply_document(document=f, filename="sticker.webp")
        except Exception:
            logger.warning("发送 WebP 失败", exc_info=True)

        if os.path.exists(gif_path):
            os.remove(gif_path)
        if os.path.exists(webp_path):
            os.remove(webp_path)
    except Exception:
        logger.exception("webm 转换失败")
    finally:
        os.remove(tmp_path)

    buf.close()


async def handle_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """回复一个贴纸发送 /pack → 下载整个表情包为 ZIP"""
    message = update.message

    # 必须回复一个贴纸消息
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
        # 获取表情包信息
        sticker_set = await context.bot.get_sticker_set(sticker_set_name)
        pack_name = sticker_set.name
        stickers = sticker_set.stickers

        is_animated = sticker_set.is_animated
        is_video = sticker_set.is_video

        # 创建 ZIP 到内存
        zip_buf = io.BytesIO()

        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, stk in enumerate(stickers):
                try:
                    stk_file = await context.bot.get_file(stk.file_id)
                    stk_buf = io.BytesIO()
                    await stk_file.download_to_memory(out=stk_buf)

                    if not is_animated and not is_video:
                        # 静态贴纸 → PNG + JPG
                        stk_buf.seek(0)
                        zf.writestr(f"{pack_name}/{i:03d}.png", stk_buf.read())

                        stk_buf.seek(0)
                        img = Image.open(stk_buf).convert("RGB")
                        jpg_buf = io.BytesIO()
                        img.save(jpg_buf, format="JPEG", quality=95)
                        zf.writestr(f"{pack_name}/{i:03d}.jpg", jpg_buf.getvalue())

                    elif is_animated:
                        # 动画贴纸 → TGS + GIF + WebP
                        stk_buf.seek(0)
                        zf.writestr(f"{pack_name}/{i:03d}.tgs", stk_buf.read())

                        try:
                            with tempfile.NamedTemporaryFile(suffix=".tgs", delete=False) as tmp:
                                tmp.write(stk_buf.getvalue())
                                tmp_path = tmp.name
                            try:
                                anim = LottieAnimation.from_tgs(tmp_path)
                                gif_path = tmp_path.replace(".tgs", ".gif")
                                anim.save_animation(gif_path)
                                anim.dispose()
                                with open(gif_path, "rb") as f:
                                    zf.writestr(f"{pack_name}/{i:03d}.gif", f.read())
                                os.remove(gif_path)

                                # TGS → WebP
                                webp_path = tmp_path.replace(".tgs", ".webp")
                                try:
                                    _tgs_to_webp(tmp_path, webp_path)
                                    with open(webp_path, "rb") as f:
                                        zf.writestr(f"{pack_name}/{i:03d}.webp", f.read())
                                    os.remove(webp_path)
                                except Exception:
                                    logger.warning("贴纸 %d TGS 转 WebP 失败，跳过", i)
                            finally:
                                if os.path.exists(tmp_path):
                                    os.remove(tmp_path)
                        except Exception:
                            logger.warning("贴纸 %d TGS 转换失败，跳过", i)

                    else:
                        # 视频贴纸 → webm + GIF + WebP
                        stk_buf.seek(0)
                        zf.writestr(f"{pack_name}/{i:03d}.webm", stk_buf.read())

                        try:
                            stk_buf.seek(0)
                            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                                tmp.write(stk_buf.read())
                                tmp_path = tmp.name
                            try:
                                gif_path = tmp_path.replace(".webm", ".gif")
                                webp_path = tmp_path.replace(".webm", ".webp")
                                _webm_to_gif(tmp_path, gif_path)
                                subprocess.run([
                                    "ffmpeg", "-y", "-i", tmp_path,
                                    "-vcodec", "libwebp", "-lossless", "0",
                                    "-compression_level", "4", "-quality", "75",
                                    "-loop", "0", "-preset", "default", "-an", "-vsync", "0",
                                    webp_path,
                                ], check=True, capture_output=True)
                                with open(gif_path, "rb") as f:
                                    zf.writestr(f"{pack_name}/{i:03d}.gif", f.read())
                                with open(webp_path, "rb") as f:
                                    zf.writestr(f"{pack_name}/{i:03d}.webp", f.read())
                                os.remove(gif_path)
                                os.remove(webp_path)
                            finally:
                                os.remove(tmp_path)
                        except Exception:
                            logger.warning("贴纸 %d webm 转换失败，跳过", i)

                except Exception:
                    logger.warning("下载贴纸 %d 失败，跳过", i)
                    continue

        # 发送 ZIP 文件
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