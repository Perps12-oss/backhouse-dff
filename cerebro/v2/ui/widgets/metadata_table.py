"""Metadata table with async metadata extraction and caching."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from concurrent.futures import Future, ThreadPoolExecutor
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
import tkinter as tk

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
except ImportError:  # pragma: no cover
    CTkFrame = tk.Frame
    CTkLabel = tk.Label

try:
    from PIL import Image
    _PIL = True
except ImportError:  # pragma: no cover
    _PIL = False

from cerebro.v2.core.design_tokens import Spacing, Typography
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme
from cerebro.utils.formatting import format_bytes

logger = logging.getLogger(__name__)

_FIELDS: List[Tuple[str, str]] = [
    ("name", "Name"),
    ("path", "Path"),
    ("size", "Size"),
    ("type", "Type"),
    ("date_taken", "Date Taken"),
    ("resolution", "Resolution"),
    ("dimensions", "Dimensions"),
    ("date_modified", "Date Modified"),
    ("date_created", "Date Created"),
    ("date_accessed", "Date Accessed"),
]

_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".ico",
}

_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306
_META_CACHE_MAX = 256
_META_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="meta-table")
_META_CACHE: "OrderedDict[str, Dict[str, str]]" = OrderedDict()
_META_LOCK = threading.Lock()


def _format_bytes(n: int) -> str:
    return format_bytes(n, decimals=2)


def _format_timestamp(ts: float) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%m/%d/%Y %I:%M:%S %p")
    except (ValueError, OSError):
        return "—"


def _parse_exif_dt(raw: str) -> Optional[str]:
    try:
        dt = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
        return dt.strftime("%m/%d/%Y %I:%M:%S %p")
    except (ValueError, TypeError):
        return None


def _gather_metadata(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {k: "—" for k, _ in _FIELDS}
    if not path or not path.exists():
        return out
    out["name"] = path.name
    out["path"] = str(path.parent)
    try:
        st = path.stat()
        out["size"] = _format_bytes(st.st_size)
        out["date_modified"] = _format_timestamp(st.st_mtime)
        out["date_created"] = _format_timestamp(getattr(st, "st_birthtime", None) or st.st_ctime)
        out["date_accessed"] = _format_timestamp(st.st_atime)
    except OSError as e:
        logger.debug("stat failed for %s: %s", path, e)

    ext = path.suffix.lower().lstrip(".")
    if ext:
        out["type"] = f"{ext.upper()} File"

    if _PIL and path.suffix.lower() in _IMAGE_EXTENSIONS:
        try:
            with Image.open(path) as im:
                w, h = im.size
                out["dimensions"] = f"{w} x {h}"
                dpi = im.info.get("dpi")
                if dpi and isinstance(dpi, tuple) and len(dpi) >= 2:
                    out["resolution"] = f"{int(dpi[0])} x {int(dpi[1])}"
                exif = None
                getexif = getattr(im, "getexif", None)
                if callable(getexif):
                    try:
                        exif = getexif()
                    except Exception:
                        exif = None
                if exif:
                    raw = exif.get(_EXIF_DATETIME_ORIGINAL) or exif.get(_EXIF_DATETIME)
                    if raw:
                        parsed = _parse_exif_dt(str(raw))
                        if parsed:
                            out["date_taken"] = parsed
        except Exception as e:
            logger.debug("image metadata failed for %s: %s", path, e)
    return out


class MetadataTable(CTkFrame):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        self._value_labels: Dict[str, CTkLabel] = {}
        self._key_labels: Dict[str, CTkLabel] = {}
        self._request_token: int = 0
        self._current_future: Optional[Future] = None
        self._current_path: Optional[Path] = None
        subscribe_to_theme(self, self._apply_theme)
        self._build()

    def _build(self) -> None:
        self.configure(fg_color=theme_color("base.backgroundTertiary"))
        header = CTkFrame(self, height=24, fg_color=theme_color("base.backgroundElevated"))
        header.pack(fill="x")
        header.grid_columnconfigure(0, weight=1, uniform="meta")
        header.grid_columnconfigure(1, weight=2, uniform="meta")
        CTkLabel(header, text="Name", font=Typography.FONT_XS, text_color=theme_color("base.foregroundSecondary"), anchor="w").grid(row=0, column=0, sticky="ew", padx=Spacing.SM, pady=4)
        CTkLabel(header, text="Description", font=Typography.FONT_XS, text_color=theme_color("base.foregroundSecondary"), anchor="w").grid(row=0, column=1, sticky="ew", padx=Spacing.SM, pady=4)
        body = CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=2, pady=(2, Spacing.XS))
        body.grid_columnconfigure(0, weight=1, uniform="meta")
        body.grid_columnconfigure(1, weight=2, uniform="meta")
        for i, (key, label) in enumerate(_FIELDS):
            k = CTkLabel(body, text=label, font=Typography.FONT_XS, text_color=theme_color("base.foregroundMuted"), anchor="w")
            k.grid(row=i, column=0, sticky="ew", padx=(Spacing.SM, Spacing.XS), pady=2)
            self._key_labels[key] = k
            v = CTkLabel(body, text="—", font=Typography.FONT_XS, text_color=theme_color("base.foreground"), anchor="w", wraplength=200, justify="left")
            v.grid(row=i, column=1, sticky="ew", padx=(Spacing.XS, Spacing.SM), pady=2)
            self._value_labels[key] = v

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("base.backgroundTertiary"))
            for lbl in self._key_labels.values():
                lbl.configure(text_color=theme_color("base.foregroundMuted"))
            for lbl in self._value_labels.values():
                lbl.configure(text_color=theme_color("base.foreground"))
        except tk.TclError:
            pass

    def load(self, path: Optional[Any]) -> None:
        if not path:
            self.clear()
            return
        try:
            p = Path(path) if not isinstance(path, Path) else path
        except (TypeError, ValueError):
            self.clear()
            return
        self._current_path = p
        token = self._request_token = self._request_token + 1

        cached = self._cache_get(p)
        if cached is not None:
            self._apply_metadata(cached, token)
            return

        self._set_loading()
        self._current_future = _META_EXECUTOR.submit(_gather_metadata, p)
        self.after(0, lambda: self._poll_metadata_future(token, p))

    def clear(self) -> None:
        self._current_path = None
        self._request_token += 1
        for lbl in self._value_labels.values():
            try:
                lbl.configure(text="—")
            except tk.TclError:
                pass

    def _set_loading(self) -> None:
        for key, lbl in self._value_labels.items():
            text = "Loading..." if key in {"name", "path", "size", "type"} else "—"
            try:
                lbl.configure(text=text)
            except tk.TclError:
                pass

    def _poll_metadata_future(self, token: int, path: Path) -> None:
        fut = self._current_future
        if fut is None:
            return
        if token != self._request_token:
            return
        if not fut.done():
            self.after(40, lambda: self._poll_metadata_future(token, path))
            return
        try:
            meta = fut.result()
        except Exception as e:
            logger.debug("metadata background task failed for %s: %s", path, e)
            meta = {k: "—" for k, _ in _FIELDS}
        self._cache_put(path, meta)
        self._apply_metadata(meta, token)

    def _apply_metadata(self, meta: Dict[str, str], token: int) -> None:
        if token != self._request_token:
            return
        for key, value in meta.items():
            lbl = self._value_labels.get(key)
            if lbl is not None:
                try:
                    lbl.configure(text=value or "—")
                except tk.TclError:
                    pass

    def _cache_get(self, path: Path) -> Optional[Dict[str, str]]:
        key = str(path.resolve())
        with _META_LOCK:
            value = _META_CACHE.get(key)
            if value is None:
                return None
            _META_CACHE.move_to_end(key)
            return dict(value)

    def _cache_put(self, path: Path, meta: Dict[str, str]) -> None:
        key = str(path.resolve())
        with _META_LOCK:
            _META_CACHE[key] = dict(meta)
            _META_CACHE.move_to_end(key)
            while len(_META_CACHE) > _META_CACHE_MAX:
                _META_CACHE.popitem(last=False)
