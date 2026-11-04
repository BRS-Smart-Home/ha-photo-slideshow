"""Picture and video conversion for the slideshow (Pillow and ffmpeg). Needs Pillow; HEIC needs pillow-heif."""
from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path


def convert_photo(src: Path, dst: Path, max_px: int) -> None:
    """Write `dst` from `src` at the original size. JPG / PNG that are small enough are copied untouched; HEIC, TIFF, BMP and GIF
    become JPG; a picture larger than `max_px` on its long side is scaled down (protects the display, not a size limit)."""
    from PIL import Image, ImageOps

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:                                      # HEIC files will then fail one by one and be replaced
        pass

    with Image.open(src) as im:
        fmt = (im.format or "").upper()
        want_png = dst.suffix.lower() == ".png"
        same_kind = (fmt == "PNG") if want_png else (fmt == "JPEG")
        if same_kind and max(im.size) <= max_px:
            shutil.copyfile(src, dst)
            return
        im = ImageOps.exif_transpose(im)
        if max(im.size) > max_px:
            im.thumbnail((max_px, max_px), Image.LANCZOS)
        if want_png:
            im.save(dst, "PNG", optimize=True)
        else:
            if im.mode != "RGB":
                im = im.convert("RGB")
            im.save(dst, "JPEG", quality=90, optimize=True)


def _ffmpeg_cmd(ffmpeg: str, src: Path, dst: Path, seconds: int, height: int, crf: int) -> list[str]:
    return [
        ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(src), "-t", str(seconds), "-an",
        "-vf", f"scale=-2:'min({height},ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst),
    ]


async def _run(cmd: list[str], timeout: int) -> None:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise RuntimeError(f"ffmpeg took longer than {timeout} s") from None
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (err or b"").decode(errors="replace").strip()[-200:])


async def convert_video(src: Path, dst: Path, max_seconds: int, max_mb: int, timeout: int = 900) -> None:
    """Small muted MP4 (at most 720p), cut at `max_seconds`; a second, smaller try when the file is above `max_mb`."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not available in Home Assistant")
    limit = max_mb * 1024 * 1024
    for height, crf in ((720, 28), (480, 34)):
        await _run(_ffmpeg_cmd(ffmpeg, src, dst, max_seconds, height, crf), timeout)
        if dst.stat().st_size <= limit:
            return
    raise RuntimeError(f"converted video is still larger than {max_mb} MB")
