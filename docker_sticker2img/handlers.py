"""贴纸消息处理"""
import io
import logging
import os
import tempfile
import zipfile

import numpy as np
from PIL import Image
from moviepy import VideoFileClip, ColorClip, CompositeVideoClip
from moviepy.video.fx import Crop
from rlottie_python import LottieAnimation
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def _crop_transparent(img: Image.Image, padding: int = 4) -> Image.Image:
    """裁剪图片中的透明区域，只保留内容部分（带少量 padding）"""
    if img.mode != "RGBA":
        return img
    bbox = img.getbbox()  # (left, top, right, bottom) 非零区域
    if not bbox:
        return img
    # 加 padding
    bbox = (
        max(0, bbox[0] - padding),
        max(0, bbox[1] - padding),
        min(img.width, bbox[2] + padding),
        min(img.height, bbox[3] + padding),
    )
    return img.crop(bbox)


def _tgs_to_gif(tgs_path: str, gif_path: str) -> None:
    """TGS → GIF（逐帧提取 + 自动裁剪白边 + 白色背景）"""
    anim = LottieAnimation.from_tgs(tgs_path)
    total_frames = anim.lottie_animation_get_totalframe()
    fps = anim.lottie_animation_get_framerate()

    # 先收集所有 RGBA 帧
    rgba_frames = []
    for i in range(total_frames):
        frame = anim.render_pillow_frame(frame_num=i)  # PIL Image（RGBA）
        if frame is None:
            continue
        rgba_frames.append(frame)

    if not rgba_frames:
        return

    # 找到所有帧中非透明像素的联合边界框
    min_left, min_top = float("inf"), float("inf")
    max_right, max_bottom = 0, 0
    for frame in rgba_frames:
        bbox = frame.getbbox()  # (left, top, right, bottom) 非零区域
        if bbox:
            min_left = min(min_left, bbox[0])
            min_top = min(min_top, bbox[1])
            max_right = max(max_right, bbox[2])
            max_bottom = max(max_bottom, bbox[3])

    if max_right <= min_left or max_bottom <= min_top:
        return

    # 加少量 padding，防止贴边
    padding = 4
    w, h = rgba_frames[0].size
    min_left = max(0, min_left - padding)
    min_top = max(0, min_top - padding)
    max_right = min(w, max_right + padding)
    max_bottom = min(h, max_bottom + padding)

    # 裁剪框
    crop_box = (min_left, min_top, max_right, max_bottom)

    # 裁剪 + 贴白色背景
    frames = []
    for frame in rgba_frames:
        cropped = frame.crop(crop_box)
        bg = Image.new("RGBA", cropped.size, (255, 255, 255, 255))
        bg.paste(cropped, mask=cropped.split()[3])
        frames.append(bg.convert("RGB"))

    if frames:
        frames[0].save(
            gif_path,
            save_all=True,
            append_images=frames[1:],
            duration=int(1000 / fps) if fps > 0 else 40,
            loop=0,
            optimize=True,
        )


def _buf_to_jpg(buf: io.BytesIO) -> io.BytesIO:
    """将图像转为 JPG BytesIO（自动裁剪白边 + 透明区域贴白色背景）"""
    buf.seek(0)
    img = Image.open(buf)
    # 处理透明通道：先裁剪白边，再贴白色背景
    if img.mode == "RGBA":
        img = _crop_transparent(img)
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    else:
        img = img.convert("RGB")
    jpg_buf = io.BytesIO()
    img.save(jpg_buf, format="JPEG", quality=95)
    jpg_buf.seek(0)
    return jpg_buf


def _buf_to_cropped_png(buf: io.BytesIO) -> io.BytesIO:
    """将 RGBA 图像裁剪透明区域后输出 PNG BytesIO"""
    buf.seek(0)
    img = Image.open(buf)
    if img.mode == "RGBA":
        img = _crop_transparent(img)
    png_buf = io.BytesIO()
    img.save(png_buf, format="PNG")
    png_buf.seek(0)
    return png_buf


def _find_crop_bounds_from_mask(clip) -> tuple | None:
    """采样多帧 mask，找到非透明区域的联合边界框"""
    if clip.mask is None:
        return None

    min_r, min_c = clip.h, clip.w
    max_r, max_c = 0, 0

    # 采样最多 8 帧，取并集
    n_samples = min(8, max(1, int(clip.fps * clip.duration)))
    for i in range(n_samples):
        t = clip.duration * (i + 0.5) / n_samples
        try:
            mask_frame = clip.mask.get_frame(t)  # (H, W) float 0~1
        except Exception:
            continue
        rows = np.any(mask_frame > 0.01, axis=1)
        cols = np.any(mask_frame > 0.01, axis=0)
        if rows.any():
            r = np.where(rows)[0]
            min_r = min(min_r, int(r[0]))
            max_r = max(max_r, int(r[-1]))
        if cols.any():
            c = np.where(cols)[0]
            min_c = min(min_c, int(c[0]))
            max_c = max(max_c, int(c[-1]))

    if max_r <= min_r or max_c <= min_c:
        return None

    return min_r, min_c, max_r, max_c


def _webm_to_gif(webm_path: str, gif_path: str) -> None:
    """webm → GIF（自动裁剪白边 + 白色背景合成）"""
    clip = VideoFileClip(webm_path, has_mask=True)

    # 尝试找到内容边界并裁剪
    bounds = _find_crop_bounds_from_mask(clip)
    if bounds:
        rmin, cmin, rmax, cmax = bounds
        padding = 4
        rmin = max(0, rmin - padding)
        rmax = min(clip.h - 1, rmax + padding)
        cmin = max(0, cmin - padding)
        cmax = min(clip.w - 1, cmax + padding)

        crop_w = cmax - cmin + 1
        crop_h = rmax - rmin + 1
        bg = ColorClip(size=(crop_w, crop_h), color=(255, 255, 255), duration=clip.duration)
        # MoviePy 2.x: 使用 with_effects + Crop
        cropped_clip = clip.with_effects([Crop(y1=rmin, y2=rmax + 1, x1=cmin, x2=cmax + 1)])
        final = CompositeVideoClip([bg, cropped_clip.with_position("center")])
    else:
        # 找不到内容边界，回退到全尺寸白色背景
        bg = ColorClip(size=clip.size, color=(255, 255, 255), duration=clip.duration)
        final = CompositeVideoClip([bg, clip.with_position("center")])

    final.write_gif(gif_path, fps=15, logger=None)


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """收到贴纸 → 转为常见格式发送"""
    message = update.message
    sticker = message.sticker

    # 下载贴纸到内存
    file = await context.bot.get_file(sticker.file_id)
    buf = io.BytesIO()
    await file.download_to_memory(out=buf)
    buf.seek(0)

    # ===== 静态贴纸 → PNG + JPG（自动裁剪白边）=====
    if not sticker.is_animated and not sticker.is_video:
        # 发送裁剪后的 PNG
        png_buf = _buf_to_cropped_png(buf)
        await message.reply_document(document=png_buf, filename="sticker.png")
        # 发送裁剪后的 JPG
        jpg_buf = _buf_to_jpg(buf)
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
            _tgs_to_gif(tmp_path, gif_path)

            # 发送 GIF 动图
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

        # 发送 TGS 源文件
        buf.seek(0)
        await message.reply_document(document=buf, filename="sticker.tgs")
        buf.close()
        return

    # ===== 视频贴纸（webm）→ webm + GIF =====
    # 发送原始 webm 文件
    buf.name = "sticker.webm"
    await message.reply_document(document=buf, filename="sticker.webm")

    # 转为 GIF（白色背景）
    buf.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
        tmp.write(buf.read())
        tmp_path = tmp.name
    try:
        gif_path = tmp_path.replace(".webm", ".gif")
        _webm_to_gif(tmp_path, gif_path)

        # 发送 GIF 动图
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

        # StickerSet 没有 is_animated/is_video，用第一个贴纸判断类型
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
                        # 静态贴纸 → 裁剪白边后的 PNG + JPG
                        stk_buf.seek(0)
                        img = Image.open(stk_buf)
                        img = _crop_transparent(img) if img.mode == "RGBA" else img
                        png_buf = io.BytesIO()
                        img.save(png_buf, format="PNG")
                        zf.writestr(f"{pack_name}/{i:03d}.png", png_buf.getvalue())

                        # JPG：贴白色背景
                        if img.mode == "RGBA":
                            bg = Image.new("RGB", img.size, (255, 255, 255))
                            bg.paste(img, mask=img.split()[3])
                            img = bg
                        else:
                            img = img.convert("RGB")
                        jpg_buf = io.BytesIO()
                        img.save(jpg_buf, format="JPEG", quality=95)
                        zf.writestr(f"{pack_name}/{i:03d}.jpg", jpg_buf.getvalue())

                    elif is_animated:
                        # 动画贴纸 → TGS + GIF
                        stk_buf.seek(0)
                        zf.writestr(f"{pack_name}/{i:03d}.tgs", stk_buf.read())

                        try:
                            with tempfile.NamedTemporaryFile(suffix=".tgs", delete=False) as tmp:
                                tmp.write(stk_buf.getvalue())
                                tmp_path = tmp.name
                            try:
                                gif_path = tmp_path.replace(".tgs", ".gif")
                                _tgs_to_gif(tmp_path, gif_path)
                                with open(gif_path, "rb") as f:
                                    zf.writestr(f"{pack_name}/{i:03d}.gif", f.read())
                                if os.path.exists(gif_path):
                                    os.remove(gif_path)
                            finally:
                                if os.path.exists(tmp_path):
                                    os.remove(tmp_path)
                        except Exception:
                            logger.warning("贴纸 %d TGS 转换失败，跳过", i)

                    else:
                        # 视频贴纸 → webm + GIF
                        stk_buf.seek(0)
                        zf.writestr(f"{pack_name}/{i:03d}.webm", stk_buf.read())

                        try:
                            stk_buf.seek(0)
                            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                                tmp.write(stk_buf.read())
                                tmp_path = tmp.name
                            try:
                                gif_path = tmp_path.replace(".webm", ".gif")
                                _webm_to_gif(tmp_path, gif_path)
                                with open(gif_path, "rb") as f:
                                    zf.writestr(f"{pack_name}/{i:03d}.gif", f.read())
                                os.remove(gif_path)
                            finally:
                                os.remove(tmp_path)
                        except Exception:
                            logger.warning("贴纸 %d webm 转 GIF 失败，跳过", i)

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