"""Virtualized thumbnail grid with async decode and backpressure."""

from __future__ import annotations

from pathlib import Path
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
import tkinter as tk

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkButton = ctk.CTkButton
    CTkCheckBox = ctk.CTkCheckBox
    CTkScrollableFrame = ctk.CTkScrollableFrame
except ImportError:
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkButton = tk.Button
    CTkCheckBox = tk.Checkbutton
    CTkScrollableFrame = tk.Frame

try:
    from PIL import Image, ImageOps, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None
    ImageOps = None
    ImageTk = None

from cerebro.v2.core.design_tokens import Spacing, Typography
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme


def _fmt_bytes(n: int) -> str:
    if not n:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i, s = 0, float(n)
    while s >= 1024 and i < len(units) - 1:
        s /= 1024
        i += 1
    return f"{int(s)} {units[i]}" if i == 0 else f"{s:.1f} {units[i]}"


class _Card(CTkFrame):
    THUMB_W = 96
    THUMB_H = 96

    def __init__(self, master, item_id: str, file_obj: Any, on_check: Callable[[str, bool], None], on_click: Callable[[str], None]):
        super().__init__(master, fg_color=theme_color("base.backgroundElevated"), corner_radius=Spacing.BORDER_RADIUS_SM)
        self._item_id = item_id
        self._on_check = on_check
        self._on_click = on_click
        self._var = tk.BooleanVar(value=False)
        self._thumb_ref = None
        name = Path(str(getattr(file_obj, "path", ""))).name
        size = int(getattr(file_obj, "size", 0) or 0)
        self._check = CTkCheckBox(self, text="", variable=self._var, command=self._on_toggle)
        self._check.pack(anchor="ne", padx=Spacing.XS, pady=(Spacing.XS, 0))
        self._thumb = CTkLabel(self, text="Loading...", width=self.THUMB_W, height=self.THUMB_H)
        self._thumb.pack(anchor="w", padx=Spacing.XS, pady=(0, Spacing.XS))
        CTkLabel(self, text=(name[:20] + "..." if len(name) > 20 else name), font=Typography.FONT_XS).pack(anchor="w", padx=Spacing.XS)
        CTkLabel(self, text=_fmt_bytes(size), font=Typography.FONT_XS, text_color=theme_color("base.foregroundMuted")).pack(anchor="w", padx=Spacing.XS, pady=(0, Spacing.XS))
        for w in (self, self._thumb):
            w.bind("<Button-1>", lambda _e: self._on_click(self._item_id))

    def _on_toggle(self) -> None:
        self._on_check(self._item_id, bool(self._var.get()))

    def set_checked(self, checked: bool) -> None:
        self._var.set(bool(checked))

    def is_checked(self) -> bool:
        return bool(self._var.get())

    @property
    def item_id(self) -> str:
        return self._item_id

    def set_thumbnail(self, image) -> None:
        self._thumb_ref = image
        try:
            self._thumb.configure(image=image, text="")
        except Exception:
            pass

    def set_placeholder(self, text: str) -> None:
        try:
            self._thumb.configure(image=None, text=text)
        except Exception:
            pass


class ThumbnailGrid(CTkFrame):
    """Drop-in grid view with ResultsPanel-like API surface."""

    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        subscribe_to_theme(self, self._apply_theme)
        self._groups: List[Any] = []
        self._cards: Dict[str, _Card] = {}
        self._on_selection_changed: Optional[Callable[[List[str]], None]] = None
        self._on_request_add_folder: Optional[Callable[[], None]] = None
        self._on_request_start_search: Optional[Callable[[], None]] = None
        self._render_after_id: Optional[str] = None
        self._scroll_after_id: Optional[str] = None
        self._render_cursor: int = 0
        self._render_batch_size: int = 2
        self._card_chunk_size: int = 12
        self._render_tasks: List[Dict[str, Any]] = []
        self._group_sections: List[Dict[str, Any]] = []
        self._visible_groups_limit: int = 0
        self._group_page_size: int = 14
        self._decode_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumb-decode")
        self._decode_semaphore = threading.Semaphore(4)
        self._decode_futures: Dict[str, Tuple[Future, Tuple[str, float, int]]] = {}
        self._thumb_cache: "OrderedDict[Tuple[str, float, int], Any]" = OrderedDict()
        self._thumb_cache_limit = 180
        self._render_generation: int = 0
        self._build()

    def _build(self) -> None:
        self.configure(fg_color=theme_color("results.background"))
        self._status = CTkLabel(self, text="No results — run a scan", font=Typography.FONT_SM, anchor="w")
        self._status.pack(fill="x", padx=Spacing.XS, pady=(Spacing.XS, 0))
        self._scroll = CTkScrollableFrame(self, fg_color=theme_color("results.background"))
        self._scroll.pack(fill="both", expand=True, padx=Spacing.XS, pady=Spacing.XS)
        self._empty = CTkFrame(self._scroll, fg_color="transparent")
        self._empty.pack(fill="both", expand=True)
        CTkLabel(self._empty, text="No duplicates to display", font=Typography.FONT_LG).pack(pady=(40, Spacing.SM))
        row = CTkFrame(self._empty, fg_color="transparent")
        row.pack()
        CTkButton(row, text="Add Folder", command=lambda: self._on_request_add_folder and self._on_request_add_folder()).pack(side="left", padx=Spacing.XS)
        CTkButton(row, text="Start Search", command=lambda: self._on_request_start_search and self._on_request_start_search()).pack(side="left", padx=Spacing.XS)
        self._bind_scroll_events()

    def _bind_scroll_events(self) -> None:
        try:
            canvas = getattr(self._scroll, "_parent_canvas", None)
            if canvas:
                canvas.bind("<MouseWheel>", self._on_scroll_event, add="+")
                canvas.bind("<Configure>", self._on_scroll_event, add="+")
        except Exception:
            pass

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("results.background"))
            self._scroll.configure(fg_color=theme_color("results.background"))
        except Exception:
            pass

    def load_results(self, groups: List[Any]) -> None:
        self.clear()
        self._groups = list(groups or [])
        total_files = sum(len(getattr(g, "files", []) or []) for g in self._groups)
        self._status.configure(text=f"{len(self._groups)} groups, {total_files} files")
        if not self._groups:
            self._empty.pack(fill="both", expand=True)
            return
        self._empty.pack_forget()
        self._render_cursor = 0
        self._render_tasks = []
        self._group_sections = []
        self._visible_groups_limit = min(len(self._groups), self._group_page_size)
        self._render_generation += 1
        self._schedule_render_next_batch()

    def clear(self) -> None:
        if self._render_after_id:
            try:
                self.after_cancel(self._render_after_id)
            except Exception:
                pass
            self._render_after_id = None
        if self._scroll_after_id:
            try:
                self.after_cancel(self._scroll_after_id)
            except Exception:
                pass
            self._scroll_after_id = None
        self._render_tasks = []
        self._cards.clear()
        self._group_sections = []
        self._visible_groups_limit = 0
        self._render_cursor = 0
        self._render_generation += 1
        for fut, _key in list(self._decode_futures.values()):
            fut.cancel()
        self._decode_futures.clear()
        for w in list(self._scroll.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        self._empty = CTkFrame(self._scroll, fg_color="transparent")
        self._empty.pack(fill="both", expand=True)
        CTkLabel(self._empty, text="No duplicates to display", font=Typography.FONT_LG).pack(pady=(40, Spacing.SM))

    def _schedule_render_next_batch(self) -> None:
        self._render_after_id = self.after(16, self._render_next_batch)

    def _render_next_batch(self) -> None:
        self._render_after_id = None
        # Phase 1: create a few group headers quickly.
        target = min(self._visible_groups_limit, len(self._groups))
        end = min(target, self._render_cursor + self._render_batch_size)
        while self._render_cursor < end:
            self._enqueue_group(self._groups[self._render_cursor])
            self._render_cursor += 1

        # Phase 2: render cards incrementally from queued groups.
        task_budget = 2  # groups per tick
        while self._render_tasks and task_budget > 0:
            task = self._render_tasks[0]
            self._render_group_cards_chunk(task)
            if task["offset"] >= len(task["files"]):
                self._render_tasks.pop(0)
            task_budget -= 1

        try:
            self.update_idletasks()
        except Exception:
            pass

        if self._render_cursor < target or self._render_tasks:
            self._schedule_render_next_batch()

    def _enqueue_group(self, group: Any) -> None:
        gid = getattr(group, "group_id", "?")
        files = list(getattr(group, "files", []) or [])
        section = CTkFrame(self._scroll, fg_color="transparent")
        section.pack(fill="x", pady=(Spacing.SM, 0))
        CTkLabel(section, text=f"Group {gid} — {len(files)} files", font=Typography.FONT_SM, anchor="w").pack(fill="x")
        cards_row = CTkFrame(section, fg_color="transparent")
        cards_row.pack(fill="x", pady=(Spacing.XS, 0))
        task = (
            {
                "group_id": gid,
                "files": files,
                "cards_row": cards_row,
                "offset": 0,
            }
        )
        self._group_sections.append(task)
        self._render_tasks.append(task)

    def _render_group_cards_chunk(self, task: Dict[str, Any]) -> None:
        gid = task["group_id"]
        files = task["files"]
        cards_row = task["cards_row"]
        start = task["offset"]
        end = min(len(files), start + self._card_chunk_size)
        for file_idx in range(start, end):
            f = files[file_idx]
            iid = f"{gid}_{file_idx}"
            card = _Card(cards_row, iid, f, self._on_card_check, self._on_card_click)
            card.pack(side="left", padx=Spacing.XS, pady=Spacing.XS)
            self._cards[iid] = card
            self._request_thumbnail(iid, f)
        task["offset"] = end

    def _on_card_check(self, _item_id: str, _checked: bool) -> None:
        if self._on_selection_changed:
            self._on_selection_changed(self.get_checked())

    def _on_card_click(self, item_id: str) -> None:
        card = self._cards.get(item_id)
        if card is None:
            return
        self.set_check(item_id, not card.is_checked())

    def get_checked(self) -> List[str]:
        return [iid for iid, card in self._cards.items() if card.is_checked()]

    def set_check(self, item_id: str, checked: bool) -> None:
        card = self._cards.get(item_id)
        if card:
            card.set_checked(checked)
            if self._on_selection_changed:
                self._on_selection_changed(self.get_checked())

    def on_selection_changed(self, callback: Callable[[List[str]], None]) -> None:
        self._on_selection_changed = callback

    def on_request_add_folder(self, callback: Callable[[], None]) -> None:
        self._on_request_add_folder = callback

    def on_request_start_search(self, callback: Callable[[], None]) -> None:
        self._on_request_start_search = callback

    def _on_scroll_event(self, _event=None) -> None:
        if self._scroll_after_id:
            try:
                self.after_cancel(self._scroll_after_id)
            except Exception:
                pass
        self._scroll_after_id = self.after(100, self._on_scroll_idle)

    def _on_scroll_idle(self) -> None:
        self._scroll_after_id = None
        if self._visible_groups_limit >= len(self._groups):
            return
        try:
            canvas = getattr(self._scroll, "_parent_canvas", None)
            if canvas is None:
                return
            top = float(canvas.canvasy(0))
            viewport_h = max(float(canvas.winfo_height()), 1.0)
            bottom = top + viewport_h
            _, y1, _, y2 = canvas.bbox("all") or (0, 0, 0, 0)
            if y2 <= 0:
                return
            # Prefetch next page once user gets near bottom.
            if bottom >= y2 - (viewport_h * 1.4):
                self._visible_groups_limit = min(
                    len(self._groups),
                    self._visible_groups_limit + self._group_page_size,
                )
                if self._render_after_id is None:
                    self._schedule_render_next_batch()
        except Exception:
            pass

    def _request_thumbnail(self, item_id: str, file_obj: Any) -> None:
        if not HAS_PIL:
            card = self._cards.get(item_id)
            if card:
                card.set_placeholder("No PIL")
            return
        path = Path(str(getattr(file_obj, "path", "")))
        if not path.exists():
            card = self._cards.get(item_id)
            if card:
                card.set_placeholder("Missing")
            return

        cache_key = self._thumb_cache_key(path)
        cached = self._thumb_cache_get(cache_key)
        if cached is not None:
            card = self._cards.get(item_id)
            if card:
                card.set_thumbnail(cached)
            return

        if item_id in self._decode_futures:
            return
        generation = self._render_generation
        fut = self._decode_executor.submit(self._decode_thumbnail, path, cache_key)
        self._decode_futures[item_id] = (fut, cache_key)
        self.after(0, lambda: self._poll_decode(item_id, fut, cache_key, generation))

    def _poll_decode(self, item_id: str, future: Future, cache_key: Tuple[str, float, int], generation: int) -> None:
        if generation != self._render_generation:
            return
        if not future.done():
            self.after(40, lambda: self._poll_decode(item_id, future, cache_key, generation))
            return
        self._decode_futures.pop(item_id, None)
        try:
            pil_image = future.result()
        except Exception:
            pil_image = None
        card = self._cards.get(item_id)
        if card is None:
            return
        if pil_image is None:
            card.set_placeholder("Preview N/A")
            return
        tk_image = ImageTk.PhotoImage(pil_image)
        self._thumb_cache_put(cache_key, tk_image)
        card.set_thumbnail(tk_image)

    def _thumb_cache_key(self, path: Path) -> Tuple[str, float, int]:
        try:
            st = path.stat()
            return (str(path), st.st_mtime, st.st_size)
        except OSError:
            return (str(path), 0.0, 0)

    def _thumb_cache_get(self, key: Tuple[str, float, int]):
        image = self._thumb_cache.get(key)
        if image is not None:
            self._thumb_cache.move_to_end(key)
        return image

    def _thumb_cache_put(self, key: Tuple[str, float, int], image) -> None:
        self._thumb_cache[key] = image
        self._thumb_cache.move_to_end(key)
        while len(self._thumb_cache) > self._thumb_cache_limit:
            self._thumb_cache.popitem(last=False)

    def _decode_thumbnail(self, path: Path, cache_key: Tuple[str, float, int]):
        if not self._decode_semaphore.acquire(timeout=4):
            return None
        try:
            with Image.open(path) as img:
                if ImageOps is not None:
                    img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                img.thumbnail((_Card.THUMB_W, _Card.THUMB_H), Image.Resampling.LANCZOS)
                return img.copy()
        except Exception:
            return None
        finally:
            self._decode_semaphore.release()
