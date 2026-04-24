"""Delete ceremony UI — modals, progress, summary, celebration, undo toast.

Moved out of the retired monolithic Ashisoft shell module so the live app path
(``main.py`` → ``app_shell.run_app``) never imports the legacy Ashisoft
shell.  Imported by :mod:`cerebro.v2.ui.delete_flow` only.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from typing import Callable, List

from cerebro.services.logger import get_logger
from cerebro.utils.formatting import format_bytes
from cerebro.v2.core.theme_bridge_v2 import theme_color
from cerebro.v2.ui.feedback import show_text_panel

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Delete-flow helpers (module-level — no self needed)
# ---------------------------------------------------------------------------

def delete_media_label(mode: str) -> str:
    """Return the plural media noun for the current scan mode."""
    from cerebro.v2.ui.mode_tabs import ScanMode

    return {
        ScanMode.PHOTOS: "photos",
        ScanMode.VIDEOS: "videos",
        ScanMode.MUSIC: "music tracks",
        ScanMode.EMPTY_FOLDERS: "empty folders",
        ScanMode.LARGE_FILES: "files",
    }.get(mode, "files")


def delete_breakdown(files: list, mode: str) -> str:
    """Return e.g. '21 photos' or '12 images · 5 videos · 4 other files'."""
    from cerebro.v2.ui.mode_tabs import ScanMode

    n = len(files)

    if mode == ScanMode.PHOTOS:
        return f"{n} photo{'s' if n != 1 else ''}"
    if mode == ScanMode.VIDEOS:
        return f"{n} video{'s' if n != 1 else ''}"
    if mode == ScanMode.MUSIC:
        return f"{n} music track{'s' if n != 1 else ''}"
    if mode == ScanMode.EMPTY_FOLDERS:
        return f"{n} empty folder{'s' if n != 1 else ''}"

    # FILES / LARGE_FILES — group by category
    IMG = {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic",
        ".tiff", ".tif", ".cr2", ".cr3", ".nef", ".arw", ".dng",
    }
    VID = {
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
        ".m4v", ".mpg", ".mpeg", ".3gp",
    }
    AUD = {
        ".mp3", ".flac", ".ogg", ".wav", ".aac", ".m4a", ".wma",
        ".opus", ".aiff", ".ape",
    }
    cats: dict = {"images": 0, "videos": 0, "audio files": 0, "other files": 0}
    for f in files:
        p = str(f.get("path", "") if isinstance(f, dict) else getattr(f, "path", ""))
        ext = Path(p).suffix.lower()
        if ext in IMG:
            cats["images"] += 1
        elif ext in VID:
            cats["videos"] += 1
        elif ext in AUD:
            cats["audio files"] += 1
        else:
            cats["other files"] += 1
    parts = [f"{v} {k}" for k, v in cats.items() if v]
    return " · ".join(parts) or f"{n} files"


# =============================================================================
# Undo Toast — non-blocking notification after send2trash
# =============================================================================

class UndoToast:
    """
    Floating toast that appears at the bottom-right of the parent window
    after files are moved to the Recycle Bin.

    Dismisses automatically after TIMEOUT_S seconds or when the user
    clicks Undo (which attempts OS-level restore from Trash).
    """

    TIMEOUT_S = 30
    BG = "#1e2430"
    FG = "#e0e0e0"
    ACCENT = "#4fc3f7"

    def __init__(self, parent: tk.Wm, count: int, size_str: str,
                 deleted_paths: List[str]) -> None:
        self._parent = parent
        self._deleted = deleted_paths
        self._after_id = None

        self._win = tk.Toplevel(parent)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        try:
            self._win.attributes("-alpha", 0.95)
        except tk.TclError as exc:
            logger.debug("Toast transparency unsupported: %s", exc)

        # Content
        frame = tk.Frame(self._win, bg=self.BG, padx=14, pady=10)
        frame.pack(fill="both")

        tk.Label(
            frame,
            text=f"🗑  {count} file{'s' if count != 1 else ''} moved to Recycle Bin  ({size_str})",
            bg=self.BG, fg=self.FG,
            font=("", 10),
        ).pack(side="left", padx=(0, 16))

        tk.Button(
            frame, text="Undo", bg=self.ACCENT, fg="#000",
            relief="flat", padx=8, pady=2, font=("", 10, "bold"),
            cursor="hand2",
            command=self._undo,
        ).pack(side="left")

        tk.Button(
            frame, text="✕", bg=self.BG, fg=self.FG,
            relief="flat", padx=6, font=("", 10),
            cursor="hand2",
            command=self._dismiss,
        ).pack(side="left", padx=(8, 0))

        # Position: bottom-right of parent
        self._win.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() - self._win.winfo_width() - 24
        py = parent.winfo_rooty() + parent.winfo_height() - self._win.winfo_height() - 40
        self._win.geometry(f"+{px}+{py}")

        # Auto-dismiss
        self._after_id = parent.after(self.TIMEOUT_S * 1000, self._dismiss)

    def _dismiss(self) -> None:
        try:
            if self._after_id:
                self._parent.after_cancel(self._after_id)
            self._win.destroy()
        except (tk.TclError, ValueError, AttributeError) as exc:
            logger.debug("Undo toast dismiss cleanup skipped: %s", exc)

    def _undo(self) -> None:
        """Attempt to restore trashed files from the platform Recycle Bin."""
        restored = 0
        if sys.platform == "win32":
            try:
                subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])
                restored = -1
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Failed to open Recycle Bin on Windows: %s", exc)
        elif sys.platform == "darwin":
            try:
                subprocess.Popen(["open", os.path.expanduser("~/.Trash")])
                restored = -1
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Failed to open Trash on macOS: %s", exc)
        else:
            try:
                trash_dir = Path.home() / ".local" / "share" / "Trash" / "files"
                subprocess.Popen(["xdg-open", str(trash_dir)])
                restored = -1
            except (OSError, subprocess.SubprocessError) as exc:
                logger.warning("Failed to open Trash folder on Linux: %s", exc)

        if restored == -1:
            show_text_panel(
                self._parent,
                "Undo",
                "The Recycle Bin has been opened.\n"
                "Select the files and choose 'Restore' to recover them.",
            )
        self._dismiss()


# =============================================================================
# Delete-flow dialog widgets
# =============================================================================

class DeleteConfirmDialog:
    """Blocking two-button modal confirmation dialog used by the delete flow."""

    def __init__(self, parent, *, title: str, icon: str, headline: str, body: str,
                 btn_cancel: str, btn_confirm: str, confirm_dangerous: bool = False):
        self.result: bool = False

        try:
            import customtkinter as _ctk
            win = _ctk.CTkToplevel(parent)
            win.configure(fg_color=theme_color("base.backgroundElevated"))
        except Exception:
            win = tk.Toplevel(parent)
            win.configure(bg=theme_color("base.backgroundElevated"))

        self._win = win
        win.title(title)
        win.resizable(False, False)
        win.transient(parent)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        bg = theme_color("base.backgroundElevated")
        pad = 24

        header = tk.Frame(win, bg=bg)
        header.pack(fill="x", padx=pad, pady=(pad, 0))
        tk.Label(header, text=icon, font=("", 26),
                 bg=bg, fg=theme_color("base.foreground")).pack(side="left", padx=(0, 12))
        tk.Label(header, text=headline, font=("", 15, "bold"),
                 bg=bg, fg=theme_color("base.foreground"),
                 justify="left", wraplength=340).pack(side="left")

        tk.Label(win, text=body, font=("", 11),
                 bg=bg, fg=theme_color("base.foregroundSecondary"),
                 justify="left", wraplength=400, anchor="w").pack(
            fill="x", padx=pad, pady=(12, 20))

        tk.Frame(win, height=1, bg="#2d3748").pack(fill="x")

        btn_row = tk.Frame(win, bg=bg)
        btn_row.pack(fill="x", padx=pad, pady=(12, pad))

        confirm_bg = (
            theme_color("button.danger") if confirm_dangerous
            else theme_color("button.primary")
        )

        def _confirm() -> None:
            self.result = True
            win.destroy()

        def _cancel() -> None:
            self.result = False
            win.destroy()

        tk.Button(
            btn_row, text=btn_cancel, command=_cancel,
            font=("", 11), relief="flat", padx=16, pady=6,
            bg=theme_color("button.secondary"),
            fg=theme_color("base.foreground"), cursor="hand2",
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_row, text=btn_confirm, command=_confirm,
            font=("", 11, "bold"), relief="flat", padx=16, pady=6,
            bg=confirm_bg, fg="#ffffff", cursor="hand2",
        ).pack(side="right")

        win.update_idletasks()
        win.minsize(440, 1)
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - win.winfo_width()) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{px}+{py}")
        win.grab_set()
        parent.wait_window(win)


class DeleteProgressDialog:
    """Modal progress dialog shown while files are being moved to the Recycle Bin."""

    def __init__(self, parent, *, total: int):
        self._parent = parent
        self._total = max(1, total)
        self._closed = False

        try:
            import customtkinter as _ctk
            win = _ctk.CTkToplevel(parent)
            win.configure(fg_color=theme_color("base.backgroundElevated"))
        except Exception:
            win = tk.Toplevel(parent)
            win.configure(bg=theme_color("base.backgroundElevated"))

        self._win = win
        win.title("Deleting…")
        win.resizable(False, False)
        win.transient(parent)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        bg = theme_color("base.backgroundElevated")
        pad = 28

        tk.Label(win, text="🗑  Moving files to Recycle Bin…",
                 font=("", 14, "bold"), bg=bg,
                 fg=theme_color("base.foreground")).pack(padx=pad, pady=(pad, 6))

        self._label = tk.Label(win, text=f"0 of {total}",
                               font=("", 11), bg=bg,
                               fg=theme_color("base.foregroundSecondary"))
        self._label.pack(padx=pad)

        bar_frame = tk.Frame(win, bg=bg)
        bar_frame.pack(fill="x", padx=pad, pady=(10, pad))

        self._use_ctk_bar = False
        try:
            import customtkinter as _ctk
            self._pbar = _ctk.CTkProgressBar(bar_frame, width=380, height=14)
            self._pbar.pack(fill="x")
            self._pbar.set(0)
            self._use_ctk_bar = True
        except Exception:
            self._canvas = tk.Canvas(bar_frame, height=10, bg="#2d3748",
                                     highlightthickness=0, width=380)
            self._canvas.pack(fill="x")

        win.update_idletasks()
        win.minsize(440, 1)
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - win.winfo_width()) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{px}+{py}")
        win.grab_set()

    def set_progress(self, done: int) -> None:
        if self._closed:
            return
        try:
            pct = min(1.0, done / self._total)
            self._label.configure(text=f"{done} of {self._total}")
            if self._use_ctk_bar:
                self._pbar.set(pct)
            else:
                self._canvas.update_idletasks()
                w = self._canvas.winfo_width() or 380
                self._canvas.delete("all")
                self._canvas.create_rectangle(
                    0, 0, int(w * pct), 10, fill="#4fc3f7", outline=""
                )
        except (tk.TclError, AttributeError):
            pass

    def close(self) -> None:
        self._closed = True
        try:
            self._win.grab_release()
            self._win.destroy()
        except (tk.TclError, AttributeError):
            pass

    def wait(self) -> None:
        try:
            self._parent.wait_window(self._win)
        except (tk.TclError, AttributeError):
            pass


class DeleteSummaryDialog:
    """Summary dialog shown after all deletions finish. result = 'ok' | 'rescan'."""

    def __init__(self, parent, *, noun: str, count: int, recovered: int):
        self.result: str = "ok"
        recovered_str = format_bytes(recovered, decimals=1)

        try:
            import customtkinter as _ctk
            win = _ctk.CTkToplevel(parent)
            win.configure(fg_color=theme_color("base.backgroundElevated"))
        except Exception:
            win = tk.Toplevel(parent)
            win.configure(bg=theme_color("base.backgroundElevated"))

        self._win = win
        win.title("Deletion Complete")
        win.resizable(False, False)
        win.transient(parent)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        bg = theme_color("base.backgroundElevated")
        success_color = theme_color("feedback.success")
        pad = 28

        tk.Frame(win, height=6, bg=success_color).pack(fill="x")

        tk.Label(win, text="✓  Deletion complete",
                 font=("", 18, "bold"), bg=bg,
                 fg=success_color).pack(padx=pad, pady=(20, 6))

        tk.Label(win,
                 text=f"{count} similar {noun} deleted\nSpace recovered: {recovered_str}",
                 font=("", 13), bg=bg,
                 fg=theme_color("base.foreground"),
                 justify="center").pack(padx=pad, pady=(0, 24))

        tk.Frame(win, height=1, bg="#2d3748").pack(fill="x")

        btn_row = tk.Frame(win, bg=bg)
        btn_row.pack(fill="x", padx=pad, pady=(14, pad))

        def _rescan() -> None:
            self.result = "rescan"
            win.destroy()

        def _ok() -> None:
            self.result = "ok"
            win.destroy()

        tk.Button(
            btn_row, text="Rescan", command=_rescan,
            font=("", 11), relief="flat", padx=14, pady=7,
            bg=theme_color("button.secondary"),
            fg=theme_color("base.foreground"), cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btn_row, text="OK", command=_ok,
            font=("", 11, "bold"), relief="flat", padx=28, pady=7,
            bg=theme_color("button.primary"),
            fg="#ffffff", cursor="hand2",
        ).pack(side="right")

        win.update_idletasks()
        win.minsize(400, 1)
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - win.winfo_width()) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{px}+{py}")
        win.grab_set()
        parent.wait_window(win)


class DeleteCelebrationOverlay:
    """
    Full-window overlay shown after a clean delete.

    Displays a thumbs-up + "No duplicate <noun> remain!" message for
    DELAY_MS milliseconds, then calls on_done() to return to the welcome screen.
    """

    DELAY_MS = 7000

    def __init__(self, parent, *, noun: str, on_done: Callable[[], None]):
        self._parent = parent
        self._on_done = on_done

        win = tk.Toplevel(parent)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        parent.update_idletasks()
        w = parent.winfo_width()
        h = parent.winfo_height()
        x = parent.winfo_rootx()
        y = parent.winfo_rooty()
        win.geometry(f"{w}x{h}+{x}+{y}")

        bg = theme_color("base.backgroundElevated")
        win.configure(bg=bg)

        outer = tk.Frame(win, bg=bg)
        outer.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(outer, text="👍", font=("", 80),
                 bg=bg).pack(pady=(0, 20))

        tk.Label(outer,
                 text=f"No duplicate {noun} remain!",
                 font=("", 24, "bold"), bg=bg,
                 fg=theme_color("feedback.success")).pack(pady=(0, 10))

        tk.Label(outer, text="Your collection is clean.",
                 font=("", 14), bg=bg,
                 fg=theme_color("base.foregroundSecondary")).pack()

        self._win = win
        self._after_id = parent.after(self.DELAY_MS, self._finish)

    def _finish(self) -> None:
        try:
            self._win.destroy()
        except tk.TclError:
            pass
        try:
            self._on_done()
        except Exception:
            pass


class GroupDeleteDialog:
    """Shown when a group header row is selected and DELETE is clicked.

    Offers a single safe action: keep the largest copy and trash the rest.
    result: ``"keep_one"`` | ``"cancel"``
    """

    def __init__(self, parent, *, group) -> None:
        self.result: str = "cancel"

        n_files = len(group.files)
        try:
            reclaimable_str = format_bytes(int(group.reclaimable), decimals=1)
        except Exception:
            reclaimable_str = f"{group.reclaimable} bytes"

        try:
            import customtkinter as _ctk
            win = _ctk.CTkToplevel(parent)
            win.configure(fg_color=theme_color("base.backgroundElevated"))
        except Exception:
            win = tk.Toplevel(parent)
            win.configure(bg=theme_color("base.backgroundElevated"))

        self._win = win
        win.title("Delete Duplicate Group")
        win.resizable(False, False)
        win.transient(parent)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        bg = theme_color("base.backgroundElevated")
        pad = 24

        header = tk.Frame(win, bg=bg)
        header.pack(fill="x", padx=pad, pady=(pad, 0))
        tk.Label(header, text="🗂", font=("", 26),
                 bg=bg, fg=theme_color("base.foreground")).pack(side="left", padx=(0, 12))
        tk.Label(header, text=f"Delete Group #{group.group_id}?",
                 font=("", 15, "bold"), bg=bg, fg=theme_color("base.foreground"),
                 justify="left", wraplength=340).pack(side="left")

        body = (
            f"This group has {n_files} copies of the same file.\n"
            f"The largest copy will be kept; the other {n_files - 1} "
            f"will be moved to the Recycle Bin, freeing {reclaimable_str}."
        )
        tk.Label(win, text=body, font=("", 11), bg=bg,
                 fg=theme_color("base.foregroundSecondary"),
                 justify="left", wraplength=420, anchor="w").pack(
            fill="x", padx=pad, pady=(12, 20))

        tk.Frame(win, height=1, bg="#2d3748").pack(fill="x")

        btn_row = tk.Frame(win, bg=bg)
        btn_row.pack(fill="x", padx=pad, pady=(12, pad))

        def _keep_one() -> None:
            self.result = "keep_one"
            win.destroy()

        def _cancel() -> None:
            self.result = "cancel"
            win.destroy()

        tk.Button(btn_row, text="Cancel", command=_cancel,
                  font=("", 11), relief="flat", padx=16, pady=6,
                  bg=theme_color("button.secondary"),
                  fg=theme_color("base.foreground"),
                  cursor="hand2").pack(side="right", padx=(8, 0))

        tk.Button(btn_row, text="Keep Best — Delete Duplicates", command=_keep_one,
                  font=("", 11, "bold"), relief="flat", padx=16, pady=6,
                  bg=theme_color("button.danger"), fg="#ffffff",
                  cursor="hand2").pack(side="right")

        win.update_idletasks()
        win.minsize(480, 1)
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - win.winfo_width()) // 2)
        py = parent.winfo_rooty() + max(0, (parent.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{px}+{py}")
        win.grab_set()
        parent.wait_window(win)


# --- Backward-compatible aliases for delete_flow (underscore-prefixed names) ---
_DeleteDialog = DeleteConfirmDialog
_DeleteProgressDialog = DeleteProgressDialog
_DeleteSummaryDialog = DeleteSummaryDialog
_DeleteCelebration = DeleteCelebrationOverlay
_UndoToast = UndoToast
_delete_media_label = delete_media_label
_delete_breakdown = delete_breakdown
