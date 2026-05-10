"""Shared layout shell for the Cerebro Flet app.

Provides the NavigationRail-based shell with a content area that pages
are swapped into. All pages receive the same consistent chrome.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.routes import ROUTE_MAP, ROUTES
from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


def _control_on_page(ctrl: ft.Control | None) -> bool:
    """True if *ctrl* is attached to a Page (Flet raises RuntimeError if not)."""
    if ctrl is None:
        return False
    try:
        return ctrl.page is not None
    except RuntimeError:
        return False


class AppLayout(ft.Column):
    """Root layout: top navigation bar and content area."""

    def __init__(
        self,
        page: ft.Page,
        state_bridge: "StateBridge",
        page_builders: dict[str, Callable[[], ft.Control]],
    ):
        super().__init__(expand=True, spacing=0)
        self._page = page
        self._bridge = state_bridge
        self._builders = page_builders
        self._theme_mode = "dark" if str(getattr(self._bridge, "app_theme", "dark")).lower() == "dark" else "light"
        self._t = theme_for_mode(self._theme_mode)
        # Start "uninitialized" so first navigate_to("dashboard") mounts content.
        self._current_key: str = ""

        # Plain container (not AnimatedSwitcher): with singleton tab pages, the
        # switcher often failed to replace visible content while the rail updated.
        # Clip so wide / overflowing results subtree cannot sit on top of the rail in hit-testing.
        self._content_host = ft.Container(expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE)
        self._tab_containers: dict[str, ft.Container] = {}  # F2: reuse wrappers

        # Keep power-user pages routable but remove low-frequency pages from top-level navbar.
        self._nav_routes = [r for r in ROUTES if r.key != "exclude"]
        self._brand_icon = ft.Icon(ft.icons.Icons.AUTO_AWESOME, size=16)
        self._brand_text = ft.Text("CEREBRO", size=11, weight=ft.FontWeight.W_700)
        self._brand_block = ft.Container(
            content=ft.Row(
                [self._brand_icon, self._brand_text],
                spacing=8,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            tooltip="Cerebro v2.0",
        )
        self._nav_pills: dict[str, ft.Container] = {}
        self._nav_labels: dict[str, ft.Text] = {}
        self._nav_icons: dict[str, ft.Icon] = {}
        self._nav_hover_key: str | None = None
        nav_button_row = ft.Row(spacing=6, tight=True)
        for route in self._nav_routes:
            icon = ft.Icon(route.icon, size=16)
            label = ft.Text(route.label, size=11, weight=ft.FontWeight.W_600)
            pill = ft.Container(
                border_radius=999,
                padding=ft.padding.symmetric(horizontal=12, vertical=7),
                ink=True,
                animate=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
                content=ft.Row(
                    [icon, label],
                    spacing=6,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                on_click=lambda _e, k=route.key: self._on_nav_click(k),
                on_hover=lambda e, k=route.key: self._on_nav_hover(e, k),
            )
            self._nav_pills[route.key] = pill
            self._nav_labels[route.key] = label
            self._nav_icons[route.key] = icon
            nav_button_row.controls.append(pill)

        self._top_nav = ft.Container(
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.TRANSPARENT)),
            content=ft.Row(
                [
                    self._brand_block,
                    ft.Container(width=12),
                    nav_button_row,
                    ft.Container(expand=True),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        self.controls = [
            self._top_nav,
            self._content_host,
        ]
        self._apply_nav_theme()

    def _on_nav_click(self, key: str) -> None:
        if key == "review" and not bool(self._bridge.state.groups):
            self._bridge.show_snackbar("Run a scan first to unlock Results and Review.", info=True)
            self.navigate_to("dashboard")
            return
        self.navigate_to(key)

    def _on_nav_hover(self, e: ft.ControlEvent, key: str) -> None:
        self._nav_hover_key = key if str(e.data).lower() == "true" else None
        self._sync_nav_selection()
        if self.page is not None:
            self.update()

    def _selected_nav_index_for_key(self, key: str) -> int:
        """Map route keys to rail indices, including hidden routes."""
        key_for_nav = "settings" if key == "exclude" else key
        return next((i for i, r in enumerate(self._nav_routes) if r.key == key_for_nav), 0)

    def _apply_nav_theme(self) -> None:
        c = self._t.colors
        self._top_nav.bgcolor = c.nav_bg
        self._top_nav.border = ft.border.only(bottom=ft.BorderSide(1, c.border3))
        self._brand_icon.color = c.accent
        self._brand_text.color = c.fg
        self._sync_nav_selection()

    def _sync_nav_selection(self) -> None:
        c = self._t.colors
        selected_key = "settings" if self._current_key == "exclude" else self._current_key
        for key, pill in self._nav_pills.items():
            is_selected = key == selected_key
            is_hovered = (self._nav_hover_key == key) and not is_selected
            label = self._nav_labels[key]
            icon = self._nav_icons[key]
            label.color = c.fg if (is_selected or is_hovered) else c.fg2
            icon.color = c.accent if is_selected else (c.fg if is_hovered else c.fg_muted)
            pill.bgcolor = (
                ft.Colors.with_opacity(0.18, c.accent)
                if is_selected
                else ft.Colors.with_opacity(0.08, c.accent)
                if is_hovered
                else ft.Colors.TRANSPARENT
            )
            pill.border = ft.border.all(
                1,
                ft.Colors.with_opacity(0.44, c.accent)
                if is_selected
                else ft.Colors.with_opacity(0.26, c.accent)
                if is_hovered
                else ft.Colors.with_opacity(0.20, c.border),
            )
            pill.shadow = (
                ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=12,
                    color=ft.Colors.with_opacity(0.18, c.accent),
                    offset=ft.Offset(0, 2),
                )
                if is_selected
                else ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=8,
                    color=ft.Colors.with_opacity(0.12, c.accent),
                    offset=ft.Offset(0, 1),
                )
                if is_hovered
                else None
            )

    def apply_theme(self, mode: str) -> None:
        """Repaint shell controls when the app theme changes."""
        self._theme_mode = "dark" if (mode or "").lower() == "dark" else "light"
        self._t = theme_for_mode(self._theme_mode)
        self._apply_nav_theme()
        if self.page is not None:
            self.update()

    def navigate_to(self, key: str, *, run_on_show: bool = True) -> None:
        """Switch the content area to the page identified by *key*.

        If *run_on_show* is False, the tab's ``on_show`` hook is skipped (caller must run it
        after hydrating page-specific state). Used for ``ScanCompleted`` so ``_sync_groups``
        runs before Review paints — otherwise ``on_show`` sees empty ``_groups`` and Flet
        can miss the follow-up subtree updates.
        """
        if key not in ROUTE_MAP:
            _log.warning("Unknown route key: %s", key)
            return
        if key == "review" and not bool(self._bridge.state.groups):
            key = "dashboard"
        # If already on this key and content is mounted, skip redundant rebuild.
        # If content host is unexpectedly empty, force remount for resilience.
        if key == self._current_key and self._content_host.content is not None:
            # Re-selecting Workspace while a deferred load is pending must still run on_show;
            # otherwise the Review singleton can stay on an empty _content subtree.
            if key == "review":
                wrap = self._tab_containers.get("review")
                inner_ctrl = wrap.content if wrap is not None else None
                if inner_ctrl is not None and getattr(
                    inner_ctrl, "_pending_deferred_render", False
                ) and hasattr(inner_ctrl, "on_show"):
                    try:
                        inner_ctrl.on_show()
                    except Exception:
                        _log.exception("on_show failed for deferred same-tab review revisit")
            return
        self._current_key = key
        _ = self._selected_nav_index_for_key(key)
        self._sync_nav_selection()
        if self.page is not None:
            self.update()

        builder = self._builders.get(key)
        inner = None
        if builder:
            inner = builder()
            # F2: reuse the same wrapper container per tab to avoid remount overhead.
            if key not in self._tab_containers:
                self._tab_containers[key] = ft.Container(
                    expand=True,
                    content=inner,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                )
            else:
                tc = self._tab_containers[key]
                # Flet may skip repainting when `content` is set to the same object instance
                # again (singleton ReviewPage / DashboardPage). Bounce through None once.
                if tc.content is inner:
                    tc.content = None
                tc.content = inner
            self._content_host.content = self._tab_containers[key]
        else:
            self._content_host.content = ft.Container(
                expand=True,
                alignment=ft.Alignment(0, 0),
                content=ft.Text("Page not found"),
                key="cerebro-tab-missing",
            )

        route_info = ROUTE_MAP[key]
        self._page.route = route_info.route

        # Keep StateStore.active_tab in sync with the rail. Otherwise global listeners
        # (e.g. on ThemeChanged) still see the old tab and call navigate_to(old), which
        # immediately replaces Settings and looks like "Settings does nothing".
        try:
            self._bridge.navigate(key)
        except Exception:
            _log.exception("Failed to sync active_tab for route key %s", key)

        # Mount the new content first so inner.page is assigned before on_show runs.
        # Controls appended inside on_show (in-place list mutation) don't trigger dirty
        # tracking, so we call _content_host.update() here to mount ReviewPage, then call
        # on_show() while the page reference is live, and finally page.update() to flush.
        self._content_host.update()

        # Apply any pending theme change that was deferred while this page was inactive
        if inner is not None and hasattr(inner, "_pending_theme"):
            pending = inner._pending_theme  # type: ignore[attr-defined]
            if pending:
                inner._pending_theme = None  # type: ignore[attr-defined]
                try:
                    inner.apply_theme(pending)
                except Exception:
                    _log.exception("Deferred apply_theme failed for route key %s", key)

        if run_on_show and inner is not None and hasattr(inner, "on_show"):
            try:
                inner.on_show()
            except Exception:
                _log.exception("on_show failed for route key %s", key)

        if self._page is not None:
            try:
                self._page.update()
            except Exception:
                _log.exception("page.update after navigate_to failed")

    def refresh_current(self) -> None:
        """Refresh the current page without a full navigation cycle (F10)."""
        key = self._current_key or "dashboard"
        builder = self._builders.get(key)
        if builder:
            inner = builder()
            if inner is not None and hasattr(inner, "on_show"):
                try:
                    inner.on_show()
                except Exception:
                    _log.exception("on_show failed in refresh_current for %s", key)
        self._content_host.update()

    @property
    def current_key(self) -> str:
        return self._current_key
