"""
VirtualThumbGrid — canvas-based virtualized thumbnail grid for ResultsPage.

Sibling of ``VirtualFileGrid`` (list view, Phase 5): same scroll-model
discipline (single source of truth for ``_scroll_y``, scrollbar sync via
``yscrollcommand``, unified ``yview()`` entry point, pixel-level clamp of
the native Canvas scrollregion) but laid out as a 2-D tile grid instead
of a row stack.

Why new, not a reuse of ``cerebro.v2.ui.widgets.thumbnail_grid``:
  - The legacy ThumbnailGrid uses CTkScrollableFrame + per-card CTkFrames
    (one widget per tile). That breaks down at 4k+ tiles — the widget
    tree becomes the bottleneck that Phase 5 just solved for the list.
  - Canvas-item rendering keeps draw cost proportional to *visible* tiles
    (~20–40) regardless of dataset size.
  - Async decode / LRU cache pattern *is* ported from thumbnail_grid so
    we don't reinvent the good bits.

Public API (mirrors VirtualFileGrid where sensible):
  - load(rows: List[Dict]) — same row-dict shape as VirtualFileGrid.
  - get_checked_rows() / get_checked_count()
  - sort_by(col: str)
  - ``<<CheckChanged>>`` virtual event when the check set changes.
  - ``on_open_file(row: Dict)`` callback on double-click (replaces
    VirtualFileGrid's ``on_open_group`` to give the consumer access to
    the specific *file* the user picked, not just its group).
  - apply_theme(t: dict)
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

_log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False
    Image = None       # type: ignore[assignment]
    ImageOps = None    # type: ignore[assignment]
    ImageTk = None     # type: ignore[assignment]


# ---------------------------------------------------------------------------
# File-type classification (matches results_page tokens; kept local to avoid
# a circular import since this widget is imported *by* results_page).
# ---------------------------------------------------------------------------
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff",
              ".tif", ".heic", ".heif", ".cr2", ".cr3", ".nef", ".arw", ".dng"}
_VIDEO_EXT = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v",
              ".mpg", ".mpeg"}
_AUDIO_EXT = {".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma",
              ".opus", ".aiff", ".ape"}
_DOC_EXT   = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
              ".txt", ".odt", ".rtf"}
_ARCH_EXT  = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"}

_TYPE_GLYPH: Dict[str, str] = {
    "image":    "\U0001F5BC",   # framed picture
    "video":    "\U0001F3AC",   # clapper board
    "audio":    "\U0001F3B5",   # musical note
    "document": "\U0001F4C4",   # page facing up
    "archive":  "\U0001F4E6",   # package
    "other":    "\U0001F4CE",   # paperclip
}

_TYPE_TINT: Dict[str, str] = {
    "image":    "#2E75B6",
    "video":    "#9B59B6",
    "audio":    "#E67E22",
    "document": "#16A085",
    "archive":  "#7F8C8D",
    "other":    "#95A5A6",
}


def _classify(ext: str) -> str:
    e = (ext or "").lower()
    if e in _IMAGE_EXT:  return "image"
    if e in _VIDEO_EXT:  return "video"
    if e in _AUDIO_EXT:  return "audio"
    if e in _DOC_EXT:    return "document"
    if e in _ARCH_EXT:   return "archive"
    return "other"


def is_image_row(row: Dict) -> bool:
    """Return True if the row's file is an image type.

    Helper exported so the ResultsPage double-click handler can route
    image double-clicks to the side-by-side comparison view and
    non-image double-clicks to the Review page.
    """
    return _classify(row.get("extension", "")) == "image"


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
_TILE_W    = 140
_THUMB_H   = 140
_LABEL_H   = 32                 # filename + size line
_TILE_H    = _THUMB_H + _LABEL_H
_GAP       = 12
_EDGE_PAD  = 14
_BADGE_R   = 13                 # count-badge radius


# ---------------------------------------------------------------------------
# VirtualThumbGrid
# ---------------------------------------------------------------------------
class VirtualThumbGrid(tk.Canvas):
    """Canvas-virtualized thumbnail grid.

    Draws only the tiles whose row-band intersects the viewport.
    Thumbnails decode asynchronously on a shared ThreadPoolExecutor
    and cache in an LRU keyed on (path, mtime, size) — evicted at
    ``_THUMB_CACHE_CAP`` entries.

    Scroll model is identical to VirtualFileGrid (Phase 5 contract):
    ``_scroll_y`` is the single source of truth; ``yview()`` is the
    single entry point for scrollbar + wheel + keyboard input;
    ``yscrollcommand`` is fired from ``_render`` so the thumb tracks
    exactly with what's on screen.
    """

    ROW_H = _TILE_H + _GAP   # "row" here = one row of tiles
    TILE_W = _TILE_W
    TILE_H = _TILE_H

    _THUMB_CACHE_CAP = 180

    def __init__(self,
                 parent,
                 on_open_file: Optional[Callable[[Dict], None]] = None,
                 **kw) -> None:
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bg", "#FFFFFF")
        kw.setdefault("bd", 0)
        super().__init__(parent, **kw)

        self._on_open_file = on_open_file
        self._rows: List[Dict] = []
        self._group_counts: Dict[int, int] = {}
        self._selected_idx: Optional[int] = None
        self._checked: Set[int] = set()
        self._sort_col: str = ""
        self._sort_asc: bool = True

        # Scroll state (mirrors VirtualFileGrid semantics)
        self._scroll_y: int  = 0
        self._total_h:  int  = 0
        self._yscrollcommand: Optional[Callable[[str, str], None]] = None

        # Theme tokens
        self._t: Dict[str, str] = {
            "bg": "#FFFFFF", "bg2": "#F8F8F8", "border": "#E0E0E0",
            "fg": "#222222", "fg_muted": "#888888",
            "sel_bg": "#1E3A8A", "sel_fg": "#FFFFFF",
            "badge": "#E74C3C", "badge_fg": "#FFFFFF",
            "tile": "#FAFAFA", "tile_border": "#E8E8E8",
        }

        # ── Async decode plumbing (ported from ThumbnailGrid) ────────
        self._decode_executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="vthumb-decode")
        self._decode_semaphore = threading.Semaphore(4)
        self._decode_futures: Dict[int, Future] = {}
        self._thumb_cache: "OrderedDict[Tuple[str, float, int], Any]" = \
            OrderedDict()
        # Images we've converted to ImageTk.PhotoImage; held by path so
        # Tk doesn't garbage-collect while they're still drawn.
        self._photo_images: Dict[Tuple[str, float, int], Any] = {}

        # ── Bindings ─────────────────────────────────────────────────
        self.bind("<Configure>",     self._on_configure)
        self.bind("<Button-1>",      self._on_click)
        self.bind("<Double-Button-1>", self._on_dbl)
        self.bind("<space>",         self._on_space)
        self.bind("<MouseWheel>",    self._on_scroll)
        self.bind("<Button-4>",      self._on_scroll_linux)
        self.bind("<Button-5>",      self._on_scroll_linux)
        self.bind("<Prior>",         lambda _e: self._scroll_by_page(-1))
        self.bind("<Next>",          lambda _e: self._scroll_by_page(1))
        self.bind("<Home>",          self._on_home)
        self.bind("<End>",           self._on_end)
        self.bind("<Up>",            lambda _e: self._move_sel_row(-1))
        self.bind("<Down>",          lambda _e: self._move_sel_row(1))
        self.bind("<Left>",          lambda _e: self._move_sel(-1))
        self.bind("<Right>",         lambda _e: self._move_sel(1))

    # ──────────────────────────────────────────────────────────────
    # Scrollbar plumbing — same pattern as VirtualFileGrid.
    # ``ttk.Scrollbar`` wires itself via ``yscrollcommand=<callable>``
    # and then pushes commands back through ``yview(*args)``. We
    # intercept both so our single-source-of-truth ``_scroll_y`` stays
    # authoritative and the native Canvas scrollregion never drifts.

    def configure(self, cnf=None, **kw):  # type: ignore[override]
        if "yscrollcommand" in kw:
            self._yscrollcommand = kw.pop("yscrollcommand")
        if cnf and isinstance(cnf, dict) and "yscrollcommand" in cnf:
            self._yscrollcommand = cnf.pop("yscrollcommand")
        return super().configure(cnf, **kw) if cnf else super().configure(**kw)

    config = configure

    def yview(self, *args):  # type: ignore[override]
        if not args:
            return self._yview_fractions()
        cmd = args[0]
        if cmd == "moveto":
            frac = float(args[1])
            self._scroll_to(int(frac * max(0, self._total_h - self._viewport_h())))
        elif cmd == "scroll":
            n = int(args[1])
            kind = args[2] if len(args) > 2 else "units"
            if kind.startswith("page"):
                self._scroll_by_page(n)
            else:
                self._scroll_by(n * self.ROW_H)
        return ""

    def _yview_fractions(self) -> Tuple[float, float]:
        vh = self._viewport_h()
        if self._total_h <= 0:
            return (0.0, 1.0)
        top = self._scroll_y / self._total_h
        bot = min(1.0, (self._scroll_y + vh) / self._total_h)
        return (top, bot)

    def _scroll_to(self, y_px: int) -> None:
        max_y = max(0, self._total_h - self._viewport_h())
        self._scroll_y = max(0, min(max_y, y_px))
        self._render()

    def _scroll_by(self, delta_px: int) -> None:
        self._scroll_to(self._scroll_y + delta_px)

    def _scroll_by_page(self, pages: int) -> None:
        self._scroll_by(pages * max(1, self._viewport_h() - self.ROW_H))

    def _viewport_h(self) -> int:
        return max(1, int(self.winfo_height()))

    def _viewport_w(self) -> int:
        return max(1, int(self.winfo_width()))

    def _cols(self) -> int:
        w = self._viewport_w()
        avail = w - 2 * _EDGE_PAD + _GAP
        return max(1, avail // (_TILE_W + _GAP))

    def _tile_rect(self, idx: int) -> Tuple[int, int, int, int]:
        """Return the (x0, y0, x1, y1) rect for tile ``idx`` in
        document-space (not viewport-space). Caller subtracts
        ``_scroll_y`` from y-coords before drawing."""
        cols = self._cols()
        r, c = divmod(idx, cols)
        x0 = _EDGE_PAD + c * (_TILE_W + _GAP)
        y0 = _EDGE_PAD + r * (_TILE_H + _GAP)
        return (x0, y0, x0 + _TILE_W, y0 + _TILE_H)

    # ──────────────────────────────────────────────────────────────
    # Public API

    def load(self, rows: List[Dict]) -> None:
        self._rows = rows
        self._recount_groups()
        self._selected_idx = 0 if rows else None
        self._checked.clear()
        self._scroll_y = 0
        # Cancel pending decodes from the previous dataset — they'd
        # just pollute the cache with stale entries. Futures in flight
        # are let to finish; their results land in the cache but are
        # harmless.
        self._decode_futures.clear()
        self._update_total_h()
        self._render()
        self._fire_check_change()

    def get_checked_rows(self) -> List[Dict]:
        return [self._rows[i] for i in sorted(self._checked)
                if 0 <= i < len(self._rows)]

    def get_checked_count(self) -> int:
        return len(self._checked)

    def apply_theme(self, t: dict) -> None:
        self._t.update({
            "bg":          t.get("bg",         self._t["bg"]),
            "bg2":         t.get("bg2",        self._t["bg2"]),
            "border":      t.get("border",     self._t["border"]),
            "fg":          t.get("fg",         self._t["fg"]),
            "fg_muted":    t.get("fg_muted",   self._t["fg_muted"]),
            "sel_bg":      t.get("sel_bg",     self._t["sel_bg"]),
            "sel_fg":      t.get("sel_fg",     self._t["sel_fg"]),
            "badge":       t.get("danger",     self._t["badge"]),
            "tile":        t.get("bg3",        self._t["tile"]),
            "tile_border": t.get("border",     self._t["tile_border"]),
        })
        try:
            self.configure(bg=self._t["bg"])
        except tk.TclError:
            pass
        self._render()

    def sort_by(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        key = {"name":   lambda r: (r.get("name") or "").lower(),
               "size":   lambda r: int(r.get("size", 0) or 0),
               "date":   lambda r: r.get("date") or "",
               "folder": lambda r: (r.get("folder") or "").lower(),
               "path":   lambda r: (r.get("path") or "").lower(),
               }.get(col)
        if not key:
            return
        self._rows.sort(key=key, reverse=not self._sort_asc)
        self._selected_idx = 0 if self._rows else None
        self._scroll_y = 0
        self._render()

    # ──────────────────────────────────────────────────────────────
    # Internals

    def _recount_groups(self) -> None:
        counts: Dict[int, int] = {}
        for r in self._rows:
            gid = int(r.get("group_id", -1))
            counts[gid] = counts.get(gid, 0) + 1
        self._group_counts = counts

    def _update_total_h(self) -> None:
        cols = self._cols()
        n = len(self._rows)
        if n == 0:
            self._total_h = 0
            return
        tile_rows = (n + cols - 1) // cols
        self._total_h = 2 * _EDGE_PAD + tile_rows * _TILE_H + \
                        max(0, tile_rows - 1) * _GAP

    def _visible_range(self) -> Tuple[int, int]:
        """Return (first_idx, last_idx_exclusive) of tiles in viewport."""
        if not self._rows:
            return (0, 0)
        cols = self._cols()
        vh = self._viewport_h()
        first_row = max(0, (self._scroll_y - _EDGE_PAD) // (_TILE_H + _GAP))
        last_row  = (self._scroll_y + vh - _EDGE_PAD) // (_TILE_H + _GAP) + 1
        first = int(first_row) * cols
        last  = min(len(self._rows), (int(last_row) + 1) * cols)
        return (first, last)

    def _on_configure(self, _event=None) -> None:
        self._update_total_h()
        max_y = max(0, self._total_h - self._viewport_h())
        if self._scroll_y > max_y:
            self._scroll_y = max_y
        self._render()

    # ─── Rendering ──────────────────────────────────────────────────
    def _render(self) -> None:
        self.delete("all")
        if not self._rows:
            # Empty-state message (Phase 6: show in grid mode too
            # so the user never sees a blank canvas).
            self.create_text(
                self._viewport_w() // 2, self._viewport_h() // 2,
                text="No files in this view.",
                fill=self._t["fg_muted"],
                font=("Segoe UI", 11),
            )
            self._update_scrollbar()
            return

        first, last = self._visible_range()
        for idx in range(first, last):
            self._draw_tile(idx)

        # Request async thumbnail decode for visible image tiles whose
        # result is not yet cached / in flight.
        for idx in range(first, last):
            self._request_thumb(idx)

        self._clamp_native_scrollregion()
        self._update_scrollbar()

    def _clamp_native_scrollregion(self) -> None:
        """Pin the native Canvas scrollregion to the viewport so no
        native scroll command moves us outside our pixel bounds.
        Same trick as VirtualFileGrid. Without this, ttk.Scrollbar
        drags can desync from ``_scroll_y``."""
        w = self._viewport_w()
        h = self._viewport_h()
        try:
            super().configure(scrollregion=(0, 0, w, h))
        except tk.TclError:
            pass

    def _update_scrollbar(self) -> None:
        if self._yscrollcommand is not None:
            top, bot = self._yview_fractions()
            try:
                self._yscrollcommand(f"{top:.6f}", f"{bot:.6f}")
            except tk.TclError:
                pass

    def _draw_tile(self, idx: int) -> None:
        row = self._rows[idx]
        x0, y0, x1, y1 = self._tile_rect(idx)
        y0 -= self._scroll_y
        y1 -= self._scroll_y

        is_selected = (idx == self._selected_idx)
        is_checked  = (idx in self._checked)

        # Tile background
        bg = self._t["sel_bg"] if is_selected else self._t["tile"]
        bd = self._t["sel_bg"] if is_selected else self._t["tile_border"]
        self.create_rectangle(x0, y0, x1, y1, fill=bg, outline=bd, width=1)

        # Thumbnail zone
        tx0 = x0 + 6
        ty0 = y0 + 6
        tx1 = x1 - 6
        ty1 = ty0 + _THUMB_H - 12
        kind = _classify(row.get("extension", ""))

        path_str = str(row.get("path", ""))
        path = Path(path_str) if path_str else None
        photo = None
        if kind == "image" and path and _HAS_PIL:
            key = self._cache_key(path)
            if key and key in self._thumb_cache:
                photo = self._ensure_photo(key)

        if photo is not None:
            # Draw the PhotoImage centered inside the thumb zone.
            cx = (tx0 + tx1) // 2
            cy = (ty0 + ty1) // 2
            self.create_image(cx, cy, image=photo, anchor="center")
        else:
            # Colored band + glyph fallback (images also fall here
            # until async decode lands).
            tint = _TYPE_TINT.get(kind, _TYPE_TINT["other"])
            self.create_rectangle(tx0, ty0, tx1, ty1,
                                  fill=tint, outline=tint)
            self.create_text((tx0 + tx1) // 2, (ty0 + ty1) // 2,
                             text=_TYPE_GLYPH.get(kind, _TYPE_GLYPH["other"]),
                             fill="#FFFFFF",
                             font=("Segoe UI Emoji", 34))

        # Count badge — top-right of thumb
        gid = int(row.get("group_id", -1))
        count = self._group_counts.get(gid, 1)
        if count > 1:
            bx = tx1 - _BADGE_R - 2
            by = ty0 + _BADGE_R + 2
            self.create_oval(bx - _BADGE_R, by - _BADGE_R,
                             bx + _BADGE_R, by + _BADGE_R,
                             fill=self._t["badge"], outline="")
            self.create_text(bx, by, text=f"{count}",
                             fill=self._t["badge_fg"],
                             font=("Segoe UI", 9, "bold"))

        # Check indicator — top-left corner, small filled square
        if is_checked:
            cx0 = tx0 + 4
            cy0 = ty0 + 4
            self.create_rectangle(cx0, cy0, cx0 + 16, cy0 + 16,
                                  fill=self._t["sel_bg"], outline="#FFFFFF",
                                  width=2)
            self.create_text(cx0 + 8, cy0 + 8, text="\u2713",
                             fill="#FFFFFF",
                             font=("Segoe UI", 10, "bold"))

        # Filename label
        name = row.get("name") or ""
        if len(name) > 20:
            name = name[:17] + "…"
        label_fg = self._t["sel_fg"] if is_selected else self._t["fg"]
        size_fg  = self._t["sel_fg"] if is_selected else self._t["fg_muted"]
        self.create_text((x0 + x1) // 2, ty1 + 10,
                         text=name, fill=label_fg,
                         font=("Segoe UI", 9), anchor="n")
        self.create_text((x0 + x1) // 2, ty1 + 24,
                         text=row.get("size_str", ""), fill=size_fg,
                         font=("Segoe UI", 8), anchor="n")

    # ─── Async thumbnail decode ─────────────────────────────────────
    def _cache_key(self, path: Path) -> Optional[Tuple[str, float, int]]:
        try:
            st = path.stat()
            return (str(path), st.st_mtime, st.st_size)
        except OSError:
            return None

    def _ensure_photo(self, key: Tuple[str, float, int]):
        """Convert a cached PIL image to an ImageTk.PhotoImage once;
        hold the PhotoImage so Tk doesn't GC it mid-draw."""
        if key in self._photo_images:
            return self._photo_images[key]
        img = self._thumb_cache.get(key)
        if img is None or ImageTk is None:
            return None
        try:
            photo = ImageTk.PhotoImage(img)
        except (tk.TclError, ValueError, OSError) as exc:
            _log.debug("PhotoImage convert failed: %s", exc)
            return None
        self._photo_images[key] = photo
        # Evict photo images when the underlying PIL cache evicts, to
        # avoid leaking. Simplest: cap at the same size and drop LRU.
        while len(self._photo_images) > self._THUMB_CACHE_CAP:
            self._photo_images.pop(next(iter(self._photo_images)))
        return photo

    def _request_thumb(self, idx: int) -> None:
        if not _HAS_PIL:
            return
        if idx in self._decode_futures:
            return
        row = self._rows[idx]
        if _classify(row.get("extension", "")) != "image":
            return
        path_str = str(row.get("path", ""))
        if not path_str:
            return
        path = Path(path_str)
        key = self._cache_key(path)
        if key is None or key in self._thumb_cache:
            return
        fut = self._decode_executor.submit(self._decode, path, key)
        self._decode_futures[idx] = fut
        self.after(40, lambda i=idx, f=fut, k=key: self._poll(i, f, k))

    def _poll(self, idx: int, fut: Future,
              key: Tuple[str, float, int]) -> None:
        if not fut.done():
            self.after(60, lambda: self._poll(idx, fut, key))
            return
        self._decode_futures.pop(idx, None)
        try:
            img = fut.result()
        except Exception as exc:  # pylint: disable=broad-except
            _log.debug("thumb decode crashed for idx=%d: %s", idx, exc)
            return
        if img is None:
            return
        self._thumb_cache[key] = img
        self._thumb_cache.move_to_end(key)
        while len(self._thumb_cache) > self._THUMB_CACHE_CAP:
            evicted_key, _ = self._thumb_cache.popitem(last=False)
            self._photo_images.pop(evicted_key, None)
        # Repaint only if this tile is still in viewport.
        first, last = self._visible_range()
        if first <= idx < last:
            self._render()

    def _decode(self, path: Path, key: Tuple[str, float, int]):
        """Run in worker thread. Never touch Tk from here."""
        if not self._decode_semaphore.acquire(timeout=4):
            return None
        try:
            with Image.open(path) as img:
                if ImageOps is not None:
                    img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                # Fit inside (_TILE_W-12) × (_THUMB_H-12)
                img.thumbnail((_TILE_W - 12, _THUMB_H - 12),
                              Image.Resampling.LANCZOS)
                return img.copy()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:  # type: ignore[attr-defined]
            _log.debug("thumbnail decode failed for '%s': %s", path, exc)
            return None
        finally:
            self._decode_semaphore.release()

    # ─── Input handlers ────────────────────────────────────────────
    def _on_scroll(self, event) -> str:
        step = -3 * (event.delta // 120) if event.delta else 0
        if step:
            self._scroll_by(step * self.ROW_H // 3)   # 1 notch = 1 tile-row
        return "break"

    def _on_scroll_linux(self, event) -> str:
        step = -self.ROW_H if event.num == 4 else self.ROW_H
        self._scroll_by(step)
        return "break"

    def _on_home(self, _event=None) -> str:
        self._selected_idx = 0 if self._rows else None
        self._scroll_to(0)
        return "break"

    def _on_end(self, _event=None) -> str:
        if self._rows:
            self._selected_idx = len(self._rows) - 1
        self._scroll_to(self._total_h)
        return "break"

    def _tile_at(self, x: int, y: int) -> Optional[int]:
        """Return the row index at viewport coords (x, y), or None."""
        if not self._rows:
            return None
        doc_y = y + self._scroll_y
        cols = self._cols()
        col = (x - _EDGE_PAD) // (_TILE_W + _GAP)
        row = (doc_y - _EDGE_PAD) // (_TILE_H + _GAP)
        if col < 0 or col >= cols or row < 0:
            return None
        # Must land inside the tile rect, not in the gap between tiles
        cx = _EDGE_PAD + col * (_TILE_W + _GAP)
        cy = _EDGE_PAD + row * (_TILE_H + _GAP)
        if not (cx <= x <= cx + _TILE_W and cy <= doc_y <= cy + _TILE_H):
            return None
        idx = int(row) * cols + int(col)
        if 0 <= idx < len(self._rows):
            return idx
        return None

    def _on_click(self, event) -> None:
        self.focus_set()
        idx = self._tile_at(event.x, event.y)
        if idx is None:
            return
        # Ctrl-click toggles the check mark without moving selection;
        # plain click selects and also toggles (matches VirtualFileGrid).
        ctrl = bool(event.state & 0x0004)
        if ctrl:
            self._toggle_check(idx)
        else:
            self._selected_idx = idx
            self._toggle_check(idx)
        self._render()

    def _on_dbl(self, event) -> None:
        idx = self._tile_at(event.x, event.y)
        if idx is None:
            return
        self._selected_idx = idx
        self._render()
        if self._on_open_file:
            try:
                self._on_open_file(self._rows[idx])
            except Exception:   # pylint: disable=broad-except
                _log.exception("on_open_file callback raised")

    def _on_space(self, _event) -> str:
        if self._selected_idx is None:
            return "break"
        self._toggle_check(self._selected_idx)
        self._render()
        return "break"

    def _toggle_check(self, idx: int) -> None:
        if idx in self._checked:
            self._checked.remove(idx)
        else:
            self._checked.add(idx)
        self._fire_check_change()

    def _fire_check_change(self) -> None:
        try:
            self.event_generate("<<CheckChanged>>", when="tail")
        except tk.TclError:
            pass

    def _move_sel(self, delta: int) -> None:
        if not self._rows:
            return
        new = (self._selected_idx or 0) + delta
        new = max(0, min(len(self._rows) - 1, new))
        self._selected_idx = new
        self._ensure_visible(new)
        self._render()

    def _move_sel_row(self, delta: int) -> None:
        """Move selection up/down by a whole tile-row (i.e. by ``cols``
        indices) so the arrow keys feel like grid navigation."""
        if not self._rows:
            return
        cols = self._cols()
        self._move_sel(delta * cols)

    def _ensure_visible(self, idx: int) -> None:
        _, y0, _, y1 = self._tile_rect(idx)
        vh = self._viewport_h()
        if y0 < self._scroll_y:
            self._scroll_to(y0 - _EDGE_PAD)
        elif y1 > self._scroll_y + vh:
            self._scroll_to(y1 - vh + _EDGE_PAD)

    # ──────────────────────────────────────────────────────────────
    # Tear-down

    def destroy(self) -> None:  # type: ignore[override]
        try:
            self._decode_executor.shutdown(wait=False)
        except Exception:   # pylint: disable=broad-except
            pass
        super().destroy()
