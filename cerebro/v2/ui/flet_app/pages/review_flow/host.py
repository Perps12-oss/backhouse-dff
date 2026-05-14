from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state.actions import FileSelectionChanged
from cerebro.v2.ui.flet_app.pages.review_flow.mock_data import generate_mock_groups
from cerebro.v2.ui.flet_app.pages.review_flow.progress_sidebar import build_progress_sidebar
from cerebro.v2.ui.flet_app.pages.review_flow.router import ReviewFlowRouter
from cerebro.v2.ui.flet_app.pages.review_flow.screens.browse import BrowseScreenView
from cerebro.v2.ui.flet_app.pages.review_flow.screens.cart import build_cart_screen
from cerebro.v2.ui.flet_app.pages.review_flow.screens.execute import build_execute_screen
from cerebro.v2.ui.flet_app.pages.review_flow.screens.inspect import build_inspect_screen
from cerebro.v2.ui.flet_app.pages.review_flow.screens.overview import build_overview_screen
from cerebro.v2.ui.flet_app.pages.review_flow.screens.report import build_report_screen
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState, SetSelection
from cerebro.core.deletion import DeletionPolicy
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS, paths_to_delete
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)
_UI_SLOW_MS = 80.0


class ReviewFlowHost(ft.Column):
    """Progressive six-screen duplicate review host."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, spacing=0)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._state = ReviewFlowState()
        self._router = ReviewFlowRouter(self._state, self._render_active_screen)
        self._delete_service = DeleteService()
        self._browse_view: Optional[BrowseScreenView] = None
        self._content = ft.Container(expand=True)
        self._grid = ft.ListView(expand=True)
        self._workstation_sidebar = ft.Container(width=0)
        self._toast_layer = ft.Stack([])
        self._overlay_layer = ft.Stack([])
        self._inspect_stub = True
        self.controls = [
            ft.Row(
                [
                    self._workstation_sidebar,
                    ft.Column([self._content, self._overlay_layer, self._toast_layer], expand=True),
                ],
                expand=True,
                spacing=0,
            )
        ]
        self._seed_mock_results()
        self._render_active_screen()

    def _seed_mock_results(self) -> None:
        self._state.scan_results = generate_mock_groups(1000)
        self._state.use_mock_data = True

    def _render_active_screen(self) -> None:
        started = time.perf_counter()
        t = self._t
        screen = self._router.active_screen()
        self._workstation_sidebar = build_progress_sidebar(t, screen, self._on_progress_jump)
        self.controls[0].controls[0] = self._workstation_sidebar
        if screen == "overview":
            self._content.content = build_overview_screen(
                t,
                self._state.scan_results,
                on_start_review=self._on_start_review,
                on_auto_select=self._open_auto_select_modal,
                on_filter=self._open_filter_sheet,
                on_export=self._open_export_modal,
            )
        elif screen == "browse":
            self._browse_view = BrowseScreenView(
                t,
                self._state,
                on_back=self._on_back,
                on_toggle_set=self._toggle_set,
                on_toggle_expand=self._toggle_expand,
                on_open_inspect=self._open_inspect,
                on_open_cart=self._open_cart,
            )
            page = getattr(self._bridge, "flet_page", None)
            if page is not None:
                self._browse_view.attach_page(page)
            self._content.content = self._browse_view.root
            self._grid = self._browse_view.list_host
            self._browse_view.refresh()
        elif screen == "inspect":
            self._content.content = build_inspect_screen(
                t,
                self._state,
                on_back=self._on_back,
                on_prev_set=self._inspect_prev,
                on_next_set=self._inspect_next,
                on_keep_a=lambda e: self._inspect_keep_side(0),
                on_keep_b=lambda e: self._inspect_keep_side(1),
                on_keep_both=lambda e: self._inspect_keep_both(),
                on_delete_all=lambda e: self._inspect_delete_all(),
                on_mark_next=lambda e: self._inspect_mark_next(),
                stub_only=self._inspect_stub,
            )
        elif screen == "cart":
            self._content.content = build_cart_screen(
                t,
                self._state,
                on_back=self._on_back,
                on_proceed=lambda e: self._router.navigate("execute"),
                on_toggle_dry_run=self._toggle_dry_run,
            )
        elif screen == "execute":
            self._content.content = build_execute_screen(
                t,
                self._state,
                on_back=self._on_back,
                on_confirm_toggle=self._toggle_execute_confirm,
                on_execute=self._run_execute,
                on_cancel_remaining=lambda e: self._router.navigate("cart", push=False),
            )
        else:
            self._content.content = build_report_screen(
                t,
                self._state,
                on_back_overview=lambda e: self._router.reset_to_overview(),
                on_export=self._open_export_modal,
                on_new_scan=lambda e: self._bridge.navigate("dashboard"),
            )
        self._safe_update(self)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms > _UI_SLOW_MS:
            _log.debug("[UI_SLOW] review_flow render %s took %.1f ms", screen, elapsed_ms)

    def on_show(self) -> None:
        self._t = theme_for_mode("dark")
        self._state.marked_paths = set(self._bridge.state.selected_files)
        if not self._state.use_mock_data:
            store_groups = list(getattr(self._bridge.state, "groups", []) or [])
            if store_groups:
                self._state.scan_results = store_groups
                self._state.scan_mode = getattr(self._bridge.state, "scan_mode", None) or "files"
        self._render_active_screen()

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._state.scan_results)

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files", defer_render: bool = False) -> None:
        if groups:
            self._state.scan_results = list(groups)
            self._state.scan_mode = mode
            self._state.use_mock_data = False
        elif not self._state.scan_results:
            self._seed_mock_results()
        if not defer_render and self._page_is_set(self):
            self._render_active_screen()

    def apply_pruned_groups(self, groups: List[DuplicateGroup], mode: str = "files") -> None:
        self.load_results(groups, mode, defer_render=False)

    def handle_keyboard(self, key: str, *, ctrl: bool = False, shift: bool = False) -> bool:
        screen = self._router.active_screen()
        if key in ("escape", "esc"):
            if self._router.go_back():
                self._render_active_screen()
            return True
        if screen == "overview" and key in ("enter", "space"):
            self._on_start_review(None)
            return True
        if screen == "browse":
            if key in ("arrowup", "up"):
                self._state.browse_focus_index = max(0, self._state.browse_focus_index - 1)
                return True
            if key in ("arrowdown", "down"):
                self._state.browse_focus_index += 1
                return True
            if key == "space":
                groups = self._state.visible_groups()
                if groups:
                    idx = min(self._state.browse_focus_index, len(groups) - 1)
                    self._toggle_set(groups[idx].group_id)
                return True
            if key == "enter":
                groups = self._state.visible_groups()
                if groups:
                    idx = min(self._state.browse_focus_index, len(groups) - 1)
                    self._open_inspect(groups[idx].group_id)
                return True
        if screen == "inspect" and not self._inspect_stub:
            if key == "d":
                return True
        if ctrl and key == "z" and not shift:
            self._undo()
            return True
        if ctrl and key == "z" and shift:
            self._redo()
            return True
        if ctrl and key == "s":
            self._save_session()
            return True
        if ctrl and key == "k":
            self._open_command_palette()
            return True
        return False

    def _on_start_review(self, _e) -> None:
        self._router.navigate("browse")

    def _on_back(self, _e) -> bool:
        return self._router.go_back()

    def _on_progress_jump(self, screen) -> None:
        if screen in self._state.screen_stack:
            while self._router.active_screen() != screen and self._router.can_go_back():
                self._router.go_back()
            if self._router.active_screen() != screen:
                self._router.navigate(screen)

    def _toggle_set(self, group_id: int) -> None:
        if group_id in self._state.selected_set_ids:
            self._state.selected_set_ids.remove(group_id)
        else:
            self._state.selected_set_ids.add(group_id)
        if self._browse_view:
            self._browse_view.refresh()

    def _toggle_expand(self, group_id: int) -> None:
        if group_id in self._state.expanded_set_ids:
            self._state.expanded_set_ids.remove(group_id)
        else:
            self._state.expanded_set_ids.add(group_id)
        if self._browse_view:
            self._browse_view.refresh()

    def _open_inspect(self, group_id: int) -> None:
        self._state.inspect_set_id = group_id
        self._state.inspect_file_index = 0
        self._router.navigate("inspect")

    def _open_cart(self, _e=None) -> None:
        self._router.navigate("cart")

    def _inspect_prev(self, _e=None) -> None:
        groups = self._state.visible_groups()
        if not groups or self._state.inspect_set_id is None:
            return
        ids = [g.group_id for g in groups]
        try:
            idx = ids.index(self._state.inspect_set_id)
        except ValueError:
            idx = 0
        idx = max(0, idx - 1)
        self._state.inspect_set_id = ids[idx]
        self._render_active_screen()

    def _inspect_next(self, _e=None) -> None:
        groups = self._state.visible_groups()
        if not groups or self._state.inspect_set_id is None:
            return
        ids = [g.group_id for g in groups]
        try:
            idx = ids.index(self._state.inspect_set_id)
        except ValueError:
            idx = 0
        idx = min(len(ids) - 1, idx + 1)
        self._state.inspect_set_id = ids[idx]
        self._render_active_screen()

    def _apply_paths_for_group(self, group: DuplicateGroup, delete_paths: set[str]) -> None:
        self._state.push_undo_snapshot()
        sel = self._state.set_selections.setdefault(group.group_id, SetSelection())
        sel.deleted_paths = set(delete_paths)
        sel.kept_paths = {str(f.path) for f in group.files if str(f.path) not in delete_paths}
        self._state.marked_paths.update(delete_paths)
        self._push_marked_paths_to_store()

    def _inspect_keep_side(self, side_index: int) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group or not group.files:
            return
        keep = group.files[min(side_index, len(group.files) - 1)]
        delete_paths = {str(f.path) for f in group.files if str(f.path) != str(keep.path)}
        self._apply_paths_for_group(group, delete_paths)
        self._inspect_next()

    def _inspect_keep_both(self) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group:
            return
        self._state.push_undo_snapshot()
        sel = self._state.set_selections.setdefault(group.group_id, SetSelection())
        sel.kept_paths = {str(f.path) for f in group.files}
        sel.deleted_paths.clear()
        self._render_active_screen()

    def _inspect_delete_all(self) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group:
            return
        self._apply_paths_for_group(group, {str(f.path) for f in group.files})

    def _inspect_mark_next(self) -> None:
        self._inspect_delete_all()
        self._inspect_next()

    def _toggle_dry_run(self, e: ft.ControlEvent) -> None:
        self._state.dry_run = bool(getattr(e.control, "value", True))

    def _toggle_execute_confirm(self, e: ft.ControlEvent) -> None:
        self._state.execute_confirmed = bool(getattr(e.control, "value", False))

    def _run_execute(self, _e=None) -> None:
        if not self._state.execute_confirmed:
            self._show_toast("Confirm the checkbox before executing.")
            return
        buckets = self._state.cart_buckets()["delete"]
        paths = [str(f.path) for f in buckets]
        if self._state.dry_run:
            self._state.report_deleted_count = len(paths)
            self._state.report_freed_bytes = sum(int(f.size) for f in buckets)
            self._show_toast(f"Dry run: would remove {len(paths)} files.")
            self._router.navigate("report")
            self._render_active_screen()
            return
        self._state.execute_progress = (0, len(paths))
        self._state.execute_errors = []

        def on_progress(done: int, total: int, _name: str) -> None:
            self._state.execute_progress = (done, total)
            self._render_active_screen()

        deleted, failed, freed, _deleted_paths = self._delete_service.delete_files(
            paths,
            policy=DeletionPolicy.TRASH,
            progress_cb=on_progress,
        )
        self._state.report_deleted_count = deleted
        self._state.report_freed_bytes = freed
        if failed:
            self._state.execute_errors = [f"{failed} file(s) could not be deleted"]
        self._router.navigate("report")
        self._render_active_screen()

    def _open_auto_select_modal(self, _e=None) -> None:
        options = [ft.dropdown.Option(key, label) for key, label in RULE_LABELS]
        dd = ft.Dropdown(options=options, value=RULE_LABELS[0][0])

        def apply_rule(_ev=None) -> None:
            rule = dd.value or RULE_LABELS[0][0]
            self._state.push_undo_snapshot()
            for group in self._state.visible_groups():
                if any(self._state.is_path_protected(str(f.path)) for f in group.files):
                    continue
                to_delete = paths_to_delete(rule, group.files)
                self._apply_paths_for_group(group, set(to_delete))
            self._overlay_layer.controls.clear()
            self._show_toast(f"Applied {rule}")
            if self._browse_view:
                self._browse_view.refresh()
            self._safe_update(self)

        dlg = ft.AlertDialog(
            title=ft.Text("Auto-Select"),
            content=dd,
            actions=[ft.TextButton("Cancel", on_click=lambda e: self._close_overlay()), ft.FilledButton("Apply", on_click=apply_rule)],
        )
        self._overlay_layer.controls = [dlg]
        page = self._bridge.flet_page
        page.dialog = dlg
        dlg.open = True
        page.update()

    def _open_filter_sheet(self, _e=None) -> None:
        min_size = ft.TextField(label="Min size bytes", value=str(self._state.min_size_bytes))
        query = ft.TextField(label="Search", value=self._state.text_filter)

        def apply_filters(_ev=None) -> None:
            try:
                self._state.min_size_bytes = int(min_size.value or "0")
            except ValueError:
                self._state.min_size_bytes = 0
            self._state.text_filter = query.value or ""
            self._close_overlay()
            if self._browse_view:
                self._browse_view.refresh()

        sheet = ft.BottomSheet(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Filter & Sort", weight=ft.FontWeight.W_700),
                        query,
                        min_size,
                        ft.FilledButton("Apply", on_click=apply_filters),
                    ],
                    tight=True,
                ),
                padding=16,
            ),
            open=True,
        )
        self._bridge.flet_page.open(sheet)

    def _open_command_palette(self) -> None:
        field = ft.TextField(label="Command", autofocus=True)
        actions = {
            "invert": "Invert selection",
            "keep_newest": "Keep newest",
            "grid": "Switch to grid view",
        }

        def run_cmd(_e=None) -> None:
            cmd = (field.value or "").strip().lower()
            if cmd in {"invert", "invert selection"}:
                visible = {g.group_id for g in self._state.visible_groups()}
                selected = self._state.selected_set_ids
                self._state.selected_set_ids = visible - selected
            elif "keep newest" in cmd or cmd == "keep_newest":
                self._open_auto_select_modal()
            elif "grid" in cmd:
                self._state.view_mode = "grid"
            self._close_overlay()
            if self._browse_view:
                self._browse_view.refresh()

        dlg = ft.AlertDialog(
            title=ft.Text("Command Palette"),
            content=ft.Column([field, ft.Text("Try: invert, keep newest, grid")], tight=True),
            actions=[ft.TextButton("Close", on_click=lambda e: self._close_overlay()), ft.FilledButton("Run", on_click=run_cmd)],
        )
        page = self._bridge.flet_page
        page.dialog = dlg
        dlg.open = True
        page.update()

    def _open_export_modal(self, _e=None) -> None:
        def export_json(_ev=None) -> None:
            payload = {
                "version": 1,
                "marked_paths": sorted(self._state.marked_paths),
                "screen": self._router.active_screen(),
            }
            out = Path(self._bridge.get_settings().get("general", {}).get("export_dir", ".")) / "review_session.json"
            out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._show_toast(f"Exported {out.name}")
            self._close_overlay()

        dlg = ft.AlertDialog(
            title=ft.Text("Export"),
            content=ft.Text("Export current review session as JSON."),
            actions=[ft.TextButton("Close", on_click=lambda e: self._close_overlay()), ft.FilledButton("JSON", on_click=export_json)],
        )
        page = self._bridge.flet_page
        page.dialog = dlg
        dlg.open = True
        page.update()

    def _close_overlay(self) -> None:
        self._overlay_layer.controls.clear()
        page = self._bridge.flet_page
        if page.dialog:
            page.dialog.open = False
        page.update()

    def _show_toast(self, message: str) -> None:
        toast = ft.Container(
            content=ft.Text(message, color=self._t.colors.fg),
            bgcolor=ft.Colors.with_opacity(0.92, self._t.colors.surface),
            padding=10,
            border_radius=8,
        )
        self._toast_layer.controls = [ft.Container(content=toast, top=12, right=12)]
        self._safe_update(self._toast_layer)

    def _undo(self) -> None:
        if not self._state.undo_stack:
            return
        snap = self._state.undo_stack.pop()
        self._state.redo_stack.append(
            {
                "marked_paths": set(self._state.marked_paths),
                "selected_set_ids": set(self._state.selected_set_ids),
                "set_selections": dict(self._state.set_selections),
            }
        )
        self._state.restore_snapshot(snap)
        if self._browse_view:
            self._browse_view.refresh()

    def _redo(self) -> None:
        if not self._state.redo_stack:
            return
        snap = self._state.redo_stack.pop()
        self._state.undo_stack.append(
            {
                "marked_paths": set(self._state.marked_paths),
                "selected_set_ids": set(self._state.selected_set_ids),
                "set_selections": dict(self._state.set_selections),
            }
        )
        self._state.restore_snapshot(snap)
        if self._browse_view:
            self._browse_view.refresh()

    def _save_session(self) -> None:
        payload = {
            "version": 1,
            "active_screen": self._router.active_screen(),
            "marked_paths": sorted(self._state.marked_paths),
            "selected_set_ids": sorted(self._state.selected_set_ids),
        }
        path = Path(".") / "review_session.v1.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._show_toast("Session saved")

    def _push_marked_paths_to_store(self) -> None:
        self._bridge.store.dispatch(FileSelectionChanged(file_ids=tuple(self._state.marked_paths)))

    @staticmethod
    def _page_is_set(ctrl) -> bool:
        try:
            return ctrl.page is not None
        except RuntimeError:
            return False

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        if ctrl is None:
            return
        try:
            ctrl.update()
        except Exception:
            pass

    def enable_full_inspect(self) -> None:
        self._inspect_stub = False
