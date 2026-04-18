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

import tkinter as tk
from typing import Dict, Optional

try:
    import customtkinter as ctk
    CTk      = ctk.CTk
    CTkFrame = ctk.CTkFrame
    CTkLabel = ctk.CTkLabel
except ImportError:
    CTk      = tk.Tk       # type: ignore[misc,assignment]
    CTkFrame = tk.Frame    # type: ignore[misc,assignment]
    CTkLabel = tk.Label    # type: ignore[misc,assignment]

from cerebro.v2.ui.title_bar    import TitleBar
from cerebro.v2.ui.tab_bar      import TabBar
from cerebro.v2.ui.welcome_page import WelcomePage
from cerebro.engines.orchestrator import ScanOrchestrator

_PAGE_BG = "#F0F0F0"


class AppShell(CTk):
    """
    Root window for the CEREBRO UI overhaul.

    Phase 1 deliverable: TitleBar + TabBar + 6 switchable placeholder pages.
    """

    def __init__(self) -> None:
        super().__init__()
        # Engine reference — never modified, only read/called by page widgets
        self._orchestrator = ScanOrchestrator()
        self._setup_window()
        self._build_ui()

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
        # Centre on screen
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
        # Title bar
        self._title_bar = TitleBar(
            self,
            on_settings=self._open_settings,
            on_themes=self._open_themes,
        )
        self._title_bar.pack(fill="x")

        # Tab bar
        self._tab_bar = TabBar(self, on_tab_changed=self._on_tab_changed)
        self._tab_bar.pack(fill="x")

        # Page container — all pages sit here, stacked via place
        self._page_container = CTkFrame(self, fg_color=_PAGE_BG)
        self._page_container.pack(fill="both", expand=True)

        # Build pages — Welcome is real; rest are placeholders for now
        self._pages: Dict[str, CTkFrame] = {}
        for key in ("scan", "results", "review", "history", "diagnostics"):
            self._pages[key] = self._make_placeholder(key)

        self._pages["welcome"] = WelcomePage(
            self._page_container,
            on_start_scan=lambda: self.switch_tab("scan"),
            on_open_session=self._on_open_session,
        )

        # Show Welcome
        self._current_page: str = "welcome"
        self._pages["welcome"].place(relwidth=1, relheight=1)

    def _make_placeholder(self, key: str) -> CTkFrame:
        """Muted label placeholder shown until a later phase provides real content."""
        frame = CTkFrame(self._page_container, fg_color=_PAGE_BG)
        CTkLabel(
            frame,
            text=key.upper(),
            font=("Segoe UI", 22, "bold"),
            text_color="#CCCCCC",
        ).place(relx=0.5, rely=0.5, anchor="center")
        return frame

    # ------------------------------------------------------------------
    # Tab switching
    # ------------------------------------------------------------------

    def _on_tab_changed(self, key: str) -> None:
        if key == self._current_page:
            return
        self._pages[self._current_page].place_forget()
        self._current_page = key
        self._pages[key].place(relwidth=1, relheight=1)

    def switch_tab(self, key: str) -> None:
        """Programmatically navigate to a tab (called by page widgets)."""
        self._tab_bar.switch_to(key)

    # ------------------------------------------------------------------
    # Title bar actions (stubbed — wired in Phase 7)
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        pass  # Phase 7

    def _open_themes(self) -> None:
        pass  # Phase 7

    def _on_open_session(self, session) -> None:
        """Load a past session into the Results page and switch to it (Phase 4+)."""
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
