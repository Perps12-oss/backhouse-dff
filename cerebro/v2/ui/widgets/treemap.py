"""Squarified treemap widget — visualises duplicate groups by reclaimable size."""
from __future__ import annotations

import tkinter as tk
from typing import Callable, List, Optional, Tuple

from cerebro.engines.base_engine import DuplicateGroup

# ---------------------------------------------------------------------------
# Color palette — 8 distinct accent fills cycling by group index
# ---------------------------------------------------------------------------
_PALETTE = [
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
]

_PLACEHOLDER = "Run a scan to see your treemap"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


def _lighten(hex_color: str, amount: float = 0.25) -> str:
    """Return a lightened version of *hex_color* (clamp each channel to 255)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------------------
# Squarified layout algorithm
# ---------------------------------------------------------------------------

def _layout(items: List[Tuple[object, float]], x: float, y: float, w: float, h: float):
    """Recursively split items into a binary treemap. Yield (rx, ry, rw, rh, tag)."""
    if not items:
        return
    if len(items) == 1:
        yield (x, y, w, h, items[0][0])
        return
    total = sum(v for _, v in items)
    if total == 0:
        return
    half = 0
    acc = 0.0
    for i, (_, v) in enumerate(items):
        acc += v
        if acc >= total / 2:
            half = i + 1
            break
    left = items[:half]
    right = items[half:]
    l_total = sum(v for _, v in left)
    r_total = sum(v for _, v in right)
    if w >= h:
        lw = w * l_total / total if total > 0 else w / 2
        yield from _layout(left,  x,      y, lw,     h)
        yield from _layout(right, x + lw, y, w - lw, h)
    else:
        lh = h * l_total / total if total > 0 else h / 2
        yield from _layout(left,  x, y,      w, lh)
        yield from _layout(right, x, y + lh, w, h - lh)


def _squarify(
    rects: List[Tuple[object, float]],
    x: float, y: float, w: float, h: float,
):
    """Yield (rx, ry, rw, rh, tag) for each item in rects=[(tag, value), ...]."""
    if not rects:
        return
    total_area = w * h
    total_val = sum(v for _, v in rects)
    if total_val == 0 or total_area <= 0:
        return
    normalized = [(tag, v / total_val * total_area) for tag, v in rects]
    yield from _layout(normalized, x, y, w, h)


# ---------------------------------------------------------------------------
# TreemapWidget
# ---------------------------------------------------------------------------

class TreemapWidget(tk.Canvas):
    """Canvas-based squarified treemap.

    Sizes each group rectangle by reclaimable bytes.  Supports click-to-select,
    hover highlight, tooltip, and theme tokens.
    """

    _BORDER_W = 2
    _MIN_LABEL_W = 40
    _MIN_LABEL_H = 30

    def __init__(
        self,
        master: tk.Misc,
        on_group_select: Optional[Callable[[int], None]] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bg", "#FFFFFF")
        super().__init__(master, **kwargs)

        self._on_group_select = on_group_select
        self._groups: List[DuplicateGroup] = []
        # Map canvas tag -> (group_id, base_fill)
        self._tag_info: dict = {}
        # Theme tokens
        self._bg       = "#FFFFFF"
        self._border_c = "#E0E0E0"
        self._label_fg = "#111111"

        # Tooltip window
        self._tooltip: Optional[tk.Toplevel] = None
        self._tooltip_label: Optional[tk.Label] = None

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>",  self._on_click)
        self.bind("<Motion>",    self._on_motion)
        self.bind("<Leave>",     self._on_leave)

        # Apply initial theme from ThemeApplicator
        try:
            from cerebro.v2.ui.theme_applicator import ThemeApplicator
            self.apply_theme(ThemeApplicator.get().build_tokens())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API

    def load(self, groups: List[DuplicateGroup]) -> None:
        """Replace displayed groups and redraw."""
        self._groups = list(groups)
        self._redraw()

    def clear(self) -> None:
        """Remove all groups and redraw."""
        self._groups = []
        self._redraw()

    def apply_theme(self, tokens: dict) -> None:
        """Update colors from a theme token dict and redraw."""
        self._bg       = tokens.get("bg",     "#FFFFFF")
        self._border_c = tokens.get("border", "#E0E0E0")
        self._label_fg = tokens.get("fg",     "#111111")
        self.configure(bg=self._bg)
        self._redraw()

    # ------------------------------------------------------------------
    # Drawing

    def _redraw(self) -> None:
        self.delete("all")
        self._tag_info.clear()
        self._hide_tooltip()

        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1:
            return

        if not self._groups:
            self.create_text(
                w // 2, h // 2,
                text=_PLACEHOLDER,
                fill=self._border_c,
                font=("Segoe UI", 11),
                anchor="center",
            )
            return

        items = [
            (g.group_id, float(max(0, g.reclaimable)))
            for g in self._groups
        ]
        # Filter out zero-area items; keep at least 1 pixel worth
        items = [(gid, v) for gid, v in items if v > 0]
        if not items:
            self.create_text(
                w // 2, h // 2,
                text=_PLACEHOLDER,
                fill=self._border_c,
                font=("Segoe UI", 11),
                anchor="center",
            )
            return

        # Sort descending so largest rects are placed first (top-left)
        items.sort(key=lambda x: x[1], reverse=True)

        # Build group_id -> group map for tooltip data
        group_map = {g.group_id: g for g in self._groups}

        for i, (rx, ry, rw, rh, gid) in enumerate(
            _squarify(items, 0, 0, float(w), float(h))
        ):
            # Palette color cycles by original insertion index
            orig_idx = next(
                (j for j, (tag, _) in enumerate(items) if tag == gid), i
            )
            fill = _PALETTE[orig_idx % len(_PALETTE)]
            canvas_tag = f"rect_{gid}"
            bw = self._BORDER_W

            self.create_rectangle(
                rx + bw, ry + bw, rx + rw - bw, ry + rh - bw,
                fill=fill,
                outline=self._border_c,
                width=bw,
                tags=("treemap_rect", canvas_tag),
            )
            self._tag_info[canvas_tag] = {"group_id": gid, "fill": fill}

            # Label — only when rect is big enough
            if rw >= self._MIN_LABEL_W and rh >= self._MIN_LABEL_H:
                g = group_map.get(gid)
                size_str = _fmt_size(g.reclaimable) if g else ""
                label = f"#{gid}"
                if size_str:
                    label = f"#{gid}\n{size_str}"
                max_chars = max(4, int(rw / 7))
                lines = []
                for line in label.split("\n"):
                    if len(line) > max_chars:
                        line = line[:max_chars - 1] + "…"
                    lines.append(line)
                self.create_text(
                    rx + rw / 2, ry + rh / 2,
                    text="\n".join(lines),
                    fill=self._label_fg,
                    font=("Segoe UI", 9),
                    anchor="center",
                    justify="center",
                    tags=("treemap_label", canvas_tag),
                )

        # Bind per-tag events
        self.tag_bind("treemap_rect", "<Enter>",    self._on_rect_enter)
        self.tag_bind("treemap_rect", "<Leave>",    self._on_rect_leave)
        self.tag_bind("treemap_label", "<Enter>",   self._on_rect_enter)
        self.tag_bind("treemap_label", "<Leave>",   self._on_rect_leave)

    # ------------------------------------------------------------------
    # Interaction helpers

    def _rect_tag_from_event(self, event: tk.Event) -> Optional[str]:  # type: ignore[type-arg]
        """Return the rect_<gid> tag of the topmost canvas item under the cursor."""
        items = self.find_overlapping(event.x, event.y, event.x, event.y)
        for item in reversed(items):
            for tag in self.gettags(item):
                if tag.startswith("rect_"):
                    return tag
        return None

    def _on_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        tag = self._rect_tag_from_event(event)
        if tag and tag in self._tag_info and self._on_group_select is not None:
            self._on_group_select(self._tag_info[tag]["group_id"])

    def _on_motion(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        tag = self._rect_tag_from_event(event)
        if tag and tag in self._tag_info:
            info = self._tag_info[tag]
            gid = info["group_id"]
            g = next((g for g in self._groups if g.group_id == gid), None)
            if g:
                tip = (
                    f"Group #{gid}  ·  {len(g.files)} files"
                    f"  ·  {_fmt_size(g.reclaimable)} reclaimable"
                )
                self._show_tooltip(event.x_root + 14, event.y_root + 14, tip)
        else:
            self._hide_tooltip()

    def _on_leave(self, _event: object) -> None:
        self._hide_tooltip()

    def _on_rect_enter(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        tag = self._rect_tag_from_event(event)
        if tag and tag in self._tag_info:
            fill = self._tag_info[tag]["fill"]
            lighter = _lighten(fill, 0.3)
            for item in self.find_withtag(tag):
                try:
                    self.itemconfigure(item, fill=lighter)
                except tk.TclError:
                    pass

    def _on_rect_leave(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        tag = self._rect_tag_from_event(event)
        # Restore only items not under cursor
        for ctag, info in self._tag_info.items():
            for item in self.find_withtag(ctag):
                try:
                    self.itemconfigure(item, fill=info["fill"])
                except tk.TclError:
                    pass
        self._hide_tooltip()

    # ------------------------------------------------------------------
    # Tooltip

    def _show_tooltip(self, x: int, y: int, text: str) -> None:
        if self._tooltip is None:
            self._tooltip = tk.Toplevel(self)
            self._tooltip.wm_overrideredirect(True)
            self._tooltip.wm_attributes("-topmost", True)
            self._tooltip_label = tk.Label(
                self._tooltip,
                text=text,
                bg="#FFFFCC",
                fg="#111111",
                font=("Segoe UI", 9),
                relief="solid",
                borderwidth=1,
                padx=6,
                pady=3,
            )
            self._tooltip_label.pack()
        else:
            if self._tooltip_label is not None:
                self._tooltip_label.configure(text=text)
        try:
            self._tooltip.wm_geometry(f"+{x}+{y}")
            self._tooltip.deiconify()
        except tk.TclError:
            self._tooltip = None
            self._tooltip_label = None

    def _hide_tooltip(self) -> None:
        if self._tooltip is not None:
            try:
                self._tooltip.withdraw()
            except tk.TclError:
                self._tooltip = None
                self._tooltip_label = None
