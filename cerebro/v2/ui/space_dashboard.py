"""Space Reclaimed Dashboard — gamified stats showing cumulative deletion savings."""
from __future__ import annotations

import tkinter as tk
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from cerebro.utils.formatting import format_bytes
from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_NAVY     = "#0B1929"
_NAVY_MID = "#1E3A5F"
_WHITE    = "#FFFFFF"
_MUTED    = "#7090A8"
_ACCENT   = "#2563EB"
_GOLD     = "#F4C430"
_GRAY     = "#4A6070"

_MILESTONES = [
    (100 * 1024 * 1024,       "100 MB"),
    (1024 ** 3,               "1 GB"),
    (10 * 1024 ** 3,          "10 GB"),
    (100 * 1024 ** 3,         "100 GB"),
]


def _day_key(iso_date_str: str) -> str:
    """Return YYYY-MM-DD from an ISO timestamp string; empty string on error."""
    try:
        return str(datetime.fromisoformat(iso_date_str).date())
    except (ValueError, TypeError):
        return ""


class SpaceDashboard(tk.Frame):
    """Gamified space-reclaimed panel embedded in WelcomePage."""

    def __init__(self, master, **kwargs) -> None:
        kwargs.setdefault("bg", _NAVY)
        super().__init__(master, **kwargs)
        self._rows: List[Dict[str, Any]] = []
        self._tokens: dict = {}
        self._sparkline_canvas: tk.Canvas | None = None
        self._build()
        self._tokens = ThemeApplicator.get().build_tokens()
        ThemeApplicator.get().register(self._on_theme)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, deletion_rows: List[Dict[str, Any]]) -> None:
        """Refresh dashboard from a list of deletion history row dicts."""
        self._rows = list(deletion_rows) if deletion_rows else []
        self._rebuild()

    def apply_theme(self, tokens: dict) -> None:
        """Apply theme tokens to every widget in the dashboard."""
        self._tokens = tokens
        self._rebuild()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_theme(self, tokens: dict) -> None:
        self._tokens = tokens
        self._rebuild()

    def _build(self) -> None:
        """Create initial placeholder layout (will be replaced by _rebuild)."""
        self._rebuild()

    def _rebuild(self) -> None:
        """Destroy and recreate all child widgets from current data + tokens."""
        for w in self.winfo_children():
            w.destroy()
        self._sparkline_canvas = None

        t = self._tokens
        bg       = theme_token(t, "bg",      _NAVY)
        bar      = theme_token(t, "nav_bar", _NAVY_MID)
        fg       = theme_token(t, "fg",      _WHITE)
        fg_muted = theme_token(t, "fg_muted", _MUTED)
        accent   = theme_token(t, "accent",  _ACCENT)

        self.configure(bg=bg)

        # ── Section header ────────────────────────────────────────────
        hdr = tk.Frame(self, bg=bar, height=32)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="SPACE RECLAIMED",
            bg=bar, fg=fg,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=12, pady=6)

        # 8 px gap
        tk.Frame(self, bg=bg, height=8).pack()

        # ── No-data placeholder ───────────────────────────────────────
        if not self._rows:
            tk.Label(
                self,
                text="Delete your first duplicates to see your savings here.",
                bg=bg, fg=fg_muted,
                font=("Segoe UI", 11),
                wraplength=380, justify="center",
            ).pack(padx=16, pady=24)
            return

        # ── Compute stats ─────────────────────────────────────────────
        total_bytes  = sum(int(r.get("size", 0) or 0) for r in self._rows)
        n_files      = len(self._rows)
        sessions     = {str(r.get("mode", "")) + "|" + _day_key(str(r.get("deletion_date", "")))
                        for r in self._rows}
        n_sessions   = len(sessions)

        # Sparkline: daily bytes for last 30 days
        today = datetime.now(timezone.utc).date()
        daily: dict[str, int] = defaultdict(int)
        for r in self._rows:
            dk = _day_key(str(r.get("deletion_date", "")))
            if dk:
                daily[dk] += int(r.get("size", 0) or 0)

        sparkline_days: List[int] = []
        for offset in range(29, -1, -1):
            d = today - timedelta(days=offset)
            sparkline_days.append(daily.get(str(d), 0))

        # ── Hero stat row (number + badges side by side) ──────────────
        hero_row = tk.Frame(self, bg=bg)
        hero_row.pack(fill="x", padx=16, pady=(4, 0))

        # Hero number
        hero_val = tk.Label(
            hero_row,
            text=format_bytes(total_bytes),
            bg=bg, fg=fg,
            font=("Segoe UI", 32, "bold"),
        )
        hero_val.pack(side="left")

        tk.Label(
            hero_row,
            text="  total freed",
            bg=bg, fg=fg_muted,
            font=("Segoe UI", 11),
        ).pack(side="left", anchor="s", pady=(0, 8))

        # Badges — right-aligned in the same row
        badge_row = tk.Frame(hero_row, bg=bg)
        badge_row.pack(side="right", anchor="center")
        for threshold, label in _MILESTONES:
            unlocked = total_bytes >= threshold
            if unlocked:
                bg_b, fg_b, txt = _GOLD, "#333333", f"  {label}  "
            else:
                bg_b, fg_b, txt = bg, _GRAY, f"  {label}  "
            badge = tk.Label(
                badge_row,
                text=txt,
                bg=bg_b, fg=fg_b,
                font=("Segoe UI", 9, "bold"),
                relief="solid" if unlocked else "flat",
                bd=1 if unlocked else 0,
                padx=4, pady=2,
            )
            badge.pack(side="left", padx=2)

        # ── Sparkline canvas ──────────────────────────────────────────
        CANVAS_H    = 60
        BAR_W       = 8
        BAR_GAP     = 3
        CANVAS_W    = 30 * (BAR_W + BAR_GAP) + BAR_GAP

        spark_frame = tk.Frame(self, bg=bg)
        spark_frame.pack(fill="x", padx=16, pady=(6, 0))

        canvas = tk.Canvas(
            spark_frame,
            width=CANVAS_W, height=CANVAS_H,
            bg=bar, highlightthickness=0,
        )
        canvas.pack(fill="x", expand=True)
        self._sparkline_canvas = canvas

        max_val = max(sparkline_days) if any(v > 0 for v in sparkline_days) else 1
        USABLE_H = CANVAS_H - 6  # leave 3 px top + 3 px bottom margin

        for i, val in enumerate(sparkline_days):
            x0 = BAR_GAP + i * (BAR_W + BAR_GAP)
            x1 = x0 + BAR_W
            if val > 0:
                bar_h = max(3, int(val / max_val * USABLE_H))
                y0 = CANVAS_H - 3 - bar_h
                y1 = CANVAS_H - 3
                canvas.create_rectangle(x0, y0, x1, y1, fill=accent, outline="")
            else:
                # thin baseline marker
                canvas.create_rectangle(x0, CANVAS_H - 4, x1, CANVAS_H - 3,
                                        fill=_GRAY, outline="")

        # X-axis labels
        lbl_frame = tk.Frame(self, bg=bg)
        lbl_frame.pack(fill="x", padx=16)
        tk.Label(lbl_frame, text="30d ago", bg=bg, fg=fg_muted,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Label(lbl_frame, text="today", bg=bg, fg=fg_muted,
                 font=("Segoe UI", 8)).pack(side="right")

        # ── Footer stat ───────────────────────────────────────────────
        tk.Label(
            self,
            text=f"{n_files} file{'s' if n_files != 1 else ''} deleted"
                 f" across {n_sessions} session{'s' if n_sessions != 1 else ''}",
            bg=bg, fg=fg_muted,
            font=("Segoe UI", 10),
        ).pack(pady=(6, 10))
