"""LRU thumbnail cache: image path → base64 JPEG for Flet ft.Image(src_base64=...)."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional

_log = logging.getLogger(__name__)

_MAX_CACHE = 256
_MAX_EDGE = 112
_JPEG_QUALITY = 82

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

    def _remember(self, key: str, value: Optional[str]) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def _load_one(self, path: Path) -> tuple[Path, Optional[str]]:
        return path, self.get_base64(path)

    async def load_batch_async(
        self,
        paths: Iterable[Path],
        on_thumbnail_ready: Callable[[Path, Optional[str]], Awaitable[None] | None],
    ) -> None:
        """Load thumbnails in parallel and call callback as each one completes."""
        loop = asyncio.get_event_loop()
        tasks = [
            asyncio.ensure_future(loop.run_in_executor(self._pool, self._load_one, Path(p)))
            for p in paths
            if is_image_path(Path(p))
        ]
        for done in asyncio.as_completed(tasks):
            try:
                p, b64 = await done
            except Exception:  # pragma: no cover - defensive
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
