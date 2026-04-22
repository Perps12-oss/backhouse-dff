"""
DiagnosticsPage — full-tab Diagnostics page for the CEREBRO v2 overhaul.

Sections:
  • App Info      — CEREBRO version, Python version, UI library versions
  • Engine Status — which scan engines are loaded and operational
  • Database Info — SQLite DB paths, row counts, file sizes

All data is collected in a background thread on first show; a Refresh
button triggers a new collection pass.

All surfaces are driven by :class:`ThemeApplicator` tokens so the page
repaints whenever the active theme changes (top-bar quick dropdown or
Settings > Appearance).
"""
from __future__ import annotations

import logging
import platform
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from cerebro.v2.core.engine_deps import (
    ENGINE_DEPS,
    EngineState,
    ProbeResult,
    invalidate_module_cache,
    probe_engine,
    probe_all,
)
from cerebro.v2.core.engine_errors_db import get_engine_errors_db
from cerebro.v2.ui.design_tokens import (
    BORDER, CARD_BG, FONT_BODY, FONT_HEADER, FONT_MONO, FONT_SMALL,
    FONT_TITLE, GREEN, NAVY, NAVY_MID, PAD_X, PAD_Y, RED, TEXT_MUTED,
    TEXT_PRIMARY, TEXT_SECONDARY, YELLOW,
)
from cerebro.v2.ui.theme_applicator import ThemeApplicator, theme_token

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def _page_colors(t: dict) -> dict:
    return {
        "bg":       theme_token(t, "bg",       NAVY),
        "bar":      theme_token(t, "nav_bar",  NAVY_MID),
        "card":     theme_token(t, "bg2",      CARD_BG),
        "border":   theme_token(t, "border",   BORDER),
        "fg":       theme_token(t, "fg",       TEXT_PRIMARY),
        "fg2":      theme_token(t, "fg2",      TEXT_SECONDARY),
        "fg_muted": theme_token(t, "fg_muted", TEXT_MUTED),
        "success":  theme_token(t, "success",  GREEN),
        "warning":  theme_token(t, "warning",  YELLOW),
        "danger":   theme_token(t, "danger",   RED),
    }


# State → ("dot_color_key", "state_label_shown_to_user")
_STATE_PRESENTATION: dict = {
    EngineState.AVAILABLE:       ("success",  "available"),
    EngineState.NOT_IMPLEMENTED: ("fg_muted", "not yet implemented"),
    EngineState.MISSING_DEPS:    ("warning",  "missing dependencies"),
    EngineState.DEGRADED:        ("warning",  "degraded"),
    EngineState.RUNTIME_ERROR:   ("danger",   "runtime error"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    val = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024 or unit == "GB":
            return f"{int(val)} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TB"


def _lib_version(module_name: str, attr: str = "__version__") -> str:
    try:
        import importlib
        mod = importlib.import_module(module_name)
        return str(getattr(mod, attr, "installed"))
    except ImportError:
        return "not installed"


# ---------------------------------------------------------------------------
# _SectionHeader
# ---------------------------------------------------------------------------

class _SectionHeader(tk.Frame):
    def __init__(self, parent: tk.Widget, title: str) -> None:
        super().__init__(parent, bg=NAVY_MID, height=34)
        self.pack_propagate(False)
        self._title_lbl = tk.Label(
            self, text=title, bg=NAVY_MID, fg=TEXT_PRIMARY,
            font=FONT_HEADER,
        )
        self._title_lbl.pack(side="left", padx=PAD_X)

    def apply_theme(self, colors: dict) -> None:
        self.configure(bg=colors["bar"])
        self._title_lbl.configure(bg=colors["bar"], fg=colors["fg"])


# ---------------------------------------------------------------------------
# _InfoGrid  — two-column key/value grid
# ---------------------------------------------------------------------------

class _InfoGrid(tk.Frame):
    """Renders a list of (label, value) rows in a themed card background."""

    def __init__(self, parent: tk.Widget, colors: dict) -> None:
        super().__init__(parent, bg=colors["card"])
        self._colors = colors
        self._row = 0

    def add_row(self, label: str, value: str, role: str = "fg2") -> None:
        value_color = self._colors.get(role, self._colors["fg2"])
        tk.Label(
            self, text=label, bg=self._colors["card"], fg=self._colors["fg_muted"],
            font=FONT_SMALL, anchor="w", width=26,
        ).grid(row=self._row, column=0, sticky="w", padx=(PAD_X, 8), pady=3)
        tk.Label(
            self, text=value, bg=self._colors["card"], fg=value_color, font=FONT_MONO,
            anchor="w",
        ).grid(row=self._row, column=1, sticky="w", padx=(0, PAD_X), pady=3)
        self._row += 1


# ---------------------------------------------------------------------------
# _EngineRow
# ---------------------------------------------------------------------------

class _EngineRow(tk.Frame):
    """One row per engine: colored state dot · plain-language name ·
    detail · ``[Copy pip]`` / ``[Retry]`` action buttons when applicable.

    Designed to explain *what the user can do* about a failure rather than
    just "there was an error somewhere". See
    :class:`~cerebro.v2.core.engine_deps.EngineState` for the five states.
    """

    def __init__(
        self,
        parent: tk.Widget,
        probe: ProbeResult,
        colors: dict,
        on_retry: Optional[Callable[[str], None]] = None,
        on_copy: Optional[Callable[[str, "_EngineRow"], None]] = None,
    ) -> None:
        super().__init__(parent, bg=colors["card"])
        state = EngineState(probe.state)
        dot_key, state_label = _STATE_PRESENTATION[state]
        dot_color = colors.get(dot_key, colors["fg2"])

        # State dot.
        tk.Label(
            self, text="●", bg=colors["card"], fg=dot_color, font=FONT_SMALL,
        ).pack(side="left", padx=(PAD_X, 6), pady=4)

        # Plain-language name (fixed width so rows align).
        name = ENGINE_DEPS[probe.key].display_name if probe.key in ENGINE_DEPS else probe.key
        tk.Label(
            self, text=name, bg=colors["card"], fg=colors["fg"], font=FONT_BODY,
            width=22, anchor="w",
        ).pack(side="left")

        # Combined state + detail text.
        detail_txt = f"{state_label} — {probe.detail}" if probe.detail else state_label
        self._detail_lbl = tk.Label(
            self, text=detail_txt, bg=colors["card"], fg=colors["fg2"],
            font=FONT_SMALL, anchor="w", justify="left",
        )
        self._detail_lbl.pack(side="left", padx=(4, PAD_X))

        # Action buttons live on the right. Only shown when the user can
        # actually do something about the state.
        if probe.pip_hint and state in (EngineState.MISSING_DEPS, EngineState.DEGRADED):
            btn_copy = tk.Button(
                self,
                text="Copy install command",
                command=(
                    lambda h=probe.pip_hint, row=self: on_copy(h, row) if on_copy else None
                ),
                bg=colors["bar"], fg=colors["fg"],
                activebackground=colors["border"], activeforeground=colors["fg"],
                relief="flat", font=FONT_SMALL, cursor="hand2", padx=10, pady=2,
            )
            btn_copy.pack(side="right", padx=(4, PAD_X), pady=4)

        if on_retry and state in (
            EngineState.MISSING_DEPS, EngineState.DEGRADED, EngineState.RUNTIME_ERROR,
        ):
            btn_retry = tk.Button(
                self,
                text="Retry",
                command=lambda k=probe.key: on_retry(k),
                bg=colors["bar"], fg=colors["fg"],
                activebackground=colors["border"], activeforeground=colors["fg"],
                relief="flat", font=FONT_SMALL, cursor="hand2", padx=10, pady=2,
            )
            btn_retry.pack(side="right", padx=(4, 4), pady=4)

    def flash_copied(self, colors: dict) -> None:
        """Briefly swap the detail label to 'Copied!' for visual feedback."""
        original = self._detail_lbl.cget("text")
        original_fg = self._detail_lbl.cget("fg")
        self._detail_lbl.configure(text="Copied!", fg=colors.get("success", GREEN))
        self.after(1200, lambda: self._restore_detail(original, original_fg))

    def _restore_detail(self, text: str, fg: str) -> None:
        try:
            self._detail_lbl.configure(text=text, fg=fg)
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# DiagnosticsPage (public)
# ---------------------------------------------------------------------------

class DiagnosticsPage(tk.Frame):
    """Full-page Diagnostics tab for AppShell."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, bg=NAVY)
        self._section_headers: List[_SectionHeader] = []
        self._section_cards:   List[tk.Frame]       = []
        self._section_seps:    List[tk.Frame]       = []
        self._app_rows: List[Tuple[str, str, str]] = []
        self._eng_rows: List[ProbeResult] = []
        self._db_rows:  List[Tuple[str, str, str]] = []
        self._colors = _page_colors({})
        self._build()
        ThemeApplicator.get().register(self._apply_theme)

    # ------------------------------------------------------------------
    # Build skeleton
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._title_bar = tk.Frame(self, bg=NAVY, height=48)
        self._title_bar.pack(fill="x")
        self._title_bar.pack_propagate(False)
        self._title_lbl = tk.Label(
            self._title_bar, text="Diagnostics", bg=NAVY, fg=TEXT_PRIMARY,
            font=FONT_TITLE,
        )
        self._title_lbl.pack(side="left", padx=PAD_X, pady=PAD_Y)

        self._refresh_btn = tk.Button(
            self._title_bar, text="⟳  Refresh", command=self._load,
            bg=NAVY_MID, fg=TEXT_PRIMARY, activebackground=BORDER,
            activeforeground=TEXT_PRIMARY, relief="flat",
            font=FONT_SMALL, cursor="hand2", padx=12, pady=4,
        )
        self._refresh_btn.pack(side="right", padx=PAD_X, pady=PAD_Y)

        self._title_sep = tk.Frame(self, bg=BORDER, height=1)
        self._title_sep.pack(fill="x")

        # Scrollable content area
        self._canvas = tk.Canvas(self, bg=NAVY, highlightthickness=0)
        self._scrollbar = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._scroll_frame = tk.Frame(self._canvas, bg=NAVY)
        self._win_id = self._canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")

        self._scroll_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(self._win_id, width=e.width),
        )
        self._canvas.bind(
            "<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        # Build section skeletons
        self._app_grid         = self._make_section("App Information")
        self._engine_container = self._make_section("Engine Status")
        self._db_grid          = self._make_section("Database Information")

        self._status_lbl = tk.Label(
            self._scroll_frame, text="Loading…", bg=NAVY, fg=TEXT_MUTED,
            font=FONT_SMALL,
        )
        self._status_lbl.pack(anchor="w", padx=PAD_X, pady=(0, PAD_Y))

    def _make_section(self, title: str) -> tk.Frame:
        header = _SectionHeader(self._scroll_frame, title)
        header.pack(fill="x", pady=(PAD_Y, 0))
        sep = tk.Frame(self._scroll_frame, bg=BORDER, height=1)
        sep.pack(fill="x")
        card = tk.Frame(self._scroll_frame, bg=CARD_BG)
        card.pack(fill="x", padx=PAD_X, pady=(0, PAD_Y))
        self._section_headers.append(header)
        self._section_seps.append(sep)
        self._section_cards.append(card)
        return card

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------

    def _apply_theme(self, tokens: dict) -> None:
        colors = _page_colors(tokens)
        self._colors = colors
        self.configure(bg=colors["bg"])
        self._title_bar.configure(bg=colors["bg"])
        self._title_lbl.configure(bg=colors["bg"], fg=colors["fg"])
        self._title_sep.configure(bg=colors["border"])
        self._refresh_btn.configure(
            bg=colors["bar"], fg=colors["fg"],
            activebackground=colors["border"],
            activeforeground=colors["fg"],
        )
        self._canvas.configure(bg=colors["bg"])
        self._scroll_frame.configure(bg=colors["bg"])
        self._status_lbl.configure(bg=colors["bg"], fg=colors["fg_muted"])

        for header in self._section_headers:
            try:
                header.apply_theme(colors)
            except tk.TclError:
                pass
        for sep in self._section_seps:
            try:
                sep.configure(bg=colors["border"])
            except tk.TclError:
                pass
        for card in self._section_cards:
            try:
                card.configure(bg=colors["card"])
            except tk.TclError:
                pass

        # Re-render content with new colors if we already have data.
        if self._app_rows or self._eng_rows or self._db_rows:
            self._render(self._app_rows, self._eng_rows, self._db_rows)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def on_show(self) -> None:
        self._load()

    def _load(self) -> None:
        self._status_lbl.configure(text="Refreshing…")
        threading.Thread(target=self._collect, daemon=True).start()

    def _collect(self) -> None:
        app_rows   = self._collect_app_info()
        eng_rows   = self._collect_engine_status()
        db_rows    = self._collect_db_info()
        self.after(0, lambda: self._render(app_rows, eng_rows, db_rows))

    # ------------------------------------------------------------------
    # Engine retry / clipboard helpers (Phase 7)
    # ------------------------------------------------------------------

    def _retry_engine(self, engine_key: str) -> None:
        """Re-probe one engine in-place. Called by per-row 'Retry' button.

        Invalidates Python's import cache for the target module first, so
        packages installed in another terminal after the app started can
        be picked up without a full restart.
        """
        info = ENGINE_DEPS.get(engine_key)
        if info is None:
            return
        invalidate_module_cache(info.module_path)
        new_probe = probe_engine(info)
        self._log_probe(new_probe)
        # Replace the matching entry and re-render just the engine section.
        for i, p in enumerate(self._eng_rows):
            if p.key == engine_key:
                self._eng_rows[i] = new_probe
                break
        self._render_engine_section(self._eng_rows)

    def _copy_pip_command(self, hint: str, row: "_EngineRow") -> None:
        """Put the pip hint on the system clipboard and flash feedback."""
        try:
            self.clipboard_clear()
            self.clipboard_append(hint)
            # Force Tk to hand ownership to the OS so the clipboard value
            # survives this window being destroyed / losing focus.
            self.update_idletasks()
        except tk.TclError:
            _log.exception("Failed to copy install command to clipboard")
            return
        try:
            row.flash_copied(self._colors)
        except tk.TclError:
            pass

    def _log_probe(self, probe: ProbeResult) -> None:
        """Persist non-AVAILABLE outcomes for an audit trail."""
        if probe.state is EngineState.AVAILABLE:
            return
        try:
            get_engine_errors_db().record_error(
                engine_key=probe.key,
                state=str(probe.state.value if hasattr(probe.state, "value") else probe.state),
                detail=probe.detail,
                module_path=probe.module_path,
                exception_class=probe.exception_class,
                exception_message=probe.exception_message,
            )
        except Exception:
            _log.exception("Failed to log engine probe to engine_errors_db")

    def _collect_app_info(self) -> List[Tuple[str, str, str]]:
        rows: List[Tuple[str, str, str]] = []
        try:
            import cerebro
            rows.append(("CEREBRO version", getattr(cerebro, "__version__", "unknown"), "fg2"))
        except ImportError:
            rows.append(("CEREBRO version", "unknown", "fg_muted"))

        rows.append(("Python", f"{sys.version.split()[0]}  ({platform.python_implementation()})", "fg2"))
        rows.append(("Platform", platform.platform(terse=True), "fg2"))
        rows.append(("Architecture", platform.machine(), "fg2"))

        rows.append(("customtkinter", _lib_version("customtkinter"), "fg2"))
        rows.append(("Pillow (PIL)", _lib_version("PIL", "PILLOW_VERSION") or _lib_version("PIL"), "fg2"))
        rows.append(("tkinter", str(tk.TkVersion), "fg2"))
        return rows

    def _collect_engine_status(self) -> List[ProbeResult]:
        """Probe every engine via :mod:`cerebro.v2.core.engine_deps`.

        Each non-AVAILABLE outcome is persisted to ``engine_errors.db``
        so the user can see a failure history in addition to live state.
        """
        probes = probe_all()
        for probe in probes:
            self._log_probe(probe)
        return probes

    def _collect_db_info(self) -> List[Tuple[str, str, str]]:
        rows: List[Tuple[str, str, str]] = []

        def _db_entry(label: str, path: Path, count_fn) -> None:
            try:
                size_txt = _fmt_bytes(path.stat().st_size) if path.exists() else "not found"
                count    = count_fn() if path.exists() else 0
                rows.append((label + " path", str(path), "fg2"))
                rows.append((label + " size", size_txt, "fg2"))
                rows.append((label + " records", str(count), "fg2"))
            except Exception:
                rows.append((label + " path", str(path), "fg_muted"))

        scan_path = Path.home() / ".cerebro" / "scan_history.db"
        def _scan_count():
            from cerebro.v2.core.scan_history_db import get_scan_history_db
            return len(get_scan_history_db().get_recent(limit=99999))
        _db_entry("Scan history DB", scan_path, _scan_count)

        del_path = Path.home() / ".cerebro" / "deletion_history.db"
        def _del_count():
            from cerebro.v2.core.deletion_history_db import get_default_history_manager
            return len(get_default_history_manager().get_recent_history(limit=99999))
        _db_entry("Deletion history DB", del_path, _del_count)

        cache_path = Path.home() / ".cerebro" / "hash_cache.db"
        rows.append(("Hash cache DB path", str(cache_path), "fg2"))
        if cache_path.exists():
            rows.append(("Hash cache DB size", _fmt_bytes(cache_path.stat().st_size), "fg2"))
        else:
            rows.append(("Hash cache DB size", "not found", "fg_muted"))

        return rows

    def _render(
        self,
        app_rows:  List[Tuple[str, str, str]],
        eng_rows:  List[ProbeResult],
        db_rows:   List[Tuple[str, str, str]],
    ) -> None:
        self._app_rows = app_rows
        self._eng_rows = eng_rows
        self._db_rows  = db_rows

        colors = self._colors

        for w in self._app_grid.winfo_children():
            w.destroy()
        grid = _InfoGrid(self._app_grid, colors)
        grid.pack(fill="x", padx=2, pady=2)
        for label, value, role in app_rows:
            grid.add_row(label, value, role)

        self._render_engine_section(eng_rows)

        for w in self._db_grid.winfo_children():
            w.destroy()
        db_grid = _InfoGrid(self._db_grid, colors)
        db_grid.pack(fill="x", padx=2, pady=2)
        for label, value, role in db_rows:
            db_grid.add_row(label, value, role)

        self._status_lbl.configure(text="", bg=colors["bg"], fg=colors["fg_muted"])

    def _render_engine_section(self, probes: List[ProbeResult]) -> None:
        """Re-render just the engine-status card. Called on initial load,
        theme change, and every time a 'Retry' button re-probes an engine.
        """
        colors = self._colors
        for w in self._engine_container.winfo_children():
            w.destroy()
        for probe in probes:
            _EngineRow(
                self._engine_container,
                probe,
                colors,
                on_retry=self._retry_engine,
                on_copy=self._copy_pip_command,
            ).pack(fill="x", padx=2, pady=1)
