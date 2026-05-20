"""LRU preview cache: path → base64 JPEG (images, text snippets, video frames)."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import logging
import os
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path
from functools import partial
from typing import Awaitable, Callable, Iterable, Optional

from cerebro.v2.ui.flet_app.media_preview import preview_kind_for_path

_log = logging.getLogger(__name__)

_MAX_CACHE = 384
_MAX_EDGE = 112
_JPEG_QUALITY = 82
_MAX_PREVIEW_BYTES = int(os.environ.get("CEREBRO_PREVIEW_MAX_BYTES", str(50 * 1024 * 1024)))

# Progressive preview tiers (same LRU; keys prefixed so eviction stays coherent).
TINY_BROWSE_EDGE = 32
TINY_INSPECT_EDGE = 128
_TINY_JPEG_QUALITY_BROWSE = 48
_TINY_JPEG_QUALITY_INSPECT = 55

# Side-by-side compare view: much larger decode than grid thumbnails.
_COMPARE_MAX_EDGE = 2048
_COMPARE_JPEG_QUALITY = 90

_IMAGE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".ico", ".heic", ".heif",
}


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES


def is_previewable_path(path: Path) -> bool:
    """True when a JPEG preview can be attempted (image, text render, or video frame)."""
    return preview_kind_for_path(path) != "icon"


def _normalize_for_safe_convert(im):
    """Avoid Pillow warning for palette transparency stored as bytes."""
    try:
        transparency = im.info.get("transparency")
    except Exception:
        transparency = None
    if im.mode == "P" and isinstance(transparency, (bytes, bytearray)):
        return im.convert("RGBA")
    return im


def _pil_to_jpeg_b64(im, max_edge: int, quality: int) -> str:
    from PIL import Image

    im = _normalize_for_safe_convert(im)
    im = im.convert("RGB")
    im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _decode_image_file(path: Path, max_edge: int, quality: int) -> Optional[str]:
    from PIL import Image

    with Image.open(path) as im:
        return _pil_to_jpeg_b64(im, max_edge, quality)


def _decode_text_file(path: Path, max_edge: int, quality: int) -> Optional[str]:
    try:
        from PIL import Image, ImageDraw, ImageFont

        raw = path.read_bytes()[:8192]
        text = raw.decode("utf-8", errors="replace")
        lines = [ln.rstrip() for ln in text.splitlines()[:16] if ln.strip() or ln == ""]
        if not lines:
            lines = ["(empty)"]
        w = h = max(32, int(max_edge))
        im = Image.new("RGB", (w, h), (22, 27, 34))
        draw = ImageDraw.Draw(im)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        y = 6
        line_h = max(10, h // 14)
        max_chars = max(8, w // 7)
        for line in lines:
            snippet = line[:max_chars]
            draw.text((6, y), snippet, fill=(210, 218, 226), font=font)
            y += line_h
            if y >= h - line_h:
                break
        return _pil_to_jpeg_b64(im, max_edge, quality)
    except Exception:
        _log.debug("text thumbnail failed for %s", path, exc_info=True)
        return None


def _decode_video_file(path: Path, max_edge: int, quality: int) -> Optional[str]:
    if not shutil.which("ffmpeg"):
        return None
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        "00:00:01",
        "-i",
        str(path),
        "-vframes",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=10, check=False)
        if proc.returncode != 0 or not proc.stdout:
            return None
        from PIL import Image

        with Image.open(io.BytesIO(proc.stdout)) as im:
            return _pil_to_jpeg_b64(im, max_edge, quality)
    except Exception:
        _log.debug("video thumbnail failed for %s", path, exc_info=True)
        return None


def decode_preview_jpeg_b64(path: Path, max_edge: int, quality: int) -> Optional[str]:
    """Decode image, text snippet, or video frame to a JPEG base64 string."""
    p = Path(path)
    if not p.is_file():
        return None
    kind = preview_kind_for_path(p)
    try:
        if kind == "image":
            return _decode_image_file(p, max_edge, quality)
        if kind == "text":
            return _decode_text_file(p, max_edge, quality)
        if kind == "video":
            return _decode_video_file(p, max_edge, quality)
    except Exception:
        _log.debug("preview decode failed for %s kind=%s", path, kind, exc_info=True)
    return None


class ThumbnailCache:
    """Thread-safe enough for UI: single-threaded Flet main; worker may call get()."""

    def __init__(self, max_entries: int = _MAX_CACHE) -> None:
        self._max = max_entries
        self._data: OrderedDict[str, Optional[str]] = OrderedDict()
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="thumb-cache")

    def get_base64(self, path: Path) -> Optional[str]:
        """Return base64-encoded JPEG or None if not an image / unreadable."""
        key = str(path.resolve())
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]

        p = Path(path)
        if not p.is_file() or not is_previewable_path(p):
            self._remember(key, None)
            return None
        try:
            if p.stat().st_size > _MAX_PREVIEW_BYTES:
                self._remember(key, None)
                return None
        except OSError:
            self._remember(key, None)
            return None

        b64 = decode_preview_jpeg_b64(p, _MAX_EDGE, _JPEG_QUALITY)
        if b64 is None:
            self._remember(key, None)
            return None

        self._remember(key, b64)
        return b64

    def get_base64_sized(self, path: Path, max_edge: int) -> Optional[str]:
        """Decode JPEG thumbnail capped to ``max_edge`` (separate cache entry per size tier)."""
        me = max(64, min(512, int(max_edge)))
        p = Path(path)
        key = f"{p.resolve()}|e{me}"
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]

        if not p.is_file() or not is_previewable_path(p):
            self._remember(key, None)
            return None

        b64 = decode_preview_jpeg_b64(p, me, _JPEG_QUALITY)
        if b64 is None:
            self._remember(key, None)
            return None

        self._remember(key, b64)
        return b64

    def get_preview_tiny_base64(self, path: Path, edge: int) -> Optional[str]:
        """Very small JPEG for blur-up / placeholder (Browse 32px, Inspect 128px). LRU key ``tiny|edge|path``."""
        p = Path(path)
        me = max(16, min(512, int(edge)))
        try:
            key = f"tiny|{me}|{p.resolve()}"
        except OSError:
            key = f"tiny|{me}|{p}"
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]

        if not p.is_file() or not is_previewable_path(p):
            self._remember(key, None)
            return None

        q = _TINY_JPEG_QUALITY_INSPECT if me >= 64 else _TINY_JPEG_QUALITY_BROWSE
        b64 = decode_preview_jpeg_b64(p, me, q)
        if b64 is None:
            self._remember(key, None)
            return None

        self._remember(key, b64)
        return b64

    def get_compare_preview_base64(self, path: Path) -> Optional[str]:
        """High-res JPEG preview for compare mode (separate cache key from grid thumbnails)."""
        p = Path(path)
        try:
            key = f"cmp:{p.resolve()}"
        except OSError:
            key = f"cmp:{p}"
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]

        if not p.is_file() or not is_previewable_path(p):
            self._remember(key, None)
            return None

        b64 = decode_preview_jpeg_b64(p, _COMPARE_MAX_EDGE, _COMPARE_JPEG_QUALITY)
        if b64 is None:
            self._remember(key, None)
            return None

        self._remember(key, b64)
        return b64

    def _remember(self, key: str, value: Optional[str]) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def _load_one(self, path: Path) -> tuple[Path, Optional[str]]:
        return path, self.get_base64(path)

    def _load_one_sized(self, path: Path, max_edge: int) -> tuple[Path, Optional[str]]:
        return path, self.get_base64_sized(path, max_edge)

    async def load_batch_async(
        self,
        paths: Iterable[Path],
        on_thumbnail_ready: Callable[[Path, Optional[str]], Awaitable[None] | None],
        *,
        max_edge: Optional[int] = None,
    ) -> None:
        """Load thumbnails in parallel and call callback as each one completes.

        When ``max_edge`` is set, decode at that pixel cap (Review grid large tiles).
        When omitted, use the default small grid edge (``_MAX_EDGE``).
        """
        loop = asyncio.get_running_loop()
        if max_edge is None:
            worker = self._load_one
            tasks = [
                asyncio.ensure_future(loop.run_in_executor(self._pool, worker, Path(p)))
                for p in paths
                if is_previewable_path(Path(p))
            ]
        else:
            me = max(64, min(512, int(max_edge)))
            worker = partial(self._load_one_sized, max_edge=me)
            tasks = [
                asyncio.ensure_future(loop.run_in_executor(self._pool, worker, Path(p)))
                for p in paths
                if is_previewable_path(Path(p))
            ]
        for done in asyncio.as_completed(tasks):
            try:
                p, b64 = await done
            except Exception:
                _log.debug("thumbnail worker raised", exc_info=True)
                continue
            out = on_thumbnail_ready(p, b64)
            if asyncio.iscoroutine(out):
                await out


_DEFAULT_CACHE: Optional[ThumbnailCache] = None


def get_thumbnail_cache() -> ThumbnailCache:
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        _DEFAULT_CACHE = ThumbnailCache()
    return _DEFAULT_CACHE


def shutdown_thumbnail_cache(wait: bool = False) -> None:
    """Release the global thumbnail worker pool on app exit."""
    global _DEFAULT_CACHE
    cache = _DEFAULT_CACHE
    _DEFAULT_CACHE = None
    if cache is None:
        return
    try:
        cache._pool.shutdown(wait=wait, cancel_futures=True)
    except Exception:
        _log.debug("thumbnail pool shutdown failed", exc_info=True)
