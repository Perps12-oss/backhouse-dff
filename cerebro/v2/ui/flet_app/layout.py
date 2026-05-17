"""Shared layout shell for the Cerebro Flet app.



Provides the NavigationRail-based shell with a content area that pages

are swapped into. All pages receive the same consistent chrome.

"""



from __future__ import annotations



import logging

from typing import TYPE_CHECKING, Callable



import flet as ft



from cerebro.v2.ui.flet_app.design_system.shell_background import (

    apply_shell_theme,

    build_shell_background_stack,

)

from cerebro.v2.ui.flet_app.multigradient_themes import default_gradient, gradient_by_id
from cerebro.v2.ui.flet_app.routes import ROUTE_MAP, ROUTES
from cerebro.v2.ui.flet_app.pill_button_styles import text_on_fill
from cerebro.v2.ui.flet_app.theme import theme_for_mode

from cerebro.v2.ui.flet_app.utils.motion import should_animate

from cerebro.v2.ui.flet_app.utils.shortcuts import format_nav_shortcut_label



if TYPE_CHECKING:

    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge



_log = logging.getLogger(__name__)



_NAV_TRACK_BG = "#1e1e1e"





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

        self._current_key: str = ""



        self._content_host = ft.Container(

            expand=True,

            clip_behavior=ft.ClipBehavior.HARD_EDGE,

            padding=ft.Padding.symmetric(horizontal=self._t.spacing.lg, vertical=0),

            bgcolor=ft.Colors.TRANSPARENT,

        )

        self._tab_containers: dict[str, ft.Container] = {}



        self._nav_routes = [r for r in ROUTES if r.key != "exclude"]
        self._route_map = ROUTE_MAP



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

        self._nav_pill_stride = 106

        nav_button_row = ft.Row(spacing=6, tight=True)

        for idx, route in enumerate(self._nav_routes):

            icon = ft.Icon(route.icon, size=16)

            label = ft.Text(route.label, size=11, weight=ft.FontWeight.W_600)

            shortcut = format_nav_shortcut_label(page, idx + 1)

            pill = ft.Container(

                border_radius=16,

                padding=ft.Padding.symmetric(horizontal=12, vertical=7),

                ink=True,

                bgcolor=ft.Colors.TRANSPARENT,

                animate=ft.Animation(160, ft.AnimationCurve.EASE_OUT),

                tooltip=f"{route.label} ({shortcut})",

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



        self._nav_indicator = ft.Container(

            height=34,

            width=self._nav_pill_stride,

            border_radius=16,

            left=0,

            animate_position=ft.Animation(300, ft.AnimationCurve.EASE_OUT_CUBIC),

        )

        self._nav_track = ft.Container(

            border_radius=24,

            padding=ft.Padding.symmetric(horizontal=6, vertical=4),

            content=ft.Stack([self._nav_indicator, nav_button_row]),

        )



        gid = getattr(state_bridge, "active_gradient_id", "flet_base")

        gradient = gradient_by_id(gid) or default_gradient()

        self._shell_bg = build_shell_background_stack(gradient)



        self._content_stack = ft.Stack(

            [self._shell_bg, self._content_host],

            expand=True,

        )



        self._top_nav = ft.Container(

            padding=ft.Padding.symmetric(horizontal=12, vertical=8),

            border=ft.border.only(bottom=ft.BorderSide(1, ft.Colors.TRANSPARENT)),

            content=ft.Row(

                [

                    self._brand_block,

                    ft.Container(width=12),

                    self._nav_track,

                    ft.Container(expand=True),

                ],

                vertical_alignment=ft.CrossAxisAlignment.CENTER,

            ),

        )



        self.controls = [

            self._top_nav,

            self._content_stack,

        ]

        self._apply_nav_theme()



    def _on_nav_click(self, key: str) -> None:

        if key == "review" and not bool(self._bridge.state.groups):

            self._bridge.show_snackbar("Run a scan first to open Review.", info=True)

            self.navigate_to("dashboard")

            return

        self.navigate_to(key)



    def _on_nav_hover(self, e: ft.ControlEvent, key: str) -> None:

        self._nav_hover_key = key if str(e.data).lower() == "true" else None

        self._sync_nav_selection()

        if self.page is not None:

            self.update()



    def _selected_nav_index_for_key(self, key: str) -> int:

        key_for_nav = "settings" if key == "exclude" else key

        return next((i for i, r in enumerate(self._nav_routes) if r.key == key_for_nav), 0)



    def _apply_nav_theme(self) -> None:

        c = self._t.colors

        self._top_nav.bgcolor = c.nav_bg

        self._top_nav.border = ft.border.only(bottom=ft.BorderSide(1, c.border))

        self._nav_track.bgcolor = _NAV_TRACK_BG

        self._brand_icon.color = c.primary

        self._brand_text.color = c.fg

        self._sync_nav_selection()



    def _sync_nav_selection(self) -> None:

        c = self._t.colors

        selected_key = "settings" if self._current_key == "exclude" else self._current_key

        sel_idx = self._selected_nav_index_for_key(selected_key or "dashboard")

        self._nav_indicator.left = sel_idx * self._nav_pill_stride

        accent = c.primary
        on_accent = text_on_fill(accent)
        self._nav_indicator.bgcolor = accent

        self._nav_indicator.border = None

        self._nav_indicator.shadow = None

        if not should_animate(self._bridge):

            self._nav_indicator.animate_position = None



        for key, pill in self._nav_pills.items():

            is_selected = key == selected_key

            is_hovered = (self._nav_hover_key == key) and not is_selected

            label = self._nav_labels[key]

            icon = self._nav_icons[key]

            if is_selected:

                label.color = on_accent

                icon.color = on_accent

            elif is_hovered:

                label.color = c.fg

                icon.color = c.fg

            else:

                label.color = c.fg2

                icon.color = c.fg_muted

            pill.bgcolor = ft.Colors.TRANSPARENT

            pill.border = None

            pill.shadow = None



    def apply_shell_gradient(self, gradient_id: str) -> None:

        gradient = gradient_by_id(gradient_id) or default_gradient()

        apply_shell_theme(self._shell_bg, gradient)



    def apply_theme(self, mode: str) -> None:

        """Repaint shell controls when the app theme changes."""

        self._theme_mode = "dark" if (mode or "").lower() == "dark" else "light"

        self._t = theme_for_mode(self._theme_mode)

        self._content_host.padding = ft.Padding.symmetric(horizontal=self._t.spacing.lg, vertical=0)

        self._content_host.bgcolor = ft.Colors.TRANSPARENT

        self._apply_nav_theme()

        self.apply_shell_gradient(getattr(self._bridge, "active_gradient_id", "flet_base"))

        if self.page is not None:

            self.update()



    def navigate_to(self, key: str, *, run_on_show: bool = True) -> None:

        if key == "duplicates":

            key = "review"

        if key not in self._route_map:

            _log.warning("Unknown route key: %s", key)

            return

        if key == "review" and not bool(self._bridge.state.groups):

            key = "dashboard"

        if key == self._current_key and self._content_host.content is not None:

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

        if key == "dashboard":

            from cerebro.v2.ui.flet_app.utils.time_keeper import TimeKeeper



            TimeKeeper.instance().resume()

        else:

            from cerebro.v2.ui.flet_app.utils.time_keeper import TimeKeeper



            TimeKeeper.instance().pause()

        if self.page is not None:

            self.update()



        builder = self._builders.get(key)

        inner = None

        if builder:

            inner = builder()

            tab_clip = ft.ClipBehavior.NONE if key == "review" else ft.ClipBehavior.HARD_EDGE

            if key not in self._tab_containers:

                self._tab_containers[key] = ft.Container(

                    expand=True,

                    content=inner,

                    clip_behavior=tab_clip,

                )

            else:

                tc = self._tab_containers[key]

                tc.clip_behavior = tab_clip

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



        route_info = self._route_map[key]

        self._page.route = route_info.route



        try:

            self._bridge.navigate(key)

        except Exception:

            _log.exception("Failed to sync active_tab for route key %s", key)



        self._content_host.update()



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


