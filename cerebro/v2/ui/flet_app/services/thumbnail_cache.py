"""LRU thumbnail cache: image path → base64 JPEG for Flet ft.Image(src_base64=...)."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import logging
from collections import OrderedDict
from pathlib import Path
from functools import partial
from typing import Awaitable, Callable, Iterable, Optional

_log = logging.getLogger(__name__)

_MAX_CACHE = 384
_MAX_EDGE = 112
_JPEG_QUALITY = 82

# Side-by-side compare view: much larger decode than grid thumbnails.
_COMPARE_MAX_EDGE = 2048
_COMPARE_JPEG_QUALITY = 90

_IMAGE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".ico", ".heic", ".heif",
}


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES


def _normalize_for_safe_convert(im):
    """Avoid Pillow warning for palette transparency stored as bytes."""
    try:
        transparency = im.info.get("transparency")
    except Exception:
        transparency = None
    if im.mode == "P" and isinstance(transparency, (bytes, bytearray)):
        return im.convert("RGBA")
    return im


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
        if not p.is_file() or not is_image_path(p):
            self._remember(key, None)
            return None

        try:
            from PIL import Image

            with Image.open(p) as im:
                im = _normalize_for_safe_convert(im)
                im = im.convert("RGB")
                im.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            _log.debug("thumbnail failed for %s", path, exc_info=True)
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

        if not p.is_file() or not is_image_path(p):
            self._remember(key, None)
            return None

        try:
            from PIL import Image

            with Image.open(p) as im:
                im = _normalize_for_safe_convert(im)
                im = im.convert("RGB")
                im.thumbnail((me, me), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            _log.debug("thumbnail failed for %s (edge=%s)", path, me, exc_info=True)
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

        if not p.is_file() or not is_image_path(p):
            self._remember(key, None)
            return None

        try:
            from PIL import Image

            with Image.open(p) as im:
                im = _normalize_for_safe_convert(im)
                im = im.convert("RGB")
                im.thumbnail((_COMPARE_MAX_EDGE, _COMPARE_MAX_EDGE), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=_COMPARE_JPEG_QUALITY, optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            _log.debug("compare preview failed for %s", path, exc_info=True)
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
                if is_image_path(Path(p))
            ]
        else:
            me = max(64, min(512, int(max_edge)))
            worker = partial(self._load_one_sized, max_edge=me)
            tasks = [
                asyncio.ensure_future(loop.run_in_executor(self._pool, worker, Path(p)))
                for p in paths
                if is_image_path(Path(p))
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
