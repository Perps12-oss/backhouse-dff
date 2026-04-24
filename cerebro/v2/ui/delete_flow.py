"""
delete_flow — FINAL PLAN v2.0 §6.

Delete ceremony: shared by Duplicates page for batch deletion.

Public API:
    DeleteSummaryBar   — always-visible: Selected X files, Will free Y
    DeleteConfirmModal  — modal: file count, space freed, breakdown
    DeleteItem / DeleteCeremonyResult / run_delete_ceremony — ceremony engine

The function blocks on a nested event loop while the progress dialog runs.
Safe to call from a Tk event handler. Must NOT be called from a worker thread.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox
from typing import Callable, Dict, List, Optional, Set

from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_log = logging.getLogger(__name__)

_DANGER   = "#E74C3C"
_SUCCESS  = "#27AE60"
_BLUE     = "#2980B9"
_WHITE    = "#FFFFFF"
_PANEL_BG = "#F0F0F0"
_TEXT     = "#111111"
_TEXT_SEC = "#666666"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"


# ---------------------------------------------------------------------------
# Delete Flow State Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeleteItem:
    """One file slated for deletion."""
    path_str: str
    size:     int


@dataclass
class DeleteCeremonyResult:
    """Return value of ``run_delete_ceremony``."""
    cancelled:         bool           = False
    cancelled_at_step: Optional[int]  = None
    success_count:     int            = 0
    recovered_bytes:   int            = 0
    deleted_paths:     List[str]      = field(default_factory=list)
    failed:            List[tuple]    = field(default_factory=list)
    chose_rescan:      bool           = False
    dry_run:           bool           = False


# ---------------------------------------------------------------------------
# Delete Summary Bar (FINAL PLAN §6.1 — always visible)
# ---------------------------------------------------------------------------

class DeleteSummaryBar(tk.Frame):
    """Always-visible summary bar: Selected: X files, Will free: Y."""

    HEIGHT = 36

    def __init__(
        self,
        master,
        on_delete: Optional[Callable[[], None]] = None,
        on_undo: Optional[Callable[[], None]] = None,
        advanced: bool = False,
        **kwargs,
    ) -> None:
        self._t = ThemeApplicator.get().build_tokens()
        kwargs.setdefault("bg", self._t.get("bg2", _PANEL_BG))
        super().__init__(master, **kwargs)
        self._on_delete = on_delete
        self._on_undo = on_undo
        self._advanced = advanced
        self._selected_count = 0
        self._selected_size = 0
        self._dry_run = False
        self._undo_visible = False
        self._undo_count = 0
        self._build()
        ThemeApplicator.get().register(self._apply_theme)

    def _build(self) -> None:
        t = self._t
        bg = theme_token(t, "bg2", _PANEL_BG)
        fg = theme_token(t, "fg", _TEXT)
        fg2 = theme_token(t, "fg2", _TEXT_SEC)

        inner = tk.Frame(self, bg=bg)
        inner.pack(fill="x", padx=12, pady=6)

        self._summary_label = tk.Label(
            inner, text="Selected: 0 files",
            bg=bg, fg=fg, font=("Segoe UI", 10, "bold"),
        )
        self._summary_label.pack(side="left")

        self._size_label = tk.Label(
            inner, text="Will free: 0 B",
            bg=bg, fg=fg2, font=("Segoe UI", 10),
        )
        self._size_label.pack(side="left", padx=(12, 0))

        self._dry_run_var = tk.BooleanVar(value=False)
        self._dry_run_cb = tk.Checkbutton(
            inner, text="Preview only",
            variable=self._dry_run_var,
            bg=bg, fg=fg2, selectcolor=bg,
            activebackground=bg, activeforeground=fg,
            font=("Segoe UI", 9),
            command=self._on_dry_run_toggle,
        )
        self._dry_run_cb.pack(side="left", padx=(16, 0))

        self._delete_btn = tk.Button(
            inner, text="Delete",
            bg=_DANGER, fg=_WHITE,
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2",
            padx=20, pady=4,
            state="disabled",
            command=self._on_delete_click,
        )
        self._delete_btn.pack(side="right")

        self._mode_var = tk.StringVar(value="recycle")
        if self._advanced:
            self._build_advanced_modes(inner, bg, fg2)

        self._undo_frame = tk.Frame(self, bg=bg)

    def _build_advanced_modes(self, parent: tk.Frame, bg: str, fg: str) -> None:
        self._mode_frame = tk.Frame(parent, bg=bg)
        self._mode_frame.pack(side="right", padx=(0, 8))

        tk.Radiobutton(
            self._mode_frame, text="Recycle bin", variable=self._mode_var,
            value="recycle", bg=bg, fg=fg, selectcolor=bg,
            activebackground=bg, activeforeground=fg,
            font=("Segoe UI", 9),
        ).pack(side="left")

        tk.Radiobutton(
            self._mode_frame, text="Permanent", variable=self._mode_var,
            value="permanent", bg=bg, fg=fg, selectcolor=bg,
            activebackground=bg, activeforeground=fg,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(4, 0))

        tk.Radiobutton(
            self._mode_frame, text="Link replacement", variable=self._mode_var,
            value="link", bg=bg, fg=fg, selectcolor=bg,
            activebackground=bg, activeforeground=fg,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(4, 0))

    def update_summary(self, count: int, size: int) -> None:
        """Update the summary (FINAL PLAN §6.1)."""
        self._selected_count = count
        self._selected_size = size
        self._summary_label.configure(text=f"Selected: {count} files")
        self._size_label.configure(text=f"Will free: {_fmt_size(size)}")
        self._delete_btn.configure(
            state="normal" if count > 0 else "disabled",
        )

    def show_undo(self, count: int) -> None:
        """Show undo toast (FINAL PLAN §6.6 — time-limited)."""
        self._undo_count = count
        self._undo_visible = True
        bg = theme_token(self._t, "bg2", _PANEL_BG)

        self._undo_frame.configure(bg=bg)
        self._undo_frame.pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(
            self._undo_frame,
            text=f"{count} files moved to recycle bin",
            bg=bg, fg=_SUCCESS, font=("Segoe UI", 10),
        ).pack(side="left")

        undo_btn = tk.Button(
            self._undo_frame, text="Undo",
            bg=_BLUE, fg=_WHITE,
            font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2",
            padx=12, pady=2,
            command=self._on_undo_click,
        )
        undo_btn.pack(side="right")

    def hide_undo(self) -> None:
        self._undo_visible = False
        self._undo_frame.pack_forget()

    def set_advanced(self, value: bool) -> None:
        self._advanced = value

    def get_dry_run(self) -> bool:
        return self._dry_run

    def get_mode(self) -> str:
        return self._mode_var.get()

    def _on_dry_run_toggle(self) -> None:
        self._dry_run = self._dry_run_var.get()

    def _on_delete_click(self) -> None:
        if self._on_delete:
            self._on_delete()

    def _on_undo_click(self) -> None:
        self.hide_undo()
        if self._on_undo:
            self._on_undo()

    def _apply_theme(self, t: dict) -> None:
        self._t = t


# ---------------------------------------------------------------------------
# Delete Confirmation Modal (FINAL PLAN §6.3)
# ---------------------------------------------------------------------------

class DeleteConfirmModal(tk.Toplevel):
    """Confirmation modal — must include: file count, space freed, breakdown."""

    WIDTH = 420
    HEIGHT = 320

    def __init__(
        self,
        master,
        file_count: int,
        space_freed: int,
        breakdown: Optional[Dict[str, int]] = None,
        on_confirm: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self.title("Confirm Deletion")
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._build(file_count, space_freed, breakdown or {})

        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.WIDTH) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.HEIGHT) // 2
        self.geometry(f"+{x}+{y}")
        self.bind("<Escape>", lambda _e: self._cancel())

    def _build(self, file_count: int, space_freed: int,
               breakdown: Dict[str, int]) -> None:
        t = ThemeApplicator.get().build_tokens()
        bg = theme_token(t, "bg2", "#FFFFFF")
        fg = theme_token(t, "fg", _TEXT)
        fg2 = theme_token(t, "fg2", _TEXT_SEC)

        self.configure(bg=bg)

        tk.Label(
            self, text="Confirm Deletion",
            bg=bg, fg=fg, font=("Segoe UI", 14, "bold"),
        ).pack(pady=(20, 12))

        tk.Label(
            self, text=f"{file_count} files will be deleted",
            bg=bg, fg=fg, font=("Segoe UI", 12),
        ).pack()

        tk.Label(
            self, text=f"Space freed: {_fmt_size(space_freed)}",
            bg=bg, fg=_SUCCESS, font=("Segoe UI", 12, "bold"),
        ).pack(pady=(8, 16))

        if breakdown:
            breakdown_frame = tk.Frame(self, bg=bg)
            breakdown_frame.pack(fill="x", padx=40)
            tk.Label(
                breakdown_frame, text="Breakdown:",
                bg=bg, fg=fg2, font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")
            for ext, count in sorted(breakdown.items(), key=lambda x: -x[1]):
                tk.Label(
                    breakdown_frame,
                    text=f"  {ext}: {count} files",
                    bg=bg, fg=fg2, font=("Segoe UI", 9),
                ).pack(anchor="w")

        btn_frame = tk.Frame(self, bg=bg)
        btn_frame.pack(side="bottom", fill="x", padx=20, pady=16)

        tk.Button(
            btn_frame, text="Cancel",
            bg=bg, fg=fg, font=("Segoe UI", 10),
            relief="flat", cursor="hand2",
            padx=20, pady=6,
            command=self._cancel,
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_frame, text="Delete",
            bg=_DANGER, fg=_WHITE,
            font=("Segoe UI", 10, "bold"),
            relief="flat", cursor="hand2",
            padx=20, pady=6,
            command=self._confirm,
        ).pack(side="right")

    def _confirm(self) -> None:
        self.destroy()
        if self._on_confirm:
            self._on_confirm()

    def _cancel(self) -> None:
        self.destroy()
        if self._on_cancel:
            self._on_cancel()


# ---------------------------------------------------------------------------
# Full Delete Ceremony (preserved from existing implementation)
# ---------------------------------------------------------------------------

def run_delete_ceremony(
    parent:           tk.Widget,
    items:            List[DeleteItem],
    scan_mode:        str,
    on_remove_paths:  Callable[[Set[str]], None],
    on_navigate_home: Optional[Callable[[], None]] = None,
    on_rescan:        Optional[Callable[[], None]] = None,
    source_tag:       str = "delete_flow",
    dry_run:          bool = False,
) -> DeleteCeremonyResult:
    """Run the delete ceremony and return what happened.

    Flow:
        Step 1 — "Are you sure?"                  Cancel / Confirm
        Step 2 — breakdown + Recycle Bin notice   Cancel / Allow
        Step 3 — progress dialog + worker thread  (non-cancellable)
        Step 4 — summary                          Rescan / OK
        Step 5 — celebration overlay -> on_navigate_home()

    After step 3 succeeds, the floating Undo toast is shown bottom-right.
    """
    result = DeleteCeremonyResult()

    if not items:
        return result

    try:
        from cerebro.v2.ui.delete_ceremony_widgets import (
            _DeleteDialog, _DeleteProgressDialog, _DeleteSummaryDialog,
            _DeleteCelebration, _UndoToast,
            _delete_media_label, _delete_breakdown,
        )
        from cerebro.v2.core.deletion_history_db import log_deletion_event
    except ImportError:
        _log.exception("Delete ceremony unavailable")
        return result

    try:
        from cerebro.utils.formatting import format_bytes
    except ImportError:
        format_bytes = None

    count = len(items)
    noun  = _delete_media_label(scan_mode)
    dry_prefix = "Dry run — " if dry_run else ""
    d_body_1 = (
        (
            f"This is a preview only — no files will be changed.\n\n"
            f"The next steps show what would happen to {count} {noun} in a real "
            "run (Recycle Bin on Windows / Trash elsewhere)."
        )
        if dry_run
        else (
            f"You're about to delete {count} {noun}. This action will move "
            "the files to your system's Recycle Bin.\n\n"
            "Once you move them, you can restore from the Recycle Bin if "
            "you change your mind."
        )
    )
    d_head_1 = (
        f"Preview {count} {noun}?" if dry_run else f"Delete {count} {noun}?"
    )

    d1 = _DeleteDialog(
        parent,
        title=f"{dry_prefix}Delete Confirmation",
        icon="\u26A0",
        headline=d_head_1,
        body=d_body_1,
        btn_cancel="Cancel",
        btn_confirm="Confirm",
        confirm_dangerous=not dry_run,
    )
    if not d1.result:
        result.cancelled = True
        result.cancelled_at_step = 1
        return result

    breakdown_rows = [
        {
            "extension": Path(it.path_str).suffix.lower(),
            "size":      it.size,
            "path":      it.path_str,
        }
        for it in items
    ]
    breakdown = _delete_breakdown(breakdown_rows, noun)
    reclaimable = sum(it.size for it in items)
    reclaimable_str = (
        format_bytes(reclaimable, decimals=1) if format_bytes
        else f"{reclaimable} bytes"
    )

    d2 = _DeleteDialog(
        parent,
        title=f"{dry_prefix}Move to Recycle Bin",
        icon="\u267B",
        headline=("Recycle Bin preview" if dry_run else "Moving to Recycle Bin"),
        body=(
            (
                f"{breakdown} would be moved to the Recycle Bin.\n\n"
                f"Estimated space that would be freed: {reclaimable_str}\n\n"
                "No files are modified in a dry run."
            )
            if dry_run
            else (
                f"{breakdown} will be moved to the Recycle Bin.\n\n"
                f"Estimated space freed: {reclaimable_str}"
            )
        ),
        btn_cancel="Cancel",
        btn_confirm="Continue" if dry_run else "Allow",
        confirm_dangerous=False,
    )
    if not d2.result:
        result.cancelled = True
        result.cancelled_at_step = 2
        return result

    if dry_run:
        result.dry_run = True
        result.success_count = count
        result.recovered_bytes = int(reclaimable)
        messagebox.showinfo(
            "Dry run complete",
            f"No files were changed.\n\n"
            f"{count} {noun} would be moved to the Recycle Bin.\n"
            f"About {reclaimable_str} would be freed.",
            parent=parent,
        )
        return result

    prog = _DeleteProgressDialog(parent, total=count)

    def _worker() -> None:
        try:
            from cerebro.core.deletion import (
                DeletionEngine, DeletionPolicy, DeletionRequest,
            )
        except ImportError:
            DeletionEngine  = None
            DeletionPolicy  = None
            DeletionRequest = None

        engine  = DeletionEngine() if DeletionEngine else None
        request = (
            DeletionRequest(
                policy=DeletionPolicy.TRASH,
                metadata={"source": source_tag, "mode": "trash"},
            )
            if (DeletionRequest and DeletionPolicy) else None
        )
        try:
            import send2trash
        except ImportError:
            send2trash = None

        for i, it in enumerate(items):
            row_key = it.path_str
            size    = int(it.size or 0)
            try:
                fp = Path(row_key).resolve()
            except (OSError, ValueError):
                fp = Path(row_key)

            def _mark_ok() -> None:
                result.success_count      += 1
                result.recovered_bytes    += size
                result.deleted_paths.append(row_key)
                try:
                    log_deletion_event(str(fp), size, scan_mode)
                except (OSError, ValueError, RuntimeError):
                    _log.exception("log_deletion_event failed for %s", fp)

            try:
                if engine and request:
                    res = engine.delete_one(fp, request)
                    if getattr(res, "success", False):
                        _mark_ok()
                    else:
                        result.failed.append(
                            (str(fp),
                             getattr(res, "error", None) or "Unknown error")
                        )
                elif send2trash is not None:
                    send2trash.send2trash(str(fp))
                    _mark_ok()
                else:
                    result.failed.append(
                        (str(fp), "deletion backend unavailable")
                    )
            except (OSError, ValueError, RuntimeError, AttributeError,
                    TypeError, KeyError, ImportError) as exc:
                result.failed.append((str(fp), str(exc)))

            parent.after(0, lambda done=i + 1: prog.set_progress(done))

        parent.after(0, prog.close)

    threading.Thread(target=_worker, daemon=True,
                     name=f"delete-ceremony-{source_tag}").start()
    prog.wait()

    if result.deleted_paths:
        try:
            on_remove_paths(set(result.deleted_paths))
        except Exception:
            _log.exception("on_remove_paths callback raised")

        try:
            size_str = (format_bytes(result.recovered_bytes, decimals=1)
                        if format_bytes else f"{result.recovered_bytes} bytes")
            _UndoToast(
                parent.winfo_toplevel(),
                count=len(result.deleted_paths),
                size_str=size_str,
                deleted_paths=list(result.deleted_paths),
            )
        except Exception:
            _log.debug("Undo toast unavailable", exc_info=True)

    if result.failed:
        head = "\n".join(
            f"  \u2022 {Path(f).name}: {e}" for f, e in result.failed[:5]
        )
        more = (
            f"\n  \u2026 and {len(result.failed) - 5} more"
            if len(result.failed) > 5 else ""
        )
        messagebox.showwarning(
            "Deletion Partial",
            f"Deleted {result.success_count} of {count} {noun}.\n\n"
            f"Failed:\n{head}{more}",
            parent=parent,
        )
        return result

    d4 = _DeleteSummaryDialog(
        parent, noun=noun,
        count=result.success_count,
        recovered=result.recovered_bytes,
    )

    if d4.result == "rescan":
        result.chose_rescan = True
        if on_rescan:
            try:
                on_rescan()
            except Exception:
                _log.exception("on_rescan callback raised")
        return result

    def _done() -> None:
        if on_navigate_home:
            try:
                on_navigate_home()
            except Exception:
                _log.exception("on_navigate_home callback raised")

    _DeleteCelebration(parent, noun=noun, on_done=_done)
    return result
