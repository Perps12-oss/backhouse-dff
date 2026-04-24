"""
AppShell — top-level CTk window for CEREBRO (FINAL PLAN v2.0).

Navigation (FIXED — §1.1): Dashboard, Duplicates, History, Settings
Global Advanced Toggle (§1.2): in title bar
Layout (top to bottom):
  TitleBar   (32 px)
  TabBar     (36 px) + AdvancedToggle
  Page area  (remaining height — 4 pages, one shown at a time)
"""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Any, Callable, Dict, Optional

_log = logging.getLogger(__name__)

try:
    import customtkinter as ctk
    CTk      = ctk.CTk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
except ImportError:
    CTk      = tk.Tk       # type: ignore[misc,assignment]
    CTkFrame = tk.Frame    # type: ignore[misc,assignment]
    CTkLabel = tk.Label    # type: ignore[misc,assignment]

from cerebro.v2.ui.title_bar       import TitleBar
from cerebro.v2.ui.tab_bar         import TabBar
from cerebro.v2.ui.advanced_toggle import AdvancedToggle
from cerebro.v2.ui.dashboard_page  import DashboardPage
from cerebro.v2.ui.duplicates_page import DuplicatesPage
from cerebro.v2.ui.history_page    import HistoryPage
from cerebro.v2.ui.settings_page   import SettingsPage
from cerebro.v2.ui.a11y import apply_focus_ring, first_focusable_descendant
from cerebro.v2.ui.theme_applicator import ThemeApplicator
from cerebro.engines.orchestrator   import ScanOrchestrator
from cerebro.v2.coordinator         import CerebroCoordinator
from cerebro.v2.state import (
    Action,
    AdvancedModeToggled,
    AppState,
    ResultsFilesRemoved,
    ScanCompleted,
    StateStore,
    create_initial_state,
)

from cerebro.v2.state.actions import (
    ScanStarted,
    ScanEnded,
    ReviewNavigate,
)

_PAGE_BG_FALLBACK = "#F0F0F0"


class AppShell(CTk):
    """Root window for the CEREBRO UI (FINAL PLAN v2.0)."""

    def __init__(self) -> None:
        super().__init__()
        self._bootstrap_tkdnd()
        self._orchestrator = ScanOrchestrator()
        self._store = StateStore(create_initial_state())
        self._coordinator = CerebroCoordinator(self._store)
        self._setup_window()
        self._build_ui()

    def _bootstrap_tkdnd(self) -> None:
        try:
            from tkinterdnd2 import TkinterDnD
            self.TkdndVersion = TkinterDnD._require(self)
        except Exception as e:
            _log.debug("tkinterdnd2 unavailable, drag-and-drop disabled: %s", e)

    def _setup_window(self) -> None:
        self.title("CEREBRO")
        self.geometry("1100x700")
        self.minsize(800, 520)
        try:
            import customtkinter as _ctk
            _ctk.set_default_color_theme("blue")
        except (ImportError, AttributeError):
            pass
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_ui(self) -> None:
        ThemeApplicator.get().set_root(self)
        toks0 = ThemeApplicator.get().build_tokens()
        skip_bg = toks0.get("bg", _PAGE_BG_FALLBACK)

        # Skip-to-content link for accessibility
        self._skip_bar = tk.Frame(self, bg=skip_bg, height=30)
        self._skip_bar.pack(fill="x")
        self._skip_bar.pack_propagate(False)
        self._skip_btn = tk.Button(
            self._skip_bar,
            text="Skip to main content",
            command=self._focus_main_content,
            bg=skip_bg,
            fg=toks0.get("fg2", "#555555"),
            activebackground=skip_bg,
            activeforeground=toks0.get("fg", "#111111"),
            relief="flat",
            font=("Segoe UI", 9, "underline"),
            cursor="hand2",
            padx=8,
            pady=3,
        )
        self._skip_btn.pack(side="left", padx=6, pady=2)
        apply_focus_ring(
            self._skip_btn,
            focus_color=toks0.get("focus_ring", toks0.get("accent", "#2563EB")),
        )

        # Title bar
        self._title_bar = TitleBar(
            self,
            on_settings=self._open_settings,
            on_themes=self._open_themes,
        )
        self._title_bar.pack(fill="x")

        # Tab bar + Advanced toggle row
        nav_row = tk.Frame(self, bg=toks0.get("tab_bg", _PAGE_BG_FALLBACK))
        nav_row.pack(fill="x")

        self._tab_bar = TabBar(
            nav_row,
            on_tab_changed=self._on_main_bar_tab_request,
        )
        self._tab_bar.pack(side="left", fill="x", expand=True)

        self._advanced_toggle = AdvancedToggle(
            nav_row,
            on_toggle=self._on_advanced_toggle,
        )
        self._advanced_toggle.pack(side="right")

        # Page container
        self._page_container = CTkFrame(self, fg_color=_PAGE_BG_FALLBACK)
        self._page_container.pack(fill="both", expand=True)

        ThemeApplicator.get().register(self._apply_shell_theme)

        # Build pages (FINAL PLAN §1.1: Dashboard, Duplicates, History, Settings)
        self._pages: Dict[str, CTkFrame] = {}

        self._pages["dashboard"] = DashboardPage(
            self._page_container,
            on_start_scan=self._start_scan_from_dashboard,
            on_open_session=self._on_open_session,
            on_cancel_scan=self._cancel_scan_from_dashboard,
            store=self._store,
            coordinator=self._coordinator,
        )

        self._pages["duplicates"] = DuplicatesPage(
            self._page_container,
            on_open_group=self._on_open_group,
            on_navigate_home=lambda: self.switch_tab("dashboard"),
            on_rescan=self._rescan_from_duplicates,
            store=self._store,
            coordinator=self._coordinator,
        )

        self._pages["history"] = HistoryPage(
            self._page_container,
            on_session_click=self._on_history_session_click,
            store=self._store,
            coordinator=self._coordinator,
        )

        self._pages["settings"] = SettingsPage(
            self._page_container,
            store=self._store,
            coordinator=self._coordinator,
        )

        self._current_page: str = "dashboard"
        self._pages["dashboard"].place(relwidth=1, relheight=1)

        # State subscription
        self._store.subscribe(self._on_app_state_changed)

        # Apply initial theme
        ta = ThemeApplicator.get()
        initial_theme = "Cerebro Dark"
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            initial_theme = ThemeEngineV3.get().active_theme_name or "Cerebro Dark"
        except Exception:
            pass
        ta.apply(initial_theme, self)

    # ------------------------------------------------------------------
    # Shell chrome theming
    # ------------------------------------------------------------------

    def _apply_shell_theme(self, t: dict) -> None:
        bg = t.get("bg", _PAGE_BG_FALLBACK)
        try:
            self._skip_bar.configure(bg=bg)
            self._skip_btn.configure(
                bg=bg,
                fg=t.get("fg2", "#555555"),
                activebackground=bg,
                activeforeground=t.get("fg", "#111111"),
            )
        except (tk.TclError, AttributeError):
            pass
        apply_focus_ring(
            self._skip_btn,
            focus_color=t.get("focus_ring", t.get("accent", "#2563EB")),
        )
        try:
            self.configure(fg_color=bg)
        except (tk.TclError, AttributeError):
            try:
                self.configure(bg=bg)
            except tk.TclError:
                pass
        try:
            self._page_container.configure(fg_color=bg)
        except (tk.TclError, AttributeError):
            try:
                self._page_container.configure(bg=bg)
            except tk.TclError:
                pass

    def _focus_main_content(self) -> None:
        s = self._store.get_state()
        page = self._pages.get(s.active_tab)
        if page is not None:
            t = first_focusable_descendant(page)
            if t is not None:
                try:
                    t.focus_set()
                except (tk.TclError, AttributeError):
                    self._tab_bar.focus_active_tab()
            else:
                self._tab_bar.focus_active_tab()
        else:
            self._tab_bar.focus_active_tab()

    # ------------------------------------------------------------------
    # Tab switching (store is the only navigation source)
    # ------------------------------------------------------------------

    def _on_main_bar_tab_request(self, key: str) -> None:
        self._coordinator.set_active_tab(key)

    def _apply_visible_page(self, key: str) -> None:
        if key == self._current_page:
            return
        self._pages[self._current_page].place_forget()
        self._current_page = key
        self._pages[key].place(relwidth=1, relheight=1)
        page = self._pages[key]
        if hasattr(page, "on_show"):
            page.on_show()

    def _sync_chrome_to_state(self, s: AppState) -> None:
        self._tab_bar.set_active_key(s.active_tab)
        self._apply_visible_page(s.active_tab)

    def switch_tab(self, key: str) -> None:
        self._coordinator.set_active_tab(key)

    # ------------------------------------------------------------------
    # Advanced toggle (FINAL PLAN §1.2)
    # ------------------------------------------------------------------

    def _on_advanced_toggle(self, value: bool) -> None:
        self._coordinator.toggle_advanced(value)
        for page in self._pages.values():
            if hasattr(page, "set_advanced"):
                page.set_advanced(value)

    # ------------------------------------------------------------------
    # Title bar actions
    # ------------------------------------------------------------------

    def _open_settings(self, anchor: Optional[tk.Widget] = None) -> None:
        self.switch_tab("settings")

    def _open_themes(self, anchor: Optional[tk.Widget] = None) -> None:
        if hasattr(self, "_themes_win") and self._themes_win is not None:
            try:
                if self._themes_win.winfo_exists():
                    closer = getattr(self._themes_win, "_close", None)
                    if callable(closer):
                        closer()
                    else:
                        self._themes_win.destroy()
            except (tk.TclError, AttributeError):
                try:
                    self._themes_win.destroy()
                except tk.TclError:
                    pass
            self._themes_win = None
        anchor_widget = anchor or self._title_bar.get_themes_anchor()
        try:
            self._themes_win = _ThemeQuickDropdown(
                self,
                anchor=anchor_widget,
                on_pick=self.switch_theme,
            )
        except Exception as e:
            _log.warning("Theme dropdown error: %s", e)

    def switch_theme(self, theme_name: str) -> None:
        ThemeApplicator.get().apply(theme_name, self)

    # ------------------------------------------------------------------
    # Scan flow
    # ------------------------------------------------------------------

    def _start_scan_from_dashboard(self, folders: list = (), mode: str = "files") -> None:
        if not folders:
            return
        self._coordinator.scan_started(mode)
        self._run_scan_inline(list(folders), mode)

    def _cancel_scan_from_dashboard(self) -> None:
        try:
            self._orchestrator.cancel()
        except Exception:
            pass

    def _rescan_from_duplicates(self) -> None:
        self.switch_tab("dashboard")
        dash = self._pages.get("dashboard")
        if dash is not None and hasattr(dash, "enter_config"):
            self.after(50, dash.enter_config)

    def _run_scan_inline(self, folders: list, mode: str) -> None:
        import threading
        from pathlib import Path

        orchestrator = self._orchestrator
        orchestrator.set_mode(mode)

        def _progress_cb(p) -> None:
            self.after(0, lambda: self._coordinator.report_scan_progress(p))

        def _worker() -> None:
            try:
                orchestrator.start_scan(
                    [Path(f) for f in folders], [], {}, _progress_cb
                )
                # start_scan is async; poll until the engine finishes
                import time
                from cerebro.engines.base_engine import ScanState
                while True:
                    prog = orchestrator.get_progress()
                    if prog.state in (ScanState.COMPLETED, ScanState.CANCELLED, ScanState.ERROR):
                        break
                    time.sleep(0.1)
                prog = orchestrator.get_progress()
                if prog.state == ScanState.COMPLETED:
                    groups = orchestrator.get_results()
                    self.after(0, lambda: self._coordinator.scan_completed(groups, mode))
                    self.after(0, lambda: self.switch_tab("duplicates"))
                else:
                    self.after(0, lambda: self._coordinator.scan_ended("cancelled"))
            except Exception as e:
                _log.exception("Scan error: %s", e)
                self.after(0, lambda: self._coordinator.scan_ended("error"))

        threading.Thread(target=_worker, daemon=True, name="scan-worker").start()

    # ------------------------------------------------------------------
    # State change handler
    # ------------------------------------------------------------------

    def _on_app_state_changed(self, s: AppState, _old: AppState, action: Action) -> None:
        if isinstance(action, ScanCompleted):
            self._apply_scan_completed(s)
        elif isinstance(action, ResultsFilesRemoved):
            self._apply_results_files_removed(s)

        self._sync_chrome_to_state(s)

    def _apply_scan_completed(self, s: AppState) -> None:
        results = s.groups
        mode = s.scan_mode
        if hasattr(self._pages["duplicates"], "load_results"):
            self._pages["duplicates"].load_results(results, mode=mode)
        dup_count = sum(max(0, len(g.files) - 1) for g in results if hasattr(g, "files"))
        self.set_results_badge(dup_count)
        try:
            if hasattr(self._pages["dashboard"], "refresh"):
                self._pages["dashboard"].refresh()
        except (AttributeError, tk.TclError):
            pass

    def _apply_results_files_removed(self, s: AppState) -> None:
        results = s.groups
        mode = s.scan_mode
        if hasattr(self._pages["duplicates"], "load_results"):
            self._pages["duplicates"].load_results(results, mode=mode)
        dup_count = sum(max(0, len(g.files) - 1) for g in results if hasattr(g, "files"))
        self.set_results_badge(dup_count)

    def _on_open_group(self, group_id: int, groups: list) -> None:
        pass

    def _on_open_session(self, session) -> None:
        from tkinter import messagebox
        from cerebro.v2.persistence import (
            load_last_scan_snapshot,
            load_scan_results_for_session_timestamp,
        )

        if session is None:
            messagebox.showinfo("No session", "There is no recent scan to open.", parent=self)
            return
        try:
            ts = float(getattr(session, "timestamp", 0) or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        by_ts = load_scan_results_for_session_timestamp(ts)
        if by_ts is not None:
            groups, mode = by_ts
        else:
            last = load_last_scan_snapshot()
            if last is None:
                messagebox.showinfo("No saved results", "Run a scan at least once.", parent=self)
                return
            groups, mode, snap_ts = last[0], last[1], last[2]
            if ts and abs(snap_ts - ts) > 2.0:
                messagebox.showinfo("Not on disk", "Only the most recent scan is kept in full.", parent=self)
                return
        if not groups:
            messagebox.showinfo("No results", "Saved session had no duplicates.", parent=self)
            return
        self._coordinator.scan_completed(list(groups), mode)
        self.switch_tab("duplicates")

    def _on_history_session_click(self, entry) -> None:
        self.switch_tab("duplicates")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def replace_page(self, key: str, frame: CTkFrame) -> None:
        old = self._pages.get(key)
        if old is not None:
            old.place_forget()
            try:
                old.destroy()
            except tk.TclError:
                pass
        self._pages[key] = frame
        if self._current_page == key:
            frame.place(relwidth=1, relheight=1)

    def set_results_badge(self, count: int) -> None:
        self._tab_bar.set_results_badge(count)

    def enable_review_tab(self) -> None:
        pass

    def disable_review_tab(self) -> None:
        pass

    def run(self) -> None:
        self.mainloop()


def run_app() -> None:
    app = AppShell()
    app.run()


# ---------------------------------------------------------------------------
# Theme Quick Dropdown (preserved from original)
# ---------------------------------------------------------------------------

class _ThemeQuickDropdown(tk.Toplevel):
    """Lightweight one-click theme picker anchored under the title-bar link."""

    ROW_H = 26
    WIDTH = 220
    MAX_VISIBLE = 14

    def __init__(
        self,
        master: tk.Misc,
        anchor: Optional[tk.Widget],
        on_pick: Callable[[str], None],
        **kw,
    ) -> None:
        super().__init__(master, **kw)
        self._on_pick = on_pick
        self._master  = master
        self._outside_bind_id: Optional[str] = None
        self._dismissed = False
        self._after_topmost_id: Optional[Any] = None
        self._after_guard_id: Optional[Any] = None
        self.overrideredirect(True)

        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            engine = ThemeEngineV3.get()
            self._names = engine.all_theme_names()
            self._active = engine.active_theme_name
        except Exception:
            self._names = []
            self._active = ""

        tokens = ThemeApplicator.get().build_tokens()
        self._bg      = tokens.get("bg2", "#1C2333")
        self._fg      = tokens.get("fg", "#E6EDF3")
        self._fg_mute = tokens.get("fg2", "#8B949E")
        self._hover   = tokens.get("bg3", "#161B22")
        self._accent  = tokens.get("accent", "#22D3EE")
        self._border  = tokens.get("border", "#30363D")

        self.configure(bg=self._border)

        self._build()
        self._place_under(anchor)

        try:
            self.lift()
            self.attributes("-topmost", True)
            self._after_topmost_id = self.after(200, self._deferred_clear_topmost)
        except tk.TclError:
            pass

        self.bind("<Escape>", lambda _e: self._close())
        self._after_guard_id = self.after(0, self._install_outside_click_guard)

    def _build(self) -> None:
        outer = tk.Frame(self, bg=self._border)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        canvas = tk.Canvas(outer, bg=self._bg, highlightthickness=0, bd=0,
                           width=self.WIDTH - 2)
        vsb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=self._bg)
        win   = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _cfg(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _resize(e):
            canvas.itemconfig(win, width=e.width)
        inner.bind("<Configure>", _cfg)
        canvas.bind("<Configure>", _resize)
        canvas.bind(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        for name in self._names:
            self._make_row(inner, name)

    def _make_row(self, parent: tk.Widget, name: str) -> None:
        is_active = name == self._active
        row = tk.Frame(parent, bg=self._bg, height=self.ROW_H, cursor="hand2")
        row.pack(fill="x")
        row.pack_propagate(False)

        check = tk.Label(
            row,
            text="\u2713" if is_active else " ",
            bg=self._bg, fg=self._accent,
            font=("Segoe UI", 10, "bold"),
            width=2, anchor="center",
        )
        check.pack(side="left", padx=(4, 0))

        lbl = tk.Label(
            row, text=name,
            bg=self._bg,
            fg=self._fg if is_active else self._fg_mute,
            font=("Segoe UI", 10, "bold") if is_active else ("Segoe UI", 10),
            anchor="w",
        )
        lbl.pack(side="left", fill="x", expand=True, padx=(2, 8))

        def _enter(_e=None, r=row, l=lbl, c=check):
            r.configure(bg=self._hover)
            l.configure(bg=self._hover, fg=self._fg)
            c.configure(bg=self._hover)
        def _leave(_e=None, r=row, l=lbl, c=check, active=is_active):
            r.configure(bg=self._bg)
            l.configure(bg=self._bg, fg=self._fg if active else self._fg_mute)
            c.configure(bg=self._bg)
        def _click(_e=None, n=name):
            self._pick(n)

        for w in (row, check, lbl):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
            w.bind("<Button-1>", _click)

    def _place_under(self, anchor: Optional[tk.Widget]) -> None:
        visible_rows = min(len(self._names), self.MAX_VISIBLE)
        visible_rows = max(1, visible_rows)
        height = visible_rows * self.ROW_H + 2

        if anchor is not None and anchor.winfo_exists():
            try:
                anchor.update_idletasks()
                x = anchor.winfo_rootx()
                y = anchor.winfo_rooty() + anchor.winfo_height() + 4
            except tk.TclError:
                x = self.master.winfo_rootx() + 40
                y = self.master.winfo_rooty() + 40
        else:
            x = self.master.winfo_rootx() + 40
            y = self.master.winfo_rooty() + 40

        try:
            screen_w = self.winfo_screenwidth()
            if x + self.WIDTH > screen_w - 4:
                x = max(4, screen_w - self.WIDTH - 4)
            if x < 4:
                x = 4
        except tk.TclError:
            pass

        self.geometry(f"{self.WIDTH}x{height}+{x}+{y}")
        self.update_idletasks()

    def _deferred_clear_topmost(self) -> None:
        self._after_topmost_id = None
        self._safe_topmost(False)

    def _safe_topmost(self, flag: bool) -> None:
        try:
            if self.winfo_exists():
                self.attributes("-topmost", flag)
        except tk.TclError:
            pass

    def _cancel_pending_after(self) -> None:
        for attr in ("_after_topmost_id", "_after_guard_id"):
            aid = getattr(self, attr, None)
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except (tk.TclError, ValueError):
                    pass
                setattr(self, attr, None)

    def _focus_back_to_master(self) -> None:
        try:
            m = self._master
            if m is not None and m.winfo_exists():
                m.focus_set()
        except (tk.TclError, AttributeError):
            pass

    def _install_outside_click_guard(self) -> None:
        if self._dismissed:
            return
        try:
            self._outside_bind_id = self._master.bind(
                "<Button-1>", self._on_outside_click, add="+",
            )
        except tk.TclError:
            self._outside_bind_id = None

    def _on_outside_click(self, event) -> None:
        if self._dismissed:
            return
        w = event.widget
        try:
            path = str(w)
            if path.startswith(str(self)):
                return
        except Exception:
            pass
        self._close()

    def _pick(self, name: str) -> None:
        self._close()
        try:
            self._on_pick(name)
        except Exception as e:
            _log.warning("Theme pick error: %s", e)

    def _close(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self._cancel_pending_after()
        self._focus_back_to_master()
        try:
            if self._outside_bind_id is not None:
                self._master.unbind("<Button-1>", self._outside_bind_id)
        except tk.TclError:
            pass
        self._outside_bind_id = None
        try:
            self.destroy()
        except tk.TclError:
            pass
