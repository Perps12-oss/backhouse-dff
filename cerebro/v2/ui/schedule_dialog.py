"""Schedule Dialog — add/remove/toggle background scan schedules."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING, List, Optional

from cerebro.v2.core.theme_bridge_v2 import theme_color

if TYPE_CHECKING:
    from cerebro.core.scheduler import CerebroScheduler, ScheduledJob

try:
    import customtkinter as ctk
    CTkToplevel = ctk.CTkToplevel
    CTkFrame    = ctk.CTkFrame
    CTkButton   = ctk.CTkButton
    CTkLabel    = ctk.CTkLabel
    CTkEntry    = ctk.CTkEntry
except ImportError:
    CTkToplevel = tk.Toplevel      # type: ignore[misc,assignment]
    CTkFrame    = tk.Frame         # type: ignore[misc,assignment]
    CTkButton   = tk.Button        # type: ignore[misc,assignment]
    CTkLabel    = tk.Label         # type: ignore[misc,assignment]
    CTkEntry    = tk.Entry         # type: ignore[misc,assignment]

_MODES = ["files", "photos", "music", "large_files", "empty_folders"]
_COL_IDS  = ("label", "folders", "mode", "every", "enabled", "last_run", "next_run")
_COL_HDRS = ("Label",  "Folders", "Mode", "Every (h)", "On?",  "Last Run",  "Next Run")
_COL_W    = (120,       200,       80,     70,           40,     130,         130)


def _fmt_ts(ts: Optional[float]) -> str:
    if ts is None:
        return "—"
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class ScheduleDialog(CTkToplevel):
    """Modal dialog for managing scheduled background scans."""

    def __init__(self, parent: tk.Misc, scheduler: "CerebroScheduler") -> None:
        super().__init__(parent)
        self._parent    = parent
        self._scheduler = scheduler
        self._setup_window()
        self._build_ui()
        self._refresh_tree()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.title("Scheduled Scans")
        self.geometry("780x420")
        self.resizable(True, True)
        self.transient(self._parent)
        self.grab_set()
        self.update_idletasks()
        x = self._parent.winfo_x() + (self._parent.winfo_width()  // 2) - 390
        y = self._parent.winfo_y() + (self._parent.winfo_height() // 2) - 210
        self.geometry(f"780x420+{x}+{y}")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        try:
            bg  = theme_color("base.background")
            fg  = theme_color("base.foreground")
            bg2 = theme_color("base.backgroundSecondary")
        except Exception:
            bg = fg = bg2 = ""

        # Title label
        title_lbl = CTkLabel(self, text="Scheduled Scans")
        try:
            title_lbl.configure(
                font=("Segoe UI", 14, "bold"),
                text_color=fg or None,
            )
        except Exception:
            pass
        title_lbl.pack(fill="x", padx=12, pady=(10, 4))

        # Treeview frame
        tree_frame = tk.Frame(self, bg=bg or None)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=4)

        style = ttk.Style()
        try:
            style.configure(
                "Schedule.Treeview",
                background=bg2 or "#F0F0F0",
                foreground=fg or "#000000",
                fieldbackground=bg2 or "#F0F0F0",
                rowheight=24,
            )
            style.configure("Schedule.Treeview.Heading", font=("Segoe UI", 9, "bold"))
        except Exception:
            pass

        vsb = ttk.Scrollbar(tree_frame, orient="vertical")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal")

        self._tree = ttk.Treeview(
            tree_frame,
            columns=_COL_IDS,
            show="headings",
            selectmode="browse",
            style="Schedule.Treeview",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )
        vsb.configure(command=self._tree.yview)
        hsb.configure(command=self._tree.xview)

        for col_id, hdr, w in zip(_COL_IDS, _COL_HDRS, _COL_W):
            self._tree.heading(col_id, text=hdr)
            self._tree.column(col_id, width=w, minwidth=40, stretch=(col_id == "folders"))

        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)

        # Toolbar
        toolbar = tk.Frame(self, bg=bg or None)
        toolbar.pack(fill="x", padx=12, pady=(4, 10))

        btn_cfg: dict = dict(width=90, height=28)
        try:
            btn_cfg["font"] = ("Segoe UI", 10)
            btn_cfg["fg_color"]   = theme_color("button.secondary")
            btn_cfg["hover_color"] = theme_color("button.secondaryHover")
            btn_cfg["corner_radius"] = 4
        except Exception:
            pass

        add_btn = CTkButton(toolbar, text="+ Add",   command=self._on_add,    **btn_cfg)
        rem_btn = CTkButton(toolbar, text="✕ Remove", command=self._on_remove, **btn_cfg)
        tog_btn = CTkButton(toolbar, text="Toggle",  command=self._on_toggle,  **btn_cfg)
        cls_btn = CTkButton(toolbar, text="Close",   command=self.destroy,     **btn_cfg)

        add_btn.pack(side="left", padx=(0, 4))
        rem_btn.pack(side="left", padx=4)
        tog_btn.pack(side="left", padx=4)
        cls_btn.pack(side="right")

    # ------------------------------------------------------------------
    # Tree helpers
    # ------------------------------------------------------------------

    def _refresh_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for job in self._scheduler.list_jobs():
            folders_str = "; ".join(job.folders) if job.folders else "—"
            self._tree.insert(
                "",
                "end",
                iid=str(job.id),
                values=(
                    job.label,
                    folders_str,
                    job.mode,
                    f"{job.interval_hours:g}",
                    "Yes" if job.enabled else "No",
                    _fmt_ts(job.last_run),
                    _fmt_ts(job.next_run),
                ),
            )

    def _selected_job_id(self) -> Optional[int]:
        sel = self._tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except (ValueError, IndexError):
            return None

    # ------------------------------------------------------------------
    # Toolbar handlers
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        dlg = _AddJobDialog(self)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        label, folder, mode, interval_h = dlg.result
        self._scheduler.add_job(label, [folder] if folder else [], mode, interval_h)
        self._refresh_tree()

    def _on_remove(self) -> None:
        job_id = self._selected_job_id()
        if job_id is None:
            return
        self._scheduler.remove_job(job_id)
        self._refresh_tree()

    def _on_toggle(self) -> None:
        job_id = self._selected_job_id()
        if job_id is None:
            return
        iid = str(job_id)
        vals = self._tree.item(iid, "values")
        if not vals:
            return
        currently_enabled = str(vals[4]).strip().lower() == "yes"
        self._scheduler.toggle_job(job_id, not currently_enabled)
        self._refresh_tree()


# ---------------------------------------------------------------------------
# Sub-dialog: Add Job
# ---------------------------------------------------------------------------

class _AddJobDialog(tk.Toplevel):
    """Small modal to collect new-job parameters."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.result: Optional[tuple] = None
        self._parent = parent
        self.title("Add Scheduled Scan")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._build()
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width()  // 2) - 200
        y = parent.winfo_y() + (parent.winfo_height() // 2) - 140
        self.geometry(f"400x280+{x}+{y}")

    def _build(self) -> None:
        try:
            bg = theme_color("base.background")
            fg = theme_color("base.foreground")
        except Exception:
            bg = fg = ""

        pad = dict(padx=12, pady=4)

        # Label
        tk.Label(self, text="Label:", anchor="w", bg=bg or None, fg=fg or None).pack(fill="x", **pad)
        self._label_var = tk.StringVar(value="My Schedule")
        tk.Entry(self, textvariable=self._label_var).pack(fill="x", padx=12)

        # Folder
        tk.Label(self, text="Folder:", anchor="w", bg=bg or None, fg=fg or None).pack(fill="x", **pad)
        folder_frame = tk.Frame(self, bg=bg or None)
        folder_frame.pack(fill="x", padx=12)
        self._folder_var = tk.StringVar()
        folder_entry = tk.Entry(folder_frame, textvariable=self._folder_var)
        folder_entry.pack(side="left", fill="x", expand=True)
        tk.Button(
            folder_frame,
            text="Browse…",
            command=self._browse,
            relief="flat",
            cursor="hand2",
        ).pack(side="left", padx=(4, 0))

        # Mode
        tk.Label(self, text="Mode:", anchor="w", bg=bg or None, fg=fg or None).pack(fill="x", **pad)
        self._mode_var = tk.StringVar(value=_MODES[0])
        tk.OptionMenu(self, self._mode_var, *_MODES).pack(fill="x", padx=12)

        # Interval
        tk.Label(self, text="Interval (hours, 1–168):", anchor="w", bg=bg or None, fg=fg or None).pack(fill="x", **pad)
        self._interval_var = tk.StringVar(value="24")
        spinbox = tk.Spinbox(
            self,
            from_=1, to=168, increment=1,
            textvariable=self._interval_var,
            width=6,
        )
        spinbox.pack(anchor="w", padx=12)

        # Buttons
        btn_row = tk.Frame(self, bg=bg or None)
        btn_row.pack(fill="x", padx=12, pady=(12, 8))
        tk.Button(btn_row, text="OK",     command=self._on_ok,     relief="flat", cursor="hand2", width=8).pack(side="right", padx=(4, 0))
        tk.Button(btn_row, text="Cancel", command=self._on_cancel, relief="flat", cursor="hand2", width=8).pack(side="right")

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title="Select Folder")
        if chosen:
            self._folder_var.set(chosen)

    def _on_ok(self) -> None:
        label = self._label_var.get().strip() or "Schedule"
        folder = self._folder_var.get().strip()
        mode = self._mode_var.get()
        try:
            interval_h = float(self._interval_var.get())
            interval_h = max(1.0, min(168.0, interval_h))
        except ValueError:
            interval_h = 24.0
        self.result = (label, folder, mode, interval_h)
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()
