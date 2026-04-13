"""贴纸格式转换工具"""
import io
import os
import tempfile

import numpy as np
from PIL import Image
from moviepy import VideoFileClip, ColorClip, CompositeVideoClip
from moviepy.video.fx import Crop
from rlottie_python import LottieAnimation


def crop_transparent(img: Image.Image, padding: int = 1) -> Image.Image:
    """裁剪图片中的透明区域，只保留内容部分（带少量 padding）"""
    if img.mode != "RGBA":
        return img
    bbox = img.getbbox()
    if not bbox:
        return img
    bbox = (
        max(0, bbox[0] - padding),
        max(0, bbox[1] - padding),
        min(img.width, bbox[2] + padding),
        min(img.height, bbox[3] + padding),
    )
    return img.crop(bbox)


def tgs_to_gif(tgs_path: str, gif_path: str) -> None:
    """TGS → GIF（逐帧提取 + 自动裁剪白边 + 白色背景）"""
    anim = LottieAnimation.from_tgs(tgs_path)
    total_frames = anim.lottie_animation_get_totalframe()
    fps = anim.lottie_animation_get_framerate()

    rgba_frames = []
    for i in range(total_frames):
        frame = anim.render_pillow_frame(frame_num=i)
        if frame is None:
            continue
        rgba_frames.append(frame)

    if not rgba_frames:
        return

    # 所有帧中非透明像素的联合边界框
    min_left, min_top = float("inf"), float("inf")
    max_right, max_bottom = 0, 0
    for frame in rgba_frames:
        bbox = frame.getbbox()
        if bbox:
            min_left = min(min_left, bbox[0])
            min_top = min(min_top, bbox[1])
            max_right = max(max_right, bbox[2])
            max_bottom = max(max_bottom, bbox[3])

    if max_right <= min_left or max_bottom <= min_top:
        return

    padding = 4
    w, h = rgba_frames[0].size
    crop_box = (
        max(0, min_left - padding),
        max(0, min_top - padding),
        min(w, max_right + padding),
        min(h, max_bottom + padding),
    )

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


def buf_to_jpg(buf: io.BytesIO) -> io.BytesIO:
    """将图像转为 JPG BytesIO（自动裁剪白边 + 透明区域贴白色背景）"""
    buf.seek(0)
    img = Image.open(buf)
    if img.mode == "RGBA":
        img = crop_transparent(img)
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    else:
        img = img.convert("RGB")
    jpg_buf = io.BytesIO()
    img.save(jpg_buf, format="JPEG", quality=95)
    jpg_buf.seek(0)
    return jpg_buf


def buf_to_cropped_png(buf: io.BytesIO) -> io.BytesIO:
    """将 RGBA 图像裁剪透明区域后输出 PNG BytesIO"""
    buf.seek(0)
    img = Image.open(buf)
    if img.mode == "RGBA":
        img = crop_transparent(img)
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

    n_samples = min(8, max(1, int(clip.fps * clip.duration)))
    for i in range(n_samples):
        t = clip.duration * (i + 0.5) / n_samples
        try:
            mask_frame = clip.mask.get_frame(t)
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


def webm_to_gif(webm_path: str, gif_path: str) -> None:
    """webm → GIF（自动裁剪白边 + 白色背景合成）"""
    clip = VideoFileClip(webm_path, has_mask=True)

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
        cropped_clip = clip.with_effects([Crop(y1=rmin, y2=rmax + 1, x1=cmin, x2=cmax + 1)])
        final = CompositeVideoClip([bg, cropped_clip.with_position("center")])
    else:
        bg = ColorClip(size=clip.size, color=(255, 255, 255), duration=clip.duration)
        final = CompositeVideoClip([bg, clip.with_position("center")])

    final.write_gif(gif_path, fps=15, logger=None)