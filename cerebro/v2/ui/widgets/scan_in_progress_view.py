"""Scan in-progress view — shared widget used by both ResultsPanel and ScanPage.

Extracted from results_panel.py during post-v1 audit. Previously duplicated:
- results_panel._ScanInProgressView (styled version, kept)
- scan_page._ScanProgressView        (plain version, retired)

This unified view keeps the styled layout (phase label, stat cards, cancel
button, indeterminate pbar handling) and adds the plain version's only unique
feature: a current-file label that shows the basename being processed.
"""

from __future__ import annotations

import logging
import time
import tkinter as tk
from pathlib import Path
from typing import Callable, Dict, Optional

try:
    import customtkinter as ctk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
    CTkButton = ctk.CTkButton
    CTkProgressBar = ctk.CTkProgressBar
except ImportError:
    CTkFrame = tk.Frame
    CTkLabel = tk.Label
    CTkButton = tk.Button
    CTkProgressBar = None  # type: ignore[misc, assignment]

from cerebro.v2.core.design_tokens import Spacing, Typography
from cerebro.v2.core.theme_bridge_v2 import theme_color, subscribe_to_theme

logger = logging.getLogger(__name__)


# Known TurboScanner progress_callback stage strings -> UI label
_STAGE_LABELS: Dict[str, str] = {
    "": "Discovering files...",
    "discovering": "Discovering files...",
    "analyzing_images": "Analyzing images...",
    "grouping_by_size": "Grouping by size...",
    "hashing_partial": "Computing partial hashes...",
    "hashing_full": "Computing full hashes...",
    "complete": "Finalising results...",
}


def friendly_stage_label(stage: str) -> str:
    """Map engine stage key to a short headline; unknown keys are shown title-cased."""
    key = (stage or "").strip()
    if key in _STAGE_LABELS:
        return _STAGE_LABELS[key]
    if not key:
        return _STAGE_LABELS[""]
    return key.replace("_", " ").strip().title()


class ScanInProgressView(CTkFrame):
    """Live scan status view with stat cards, progress bar, and cancel button.

    Rendered by:
    - ResultsPanel.show_scanning_progress() — Results / grid host path.
    - ScanPage._show_progress()            — in-page Start button path.

    Both paths call the same update_progress() / reset() API.
    """

    def __init__(self, master, *, on_cancel: Callable[[], None], **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._on_cancel = on_cancel
        self._last_progress_ts: Optional[float] = None
        self._apply_calls = 0
        self._phase_label: Optional[CTkLabel] = None
        self._files_num: Optional[CTkLabel] = None
        self._elapsed_num: Optional[CTkLabel] = None
        self._subtitle: Optional[CTkLabel] = None
        self._current_file_lbl: Optional[CTkLabel] = None
        self._pbar = None
        self._pbar_indeterminate = False
        subscribe_to_theme(self, self._apply_theme)
        self._build_ui()

    def _build_ui(self) -> None:
        self.configure(fg_color=theme_color("results.background"))
        outer = CTkFrame(self, fg_color="transparent")
        outer.place(relx=0.5, rely=0.5, anchor="center")

        self._phase_label = CTkLabel(
            outer,
            text=friendly_stage_label(""),
            font=("", 20, "bold"),
            text_color=theme_color("base.foreground"),
        )
        self._phase_label.pack(pady=(0, Spacing.LG))

        cards = CTkFrame(outer, fg_color="transparent")
        cards.pack(fill="x", pady=(0, Spacing.MD))

        card_l = CTkFrame(cards, fg_color=theme_color("base.backgroundElevated"), corner_radius=8)
        card_l.pack(side="left", expand=True, fill="both", padx=(0, Spacing.SM))
        self._files_num = CTkLabel(
            card_l, text="0", font=("", 30, "bold"), text_color=theme_color("base.foreground")
        )
        self._files_num.pack(pady=(Spacing.SM, 0))
        CTkLabel(
            card_l,
            text="files scanned",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"),
        ).pack(pady=(0, Spacing.SM))

        card_r = CTkFrame(cards, fg_color=theme_color("base.backgroundElevated"), corner_radius=8)
        card_r.pack(side="left", expand=True, fill="both", padx=(Spacing.SM, 0))
        self._elapsed_num = CTkLabel(
            card_r, text="0:00", font=("", 30, "bold"), text_color=theme_color("base.foreground")
        )
        self._elapsed_num.pack(pady=(Spacing.SM, 0))
        CTkLabel(
            card_r,
            text="elapsed",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundSecondary"),
        ).pack(pady=(0, Spacing.SM))

        self._pbar = CTkProgressBar(outer, width=420, height=16) if CTkProgressBar else None
        if self._pbar:
            self._pbar.pack(fill="x", pady=(Spacing.SM, Spacing.XS))
            self._pbar.set(0)

        self._subtitle = CTkLabel(
            outer,
            text="0 files discovered",
            font=Typography.FONT_SM,
            text_color=theme_color("base.foregroundSecondary"),
        )
        self._subtitle.pack(pady=(0, Spacing.XS))

        # Current-file line: empty until update_progress() provides one.
        # Ported from the retired scan_page._ScanProgressView.
        self._current_file_lbl = CTkLabel(
            outer,
            text="",
            font=Typography.FONT_XS,
            text_color=theme_color("base.foregroundMuted"),
        )
        self._current_file_lbl.pack(pady=(0, Spacing.LG))

        cancel = CTkButton(
            outer,
            text="Cancel scan",
            width=180,
            height=40,
            font=Typography.FONT_MD,
            fg_color=theme_color("button.danger"),
            hover_color=theme_color("button.dangerHover"),
            command=self._on_cancel,
        )
        cancel.pack(pady=(Spacing.MD, 0))

    def _apply_theme(self) -> None:
        try:
            self.configure(fg_color=theme_color("results.background"))
        except (tk.TclError, AttributeError, ValueError) as exc:
            logger.debug("ScanInProgressView theme skipped: %s", exc)

    def apply_theme(self, _t: Optional[dict] = None) -> None:
        """Compatibility shim for callers that pass a token dict (e.g. ScanPage).

        The widget self-subscribes to theme_bridge_v2 via subscribe_to_theme(),
        so dict-based callers need only to poke the internal re-apply.
        """
        self._apply_theme()

    def reset(self) -> None:
        self._last_progress_ts = None
        self._apply_calls = 0
        if self._phase_label:
            self._phase_label.configure(text=friendly_stage_label(""))
        if self._files_num:
            self._files_num.configure(text="0")
        if self._elapsed_num:
            self._elapsed_num.configure(text="0:00")
        if self._subtitle:
            self._subtitle.configure(text="0 files discovered")
        if self._current_file_lbl:
            self._current_file_lbl.configure(text="")
        if self._pbar:
            if self._pbar_indeterminate:
                try:
                    self._pbar.stop()
                except (tk.TclError, RuntimeError, AttributeError):
                    pass
                self._pbar_indeterminate = False
            try:
                self._pbar.configure(mode="determinate")
            except (tk.TclError, ValueError, AttributeError):
                pass
            self._pbar.set(0)

    def update_progress(
        self,
        *,
        stage: str,
        files_scanned: int,
        files_total: int,
        elapsed_seconds: float,
        current_file: str = "",
    ) -> None:
        now = time.monotonic()
        if self._last_progress_ts is not None and (now - self._last_progress_ts) < 0.1:
            return
        self._last_progress_ts = now
        self._apply_calls += 1

        if self._phase_label:
            self._phase_label.configure(text=friendly_stage_label(stage))

        if self._files_num:
            self._files_num.configure(text=f"{files_scanned:,}")

        elapsed = max(0.0, float(elapsed_seconds))
        if elapsed < 3600:
            mm = int(elapsed // 60)
            ss = int(elapsed % 60)
            elapsed_str = f"{mm}:{ss:02d}"
        else:
            h = int(elapsed // 3600)
            mm = int((elapsed % 3600) // 60)
            ss = int(elapsed % 60)
            elapsed_str = f"{h}:{mm:02d}:{ss:02d}"
        if self._elapsed_num:
            self._elapsed_num.configure(text=elapsed_str)

        if self._subtitle:
            if files_total > 0:
                self._subtitle.configure(
                    text=f"{files_scanned:,} of {files_total:,} files",
                )
            else:
                self._subtitle.configure(text=f"{files_scanned:,} files discovered")

        if self._current_file_lbl:
            if current_file:
                # Truncate long basenames; keep original for tooltip/logging elsewhere.
                name = Path(current_file).name
                self._current_file_lbl.configure(text=name[:60])
            else:
                self._current_file_lbl.configure(text="")

        if self._pbar:
            if files_total <= 0:
                if not self._pbar_indeterminate:
                    try:
                        self._pbar.configure(mode="indeterminate")
                        self._pbar.start()
                    except (tk.TclError, ValueError, AttributeError) as exc:
                        logger.debug("Progress bar indeterminate mode failed: %s", exc)
                    self._pbar_indeterminate = True
            else:
                if self._pbar_indeterminate:
                    try:
                        self._pbar.stop()
                        self._pbar.configure(mode="determinate")
                    except (tk.TclError, ValueError, AttributeError) as exc:
                        logger.debug("Progress bar determinate switch failed: %s", exc)
                    self._pbar_indeterminate = False
                ratio = min(1.0, max(0.0, files_scanned / float(files_total)))
                try:
                    self._pbar.set(ratio)
                except (tk.TclError, ValueError, AttributeError) as exc:
                    logger.debug("Progress bar set failed: %s", exc)


__all__ = [
    "ScanInProgressView",
    "friendly_stage_label",
    "_STAGE_LABELS",
]
