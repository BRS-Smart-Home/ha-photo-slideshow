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
    # frame rate is passed through untouched (no dropped or duplicated frames); only the size (and quality) is reduced
    return [
        ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(src), "-t", str(seconds), "-an",
        "-vf", f"scale=-2:'min({height},ih)'", "-fps_mode", "passthrough",
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst),
    ]


def _copy_cmd(ffmpeg: str, src: Path, dst: Path, seconds: int) -> list[str]:
    """No re-encode at all: same video stream, muted, cut at `seconds`, moved into an MP4 container."""
    return [
        ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(src), "-t", str(seconds), "-an",
        "-c:v", "copy", "-movflags", "+faststart", str(dst),
    ]


async def _is_h264(ffmpeg: str, src: Path) -> bool:
    """True when the first video stream is 8-bit H.264 (plays everywhere, can be copied as is)."""
    ffprobe = shutil.which("ffprobe") or str(Path(ffmpeg).with_name("ffprobe"))
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt",
            "-of", "csv=p=0", str(src), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 30)
    except (OSError, asyncio.TimeoutError):
        return False
    parts = out.decode(errors="replace").strip().split(",")
    return parts[0] == "h264" and (len(parts) < 2 or parts[1] in ("yuv420p", "yuvj420p"))


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


async def convert_video(src: Path, dst: Path, max_seconds: int, max_mb: int, height: int = 720, timeout: int = 900) -> None:
    """Muted MP4 cut at `max_seconds`. H.264 sources are copied without re-encoding; only when that is above `max_mb`
    (or the codec is not H.264, e.g. HEVC) is the video re-encoded, with the original frame rate, in smaller steps."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not available in Home Assistant")
    limit = max_mb * 1024 * 1024
    if await _is_h264(ffmpeg, src):
        try:
            await _run(_copy_cmd(ffmpeg, src, dst, max_seconds), timeout)
            if dst.stat().st_size <= limit:
                return
        except RuntimeError:
            pass                                                     # fall through to a real conversion
    # chosen resolution first, then smaller ones when the file is still above the size limit
    steps = [(height, 24)]
    if height > 720:
        steps.append((720, 27))
    steps.append((min(height, 480), 32))
    for height, crf in steps:
        await _run(_ffmpeg_cmd(ffmpeg, src, dst, max_seconds, height, crf), timeout)
        if dst.stat().st_size <= limit:
            return
    raise RuntimeError(f"converted video is still larger than {max_mb} MB")
