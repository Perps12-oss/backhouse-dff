"""
AppShell — new top-level CTk window for the CEREBRO UI overhaul.

Layout (top to bottom):
  TitleBar   (32 px, #0B1929)
  TabBar     (36 px, #F0F0F0)
  Page area  (remaining height — 6 CTkFrames stacked, one shown at a time)

Phase 1 ships placeholder content for all 6 tabs.
Later phases call replace_page(key, real_frame) to fill each slot.
"""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, Dict, Optional

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
from cerebro.v2.ui.welcome_page    import WelcomePage
from cerebro.v2.ui.scan_page       import ScanPage
from cerebro.v2.ui.results_page    import ResultsPage
from cerebro.v2.ui.review_page      import ReviewPage
from cerebro.v2.ui.history_page     import HistoryPage
from cerebro.v2.ui.diagnostics_page import DiagnosticsPage
from cerebro.v2.ui.theme_applicator import ThemeApplicator
from cerebro.engines.orchestrator   import ScanOrchestrator

_PAGE_BG_FALLBACK = "#F0F0F0"


class AppShell(CTk):
    """
    Root window for the CEREBRO UI overhaul.

    Phase 1 deliverable: TitleBar + TabBar + 6 switchable placeholder pages.
    """

    def __init__(self) -> None:
        super().__init__()
        self._bootstrap_tkdnd()
        self._orchestrator = ScanOrchestrator()
        self._setup_window()
        self._build_ui()

    def _bootstrap_tkdnd(self) -> None:
        # tkinterdnd2 monkey-patches drop_target_register / dnd_bind onto
        # tkinter.BaseWidget at import time, but those methods only succeed
        # once the native tkdnd Tcl package has been loaded into this
        # interpreter. TkinterDnD.Tk does that inside its __init__; since
        # AppShell subclasses CTk (which does not), we load it here so that
        # any descendant widget can become a drop target.
        try:
            from tkinterdnd2 import TkinterDnD
            self.TkdndVersion = TkinterDnD._require(self)
        except Exception as e:
            _log.debug("tkinterdnd2 unavailable, drag-and-drop disabled: %s", e)

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Register root with ThemeApplicator so any caller (Settings dialog,
        # quick dropdown, etc.) can trigger a global re-dispatch without
        # threading a reference all the way through.
        ThemeApplicator.get().set_root(self)

        self._title_bar = TitleBar(
            self,
            on_settings=self._open_settings,
            on_themes=self._open_themes,
        )
        self._title_bar.pack(fill="x")

        self._tab_bar = TabBar(self, on_tab_changed=self._on_tab_changed)
        self._tab_bar.pack(fill="x")

        self._page_container = CTkFrame(self, fg_color=_PAGE_BG_FALLBACK)
        self._page_container.pack(fill="both", expand=True)

        # Re-paint shell chrome (root window + page container) whenever the
        # theme changes so no surface is left at the hard-coded fallback color.
        ThemeApplicator.get().register(self._apply_shell_theme)

        self._pages: Dict[str, CTkFrame] = {}

        self._history_page = HistoryPage(
            self._page_container,
            on_session_click=self._on_history_session_click,
        )
        self._pages["history"] = self._history_page

        self._diagnostics_page = DiagnosticsPage(self._page_container)
        self._pages["diagnostics"] = self._diagnostics_page

        self._review_page = ReviewPage(
            self._page_container,
            on_back=lambda: self.switch_tab("results"),
            on_navigate_results=lambda: self.switch_tab("results"),
            # Needed by Review's Smart-Select flow — it reuses the same
            # delete ceremony as Results, so both pages must agree on
            # where the user lands after a successful batch delete
            # (celebration → welcome) and after picking Rescan in the
            # summary dialog (→ scan).
            on_navigate_home=lambda: self.switch_tab("welcome"),
            on_rescan=lambda: self.switch_tab("scan"),
        )
        self._pages["review"] = self._review_page

        self._results_page = ResultsPage(
            self._page_container,
            on_open_group=self._on_open_group,
            on_navigate_home=lambda: self.switch_tab("welcome"),
            on_rescan=lambda: self.switch_tab("scan"),
        )
        self._pages["results"] = self._results_page

        self._pages["welcome"] = WelcomePage(
            self._page_container,
            on_start_scan=lambda: self.switch_tab("scan"),
            on_open_session=self._on_open_session,
        )

        self._pages["scan"] = ScanPage(
            self._page_container,
            orchestrator=self._orchestrator,
            on_scan_complete=self._on_scan_complete,
        )

        self._current_page: str = "welcome"
        self._pages["welcome"].place(relwidth=1, relheight=1)

        # Apply the initial theme globally. This also fires engine listeners,
        # syncs CTk appearance mode, and dispatches tokens to every shell hook.
        ta = ThemeApplicator.get()
        initial_theme = "Cerebro Dark"
        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            initial_theme = ThemeEngineV3.get().active_theme_name or "Cerebro Dark"
        except Exception:
            pass
        ta.apply(initial_theme, self)

    def _make_placeholder(self, key: str) -> CTkFrame:
        """Muted label placeholder shown until a later phase provides real content."""
        frame = CTkFrame(self._page_container, fg_color=_PAGE_BG_FALLBACK)
        CTkLabel(
            frame,
            text=key.upper(),
            font=("Segoe UI", 22, "bold"),
            text_color="#CCCCCC",
        ).place(relx=0.5, rely=0.5, anchor="center")
        return frame

    # ------------------------------------------------------------------
    # Shell chrome theming (root window + page container)
    # ------------------------------------------------------------------

    def _apply_shell_theme(self, t: dict) -> None:
        """Paint the root window and page container with the active theme."""
        bg = t.get("bg", _PAGE_BG_FALLBACK)
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

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------

    def _on_tab_changed(self, key: str) -> None:
        if key == self._current_page:
            return
        self._pages[self._current_page].place_forget()
        self._current_page = key
        self._pages[key].place(relwidth=1, relheight=1)
        # Notify pages that support lazy loading
        page = self._pages[key]
        if hasattr(page, "on_show"):
            page.on_show()

    def switch_tab(self, key: str) -> None:
        """Programmatically navigate to a tab (called by page widgets)."""
        self._tab_bar.switch_to(key)

    # ------------------------------------------------------------------
    # Title bar actions
    # ------------------------------------------------------------------

    def _open_settings(self, anchor: Optional[tk.Widget] = None) -> None:
        if hasattr(self, "_settings_win") and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        from cerebro.v2.ui.settings_dialog import SettingsDialog, Settings, get_settings_path
        self._settings_win = SettingsDialog(self, Settings.load(get_settings_path()))

    def _open_themes(self, anchor: Optional[tk.Widget] = None) -> None:
        """Open the one-click quick theme dropdown anchored to the title bar link."""
        if hasattr(self, "_themes_win") and self._themes_win is not None:
            try:
                if self._themes_win.winfo_exists():
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
        """Apply a theme globally through the single ThemeApplicator entry point."""
        ThemeApplicator.get().apply(theme_name, self)

    def _on_open_session(self, session) -> None:
        """Load a past session into the Results page and switch to it (Phase 4+)."""
        self.switch_tab("results")

    def _on_scan_complete(self, results: list, mode: str = "files") -> None:
        """Called by ScanPage when a scan finishes."""
        self._scan_results = results
        self._scan_mode    = mode or "files"
        self._results_page.load_results(results, mode=mode)
        # Seed Review with the same data in grid-mode so Smart Select
        # already has the full group set loaded if the user tabs over
        # directly. The compare mode only ever activates when the user
        # explicitly clicks a tile (or arrives via Results double-click).
        try:
            self._review_page.load_results(results, mode=mode)
        except Exception:   # pylint: disable=broad-except
            _log.exception("ReviewPage.load_results failed")
        dup_count = sum(max(0, len(g.files) - 1) for g in results)
        self.set_results_badge(dup_count)
        self.enable_review_tab()
        try:
            self._pages["welcome"].refresh()
        except (AttributeError, tk.TclError):
            pass
        self.switch_tab("results")

    def _on_open_group(self, group_id: int, groups: list) -> None:
        """Called when user double-clicks a group in Results — opens Review tab
        in compare mode pre-focused on that group. ``scan_mode`` is
        threaded through so Smart Select's delete ceremony dialogs use
        the right media noun."""
        mode = getattr(self, "_scan_mode", "files")
        self._review_page.load_group(groups, group_id, mode=mode)
        self.switch_tab("review")

    def _on_history_session_click(self, entry) -> None:
        self.switch_tab("results")

    # ------------------------------------------------------------------
    # Public API for later phases
    # ------------------------------------------------------------------

    def replace_page(self, key: str, frame: CTkFrame) -> None:
        """Swap a placeholder frame with real page content."""
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
        self._tab_bar.enable_review()

    def disable_review_tab(self) -> None:
        self._tab_bar.disable_review()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.mainloop()


def run_app() -> None:
    """Entry point for the overhauled CEREBRO app."""
    app = AppShell()
    app.run()


class _ThemeQuickDropdown(tk.Toplevel):
    """Lightweight one-click theme picker anchored under the title-bar link.

    Behavior:
      - Borderless popup (``overrideredirect``).
      - Scrollable list of theme names, current theme shown with a check mark.
      - Click a row -> apply theme globally and close.
      - Losing focus or pressing ``Escape`` closes without changes.
    """

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
        self.overrideredirect(True)

        try:
            from cerebro.core.theme_engine_v3 import ThemeEngineV3
            engine = ThemeEngineV3.get()
            self._names = engine.all_theme_names()
            self._active = engine.active_theme_name
        except Exception:
            self._names = []
            self._active = ""

        # Use current theme tokens so the dropdown matches the rest of the UI.
        tokens = ThemeApplicator.get().build_tokens()
        self._bg      = tokens.get("bg2", "#1C2333")
        self._fg      = tokens.get("fg", "#E6EDF3")
        self._fg_mute = tokens.get("fg2", "#8B949E")
        self._hover   = tokens.get("bg3", "#161B22")
        self._accent  = tokens.get("accent", "#22D3EE")
        self._border  = tokens.get("border", "#30363D")

        self.configure(bg=self._border)  # acts as 1 px border around inner frame

        self._build()
        self._place_under(anchor)

        # Keep the borderless popup above the main window on Windows, where
        # overrideredirect + transient can otherwise z-order the popup behind
        # its parent and swallow the pick click.
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.after(200, lambda: self._safe_topmost(False))
        except tk.TclError:
            pass

        self.bind("<Escape>", lambda _e: self._close())
        # Detect clicks anywhere outside the popup (the FocusOut channel is
        # unreliable for overrideredirect Toplevels on Windows — it can fire
        # spuriously before a row click lands, dismissing the dropdown).
        # Deferred so the Button-1 event that opened the popup doesn't also
        # bubble up into this handler and dismiss it immediately.
        self.after(0, self._install_outside_click_guard)

    # ------------------------------------------------------------------

    def _build(self) -> None:
        outer = tk.Frame(self, bg=self._border)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        canvas = tk.Canvas(
            outer, bg=self._bg, highlightthickness=0, bd=0,
            width=self.WIDTH - 2,
        )
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
            bg=self._bg,
            fg=self._accent,
            font=("Segoe UI", 10, "bold"),
            width=2,
            anchor="center",
        )
        check.pack(side="left", padx=(4, 0))

        lbl = tk.Label(
            row,
            text=name,
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
            l.configure(
                bg=self._bg,
                fg=self._fg if active else self._fg_mute,
            )
            c.configure(bg=self._bg)
        def _click(_e=None, n=name):
            self._pick(n)

        for w in (row, check, lbl):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
            w.bind("<Button-1>", _click)

    # ------------------------------------------------------------------

    def _place_under(self, anchor: Optional[tk.Widget]) -> None:
        visible_rows = min(len(self._names), self.MAX_VISIBLE)
        visible_rows = max(1, visible_rows)
        height = visible_rows * self.ROW_H + 2  # +2 for the 1 px border frame

        if anchor is not None and anchor.winfo_exists():
            try:
                anchor.update_idletasks()
                # Anchor the popup's left edge to the Themes label's left edge
                # so the dropdown falls directly beneath the button instead of
                # drifting far to the left. Only shift left if that would push
                # the popup past the right edge of the screen.
                x = anchor.winfo_rootx()
                y = anchor.winfo_rooty() + anchor.winfo_height() + 4
            except tk.TclError:
                x = self.master.winfo_rootx() + 40
                y = self.master.winfo_rooty() + 40
        else:
            x = self.master.winfo_rootx() + 40
            y = self.master.winfo_rooty() + 40

        # Keep the popup on-screen horizontally.
        try:
            screen_w = self.winfo_screenwidth()
            if x + self.WIDTH > screen_w - 4:
                x = max(4, screen_w - self.WIDTH - 4)
            if x < 4:
                x = 4
        except tk.TclError:
            pass

        self.geometry(f"{self.WIDTH}x{height}+{x}+{y}")
        # Force the position to be realised before the popup is shown; on
        # Windows, ``overrideredirect`` Toplevels can otherwise briefly render
        # at (0, 0) before picking up the requested geometry.
        self.update_idletasks()

    def _safe_topmost(self, flag: bool) -> None:
        try:
            if self.winfo_exists():
                self.attributes("-topmost", flag)
        except tk.TclError:
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
        """Close the popup when a click lands on any widget outside it."""
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
        # Run the pick BEFORE closing so the applicator still has a live root
        # to schedule after_idle on, and so any exception surfaces before the
        # popup is torn down.
        try:
            self._on_pick(name)
        except Exception as e:
            _log.warning("Theme pick error: %s", e)
        self._close()

    def _close(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
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
