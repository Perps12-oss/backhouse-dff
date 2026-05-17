from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state.actions import FileSelectionChanged
from cerebro.v2.ui.flet_app.components.layout.responsive_grid import is_narrow_viewport
from cerebro.v2.ui.flet_app.pages.review_flow.apply_sheet import ApplyOutcomeModel, ApplyStep, build_apply_sheet_column
from cerebro.v2.ui.flet_app.pages.review_flow.progress_sidebar import build_progress_sidebar
from cerebro.v2.ui.flet_app.pages.review_flow.router import ReviewFlowRouter
from cerebro.v2.ui.flet_app.pages.review_flow.screens.browse import BrowseScreenView
from cerebro.v2.ui.flet_app.pages.review_flow.screens.inspect import build_inspect_screen
from cerebro.v2.ui.flet_app.pages.review_flow.screens.overview import build_overview_screen
from cerebro.v2.ui.flet_app.pages.review_flow.state import (
    ReviewFlowState,
    SetSelection,
    inspect_left_right_indices,
    make_index_reference,
    normalize_inspect_ref_cmp,
    pin_compare_as_new_reference,
    step_inspect_cmp,
)
from cerebro.core.deletion import DeletionPolicy
from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS, normalized_rule, paths_to_delete
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.v2.ui.flet_app.components.common.safe_controls import IMAGE_PLACEHOLDER_SRC
from cerebro.v2.ui.flet_app.services.thumbnail_cache import TINY_INSPECT_EDGE, get_thumbnail_cache
from cerebro.v2.ui.flet_app.pages.review_flow import skeletons
from cerebro.v2.ui.flet_app.theme import theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)
_UI_SLOW_MS = 80.0


class ReviewFlowHost(ft.Column):
    """Three-screen duplicate review host (overview → browse → inspect) with apply sheet."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, spacing=0)
        self._bridge = bridge
        self._t = theme_for_mode(self._bridge.app_theme)
        self._state = ReviewFlowState()
        self._state.protected_path_prefixes = ("/windows", "/system", "c:/windows")
        self._router = ReviewFlowRouter(self._state, self._render_active_screen)
        self._delete_service = DeleteService()
        self._browse_view: Optional[BrowseScreenView] = None
        self._content = ft.Container(expand=True)
        self._grid = ft.ListView(expand=True)
        self._workstation_sidebar = ft.Container(width=0)
        self._toast_layer = ft.Stack([])
        self._overlay_layer = ft.Stack([])
        self._filter_sheet: Optional[ft.BottomSheet] = None
        self._apply_sheet: Optional[ft.BottomSheet] = None
        self._apply_outer: Optional[ft.Container] = None
        self._apply_step: ApplyStep = "summary"
        self._apply_confirm_chk: Optional[ft.Checkbox] = None
        self._apply_progress: Optional[ft.ProgressBar] = None
        self._apply_progress_label: Optional[ft.Text] = None
        self._apply_undo_snapshot: Optional[dict] = None
        self._last_apply_outcome: Optional[ApplyOutcomeModel] = None
        self._inspect_stub = False
        self._inspect_preview_generation = 0
        self._reduce_motion = bool(bridge.is_reduce_motion_enabled())
        self._last_render_screen: Optional[str] = None
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
        self._render_active_screen()

    def _render_active_screen(self) -> None:
        started = time.perf_counter()
        t = self._t
        screen = self._router.active_screen()
        if screen not in ("overview", "browse", "inspect"):
            self._state.screen_stack = [s for s in self._state.screen_stack if s in ("overview", "browse", "inspect")]
            if not self._state.screen_stack:
                self._state.screen_stack = ["browse"]
            self._state.active_screen = self._state.screen_stack[-1]
            screen = self._state.active_screen
        if screen != "browse":
            self._state.browse_detail_group_id = None
        self._reduce_motion = bool(self._bridge.is_reduce_motion_enabled())
        prev_screen = self._last_render_screen
        page_width = getattr(self._bridge.flet_page, "width", None)
        if is_narrow_viewport(page_width):
            self._workstation_sidebar = ft.Container(width=0)
        else:
            self._workstation_sidebar = build_progress_sidebar(t, screen, self._state, self._on_progress_jump)
        self.controls[0].controls[0] = self._workstation_sidebar
        if screen == "overview":
            elapsed: Optional[float] = None
            sp = getattr(self._bridge.state, "scan_progress", None) or {}
            if isinstance(sp, dict):
                raw = sp.get("elapsed_seconds")
                if isinstance(raw, (int, float)) and float(raw) > 0:
                    elapsed = float(raw)
            overview_body = build_overview_screen(
                t,
                self._state.scan_results,
                on_start_review=self._on_start_review,
                recent_lines=self._recent_review_lines(),
                scan_elapsed_seconds=elapsed,
            )
            if len(self._state.scan_results) == 0:
                sk = skeletons.overview_skeleton(t, reduce_motion=self._reduce_motion)
                self._content.content = ft.Stack(
                    [
                        ft.Container(sk, expand=True, alignment=ft.Alignment.TOP_CENTER),
                        ft.Container(overview_body, expand=True),
                    ],
                    expand=True,
                )
            else:
                # Plain Column(expand=True) as the only child of Container(expand=True) can get
                # zero height on some Flet builds (blank after Apply → "Back to review").
                self._content.content = ft.Container(
                    expand=True,
                    alignment=ft.Alignment.TOP_CENTER,
                    content=overview_body,
                )
        elif screen == "browse":
            self._browse_view = BrowseScreenView(
                t,
                self._state,
                on_back=self._on_back,
                on_open_inspect=self._open_inspect,
                on_open_group_detail=self._browse_open_detail,
                on_close_group_detail=self._browse_close_detail,
                on_toggle_file_mark=self._browse_toggle_file_mark,
                on_apply_smart_rule_all=self._apply_smart_rule_all_visible,
                on_start_delete_ceremony=self._open_apply_sheet,
                on_proceed_execute=self._open_apply_sheet,
                reduce_motion=self._reduce_motion,
            )
            page = getattr(self._bridge, "flet_page", None)
            if page is not None:
                self._browse_view.attach_page(page)
            self._content.content = self._browse_view.root
            self._grid = self._browse_view.list_host
            self._browse_view.refresh()
        elif screen == "inspect":
            self._repair_inspect_indices_for_selection()
            inspect_col, slot_a, slot_b = build_inspect_screen(
                t,
                self._state,
                on_back=self._on_back,
                on_prev_set=self._inspect_prev,
                on_next_set=self._inspect_next,
                on_keep_left=lambda e: self._inspect_keep_physical_side(0),
                on_keep_right=lambda e: self._inspect_keep_physical_side(1),
                on_keep_both=lambda e: self._inspect_keep_both(),
                on_delete_all=lambda e: self._inspect_delete_all(),
                on_mark_next=lambda e: self._inspect_mark_next(),
                on_strip_tap=self._inspect_strip_tap,
                on_strip_long_make_reference=self._inspect_strip_make_reference,
                on_swap_panels=self._inspect_swap_panels,
                on_pin_compare_as_reference=self._inspect_pin_compare_as_reference,
                on_step_compare=self._inspect_step_compare,
                on_toggle_diff=self._toggle_inspect_diff,
                on_toggle_blink=self._toggle_inspect_blink,
                stub_only=self._inspect_stub,
            )
            self._content.content = inspect_col
            self._schedule_inspect_previews(slot_a, slot_b)
        if (
            not self._reduce_motion
            and prev_screen is not None
            and prev_screen != screen
            and self._page_is_set(self._content)
        ):
            try:
                self._content.opacity = 0.0
                self._content.animate_opacity = ft.Animation(220, ft.AnimationCurve.EASE_OUT)
                self._content.opacity = 1.0
            except Exception:
                self._content.opacity = 1.0
        self._last_render_screen = screen
        self._safe_update(self)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms > _UI_SLOW_MS:
            _log.debug("[UI_SLOW] review_flow render %s took %.1f ms", screen, elapsed_ms)

    def on_show(self) -> None:
        self._t = theme_for_mode(self._bridge.app_theme)
        self._state.marked_paths = set(self._bridge.state.selected_files)
        store_groups = list(getattr(self._bridge.state, "groups", []) or [])
        if store_groups:
            self._state.scan_results = store_groups
            self._state.scan_mode = getattr(self._bridge.state, "scan_mode", None) or "files"
        self._try_resume_session()
        self._render_active_screen()

    def reset_to_overview_after_scan(self) -> None:
        """Show the results summary screen after a scan completes."""
        store_groups = list(getattr(self._bridge.state, "groups", []) or [])
        if store_groups:
            self._state.scan_results = store_groups
            self._state.scan_mode = getattr(self._bridge.state, "scan_mode", None) or "files"
        self._router.reset_to_overview()
        if self._page_is_set(self):
            self._render_active_screen()

    def apply_theme(self, mode: str) -> None:
        """Sync review-flow tokens when global light/dark (or preset) changes; rebuilds the active screen."""
        m = "dark" if (mode or "").lower() == "dark" else "light"
        self._t = theme_for_mode(m)
        self._render_active_screen()
        if self._page_is_set(self):
            try:
                self.update()
            except Exception:
                pass

    def get_groups(self) -> List[DuplicateGroup]:
        return list(self._state.scan_results)

    def load_results(self, groups: List[DuplicateGroup], mode: str = "files", defer_render: bool = False) -> None:
        self._state.scan_results = list(groups)
        self._state.scan_mode = mode
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
                if self._state.browse_detail_group_id is not None:
                    return False
                groups = self._state.visible_groups()
                if groups:
                    idx = min(self._state.browse_focus_index, len(groups) - 1)
                    self._browse_open_detail(groups[idx].group_id)
                return True
            if key == "enter":
                groups = self._state.visible_groups()
                if groups:
                    idx = min(self._state.browse_focus_index, len(groups) - 1)
                    self._open_inspect(groups[idx].group_id)
                return True
        if screen == "inspect" and not self._inspect_stub:
            group = self._state.group_by_id(self._state.inspect_set_id or -1)
            n = len(group.files) if group else 0
            if key in ("bracketleft", "[", "pageup"):
                self._inspect_prev()
                return True
            if key in ("bracketright", "]", "pagedown"):
                self._inspect_next()
                return True
            if key in ("arrowleft", "left", "arrowup", "up"):
                if shift:
                    self._inspect_swap_panels()
                    return True
                if n > 2:
                    self._state.inspect_cmp_index = step_inspect_cmp(
                        n, self._state.inspect_ref_index, self._state.inspect_cmp_index, -1
                    )
                    self._persist_inspect_layout()
                    self._render_active_screen()
                return True
            if key in ("arrowright", "right", "arrowdown", "down"):
                if shift:
                    self._inspect_swap_panels()
                    return True
                if n > 2:
                    self._state.inspect_cmp_index = step_inspect_cmp(
                        n, self._state.inspect_ref_index, self._state.inspect_cmp_index, 1
                    )
                    self._persist_inspect_layout()
                    self._render_active_screen()
                return True
            if key == "p":
                self._inspect_pin_compare_as_reference()
                return True
            if key == "1":
                self._inspect_keep_physical_side(0)
                return True
            if key == "2":
                self._inspect_keep_physical_side(1)
                return True
            if key == "b":
                self._inspect_keep_both()
                return True
            if key == "d":
                self._toggle_inspect_diff_keyboard()
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

    def _persist_inspect_layout(self) -> None:
        gid = self._state.inspect_set_id
        if gid is None:
            return
        self._state.inspect_layout_by_set_id[gid] = (
            self._state.inspect_ref_index,
            self._state.inspect_cmp_index,
            self._state.inspect_swap_panels,
        )

    def _restore_inspect_layout_for_set(self, group_id: int) -> None:
        group = self._state.group_by_id(group_id)
        n = len(group.files) if group else 0
        if group_id in self._state.inspect_layout_by_set_id:
            ref, cmp_i, swap = self._state.inspect_layout_by_set_id[group_id]
            self._state.inspect_ref_index = ref
            self._state.inspect_cmp_index = cmp_i
            self._state.inspect_swap_panels = swap
        else:
            self._state.inspect_ref_index = 0
            self._state.inspect_cmp_index = 1 if n > 1 else 0
            self._state.inspect_swap_panels = False
        self._state.inspect_ref_index, self._state.inspect_cmp_index = normalize_inspect_ref_cmp(
            n, self._state.inspect_ref_index, self._state.inspect_cmp_index
        )

    def _repair_inspect_indices_for_selection(self) -> None:
        gid = self._state.inspect_set_id
        group = self._state.group_by_id(gid or -1)
        if not group or not group.files:
            return
        n = len(group.files)
        sel = self._state.set_selections.get(group.group_id)
        ref_i, cmp_i = self._state.inspect_ref_index, self._state.inspect_cmp_index
        ref_i, cmp_i = normalize_inspect_ref_cmp(n, ref_i, cmp_i)
        if sel:
            ref_path = str(group.files[ref_i].path)
            if ref_path in sel.deleted_paths or ref_path in self._state.marked_paths:
                for j, f in enumerate(group.files):
                    p = str(f.path)
                    if p not in sel.deleted_paths and p not in self._state.marked_paths:
                        ref_i = j
                        cmp_i = step_inspect_cmp(n, ref_i, ref_i, 1)
                        self._show_toast("Reference was marked for deletion; re-anchored to another file.")
                        break
        self._state.inspect_ref_index, self._state.inspect_cmp_index = normalize_inspect_ref_cmp(n, ref_i, cmp_i)
        self._persist_inspect_layout()

    def _open_inspect(self, group_id: int) -> None:
        self._state.inspect_set_id = group_id
        self._restore_inspect_layout_for_set(group_id)
        self._router.navigate("inspect")

    def _snapshot_apply_undo(self) -> dict:
        selections: dict[int, SetSelection] = {}
        for gid, sel in self._state.set_selections.items():
            selections[gid] = SetSelection(
                kept_paths=set(sel.kept_paths),
                deleted_paths=set(sel.deleted_paths),
                protected_paths=set(sel.protected_paths),
            )
        return {
            "scan_results": copy.deepcopy(self._state.scan_results),
            "marked_paths": set(self._state.marked_paths),
            "set_selections": selections,
        }

    def _restore_apply_undo_bundle(self, snap: dict) -> None:
        self._state.scan_results = copy.deepcopy(snap.get("scan_results", []))
        self._state.marked_paths = set(snap.get("marked_paths", set()))
        restored = snap.get("set_selections", {})
        if isinstance(restored, dict):
            self._state.set_selections = dict(restored)

    def _reconcile_state_after_delete(self, new_groups: List[DuplicateGroup]) -> None:
        self._state.scan_results = new_groups
        alive = {str(f.path) for g in new_groups for f in g.files}
        self._state.marked_paths &= alive
        alive_gids = {g.group_id for g in new_groups}
        for gid in list(self._state.set_selections.keys()):
            if gid not in alive_gids:
                del self._state.set_selections[gid]
                continue
            sel = self._state.set_selections[gid]
            sel.deleted_paths = {p for p in sel.deleted_paths if p in alive}
            sel.kept_paths = {p for p in sel.kept_paths if p in alive}
            sel.protected_paths = {p for p in sel.protected_paths if p in alive}

    def _apply_sheet_closed(self, _e=None) -> None:
        self._apply_sheet = None
        self._apply_confirm_chk = None

    def _apply_close_sheet(self, _e=None) -> None:
        try:
            self._bridge.dismiss_top_dialog()
        except Exception:
            pass
        self._apply_sheet_closed()

    def _apply_refresh_body(self) -> None:
        if self._apply_outer is None:
            return
        t = self._t
        buckets = self._state.cart_buckets()
        del_n = len(buckets["delete"])
        freed = sum(int(f.size) for f in buckets["delete"])
        prot_n = len(buckets["protected"])
        step = self._apply_step
        chk = self._apply_confirm_chk if step == "confirm" else None
        assert self._apply_progress is not None and self._apply_progress_label is not None
        col = build_apply_sheet_column(
            t,
            step=step,
            delete_count=del_n,
            freed_bytes=freed,
            protected_count=prot_n,
            confirm_checkbox=chk,
            progress_bar=self._apply_progress,
            progress_label=self._apply_progress_label,
            outcome=self._last_apply_outcome,
            reduce_motion=self._reduce_motion,
            on_close=lambda _e: self._apply_close_sheet(),
            on_continue_summary=lambda _e: self._apply_goto_confirm(),
            on_back_confirm=lambda _e: self._apply_goto_summary(),
            on_apply=lambda _e: self._apply_run_confirmed(),
            on_restore_managed=lambda _e: self._apply_restore_managed(),
            on_back_overview=lambda _e: self._apply_finish_overview(),
            on_new_scan=lambda _e: self._apply_finish_new_scan(),
        )
        self._apply_outer.content = col
        self._safe_update(self._apply_outer)

    def _open_apply_sheet(self, _e=None) -> None:
        buckets = self._state.cart_buckets()["delete"]
        if not buckets:
            self._show_toast("No files marked for removal. Apply a smart rule or pick files in a group.")
            return
        self._apply_step = "summary"
        self._last_apply_outcome = None
        self._apply_undo_snapshot = None
        self._apply_confirm_chk = ft.Checkbox(
            label="I understand these files will be moved to app-managed storage (not the OS Recycle Bin).",
            value=False,
        )
        self._apply_progress = ft.ProgressBar(value=0, width=400)
        self._apply_progress_label = ft.Text("Preparing…", size=self._t.typography.size_xs)
        self._apply_outer = ft.Container(padding=16, width=480)
        self._apply_refresh_body()
        self._apply_sheet = ft.BottomSheet(
            content=self._apply_outer,
            on_dismiss=lambda e: self._apply_sheet_closed(),
            scrollable=True,
            bgcolor=self._t.colors.bg2,
            show_drag_handle=True,
        )
        self._bridge.show_modal_dialog(self._apply_sheet)

    def _apply_goto_confirm(self, _e=None) -> None:
        self._apply_step = "confirm"
        self._apply_refresh_body()

    def _apply_goto_summary(self, _e=None) -> None:
        self._apply_step = "summary"
        self._apply_refresh_body()

    def _apply_run_confirmed(self, _e=None) -> None:
        if self._apply_confirm_chk is None or not self._apply_confirm_chk.value:
            self._show_toast("Confirm the checkbox before applying.")
            return
        self._apply_step = "progress"
        self._apply_progress.value = 0
        self._apply_progress_label.value = "Applying…"
        self._apply_refresh_body()
        self._apply_execute_deletes()

    def _apply_execute_deletes(self) -> None:
        buckets = self._state.cart_buckets()
        paths = [str(f.path) for f in buckets["delete"]]
        simulate = os.environ.get("CEREBRO_REVIEW_SIMULATE_APPLY", "").strip() in ("1", "true", "yes")
        if simulate:
            self._apply_undo_snapshot = self._snapshot_apply_undo()
            freed = sum(int(f.size) for f in buckets["delete"])
            self._state.report_deleted_count = len(paths)
            self._state.report_freed_bytes = freed
            self._state.execute_errors = []
            self._state.execute_failures_detail = []
            self._last_apply_outcome = ApplyOutcomeModel(
                deleted_count=len(paths),
                freed_bytes=freed,
                error_count=0,
                failures=[],
            )
            self._apply_step = "outcome"
            self._apply_refresh_body()
            self._show_apply_undo_toast(simulated=True)
            return

        self._apply_undo_snapshot = self._snapshot_apply_undo()

        def on_progress(done: int, total: int, _name: str) -> None:
            self._state.execute_progress = (done, total)
            if self._apply_progress:
                self._apply_progress.value = (done / total) if total else 0.0
            if self._apply_progress_label:
                self._apply_progress_label.value = f"{done}/{total} processed"
            self._safe_update(self._apply_outer)

        new_groups, dfr = self._delete_service.delete_and_prune(
            paths,
            self._state.scan_results,
            DeletionPolicy.TRASH,
            progress_cb=on_progress,
        )
        self._state.execute_failures_detail = list(dfr.failures)
        self._state.execute_errors = (
            [f"{dfr.failed_count} file(s) could not be moved"] if dfr.failed_count else []
        )
        self._state.report_deleted_count = dfr.deleted_count
        self._state.report_freed_bytes = dfr.bytes_reclaimed
        self._reconcile_state_after_delete(new_groups)
        self._push_marked_paths_to_store()
        self._last_apply_outcome = ApplyOutcomeModel(
            deleted_count=dfr.deleted_count,
            freed_bytes=dfr.bytes_reclaimed,
            error_count=dfr.failed_count,
            failures=list(dfr.failures),
        )
        self._apply_step = "outcome"
        self._apply_refresh_body()
        self._render_active_screen()
        self._show_apply_undo_toast(simulated=False)

    def _show_apply_undo_toast(self, *, simulated: bool) -> None:
        msg = "Simulated apply (no files moved)." if simulated else "Last batch can be restored from managed storage."
        self._show_toast(msg, action_label="Undo", on_action=self._toast_undo_last_apply)

    def _toast_undo_last_apply(self, _e=None) -> None:
        simulate = os.environ.get("CEREBRO_REVIEW_SIMULATE_APPLY", "").strip() in ("1", "true", "yes")
        if not simulate:
            DeleteService.undo_last_trash_delete()
        if self._apply_undo_snapshot is not None:
            self._restore_apply_undo_bundle(self._apply_undo_snapshot)
            self._apply_undo_snapshot = None
        self._push_marked_paths_to_store()
        self._render_active_screen()
        if self._browse_view:
            self._browse_view.refresh()
        self._show_toast("Restored previous review state.")

    def _apply_restore_managed(self, _e=None) -> None:
        self._toast_undo_last_apply()
        self._apply_close_sheet()

    def _apply_finish_overview(self, _e=None) -> None:
        self._apply_close_sheet()
        self._state.browse_detail_group_id = None
        if len(self._state.scan_results) > 0:
            # Go straight to Browse — avoid overview→browse in one click (double opacity transition
            # on _content can leave the page stuck transparent / blank on some Flet builds).
            self._state.screen_stack = ["overview", "browse"]
            self._state.active_screen = "browse"
        else:
            self._state.screen_stack = ["overview"]
            self._state.active_screen = "overview"
        self._render_active_screen()
        try:
            self._content.opacity = 1.0
            self._content.animate_opacity = None
        except Exception:
            pass
        self._safe_update(self._content)

    def _apply_finish_new_scan(self, _e=None) -> None:
        self._apply_close_sheet()
        self._bridge.navigate("dashboard")

    def _browse_open_detail(self, group_id: int) -> None:
        self._state.browse_detail_group_id = int(group_id)
        if self._browse_view:
            self._browse_view.refresh()

    def _browse_close_detail(self, _e=None) -> None:
        self._state.browse_detail_group_id = None
        if self._browse_view:
            self._browse_view.refresh()

    def _browse_toggle_file_mark(self, path: str, group_id: int, mark: bool) -> None:
        p = str(path)
        gid = int(group_id)
        sel = self._state.set_selections.setdefault(gid, SetSelection())
        if mark:
            self._state.marked_paths.add(p)
            sel.deleted_paths.add(p)
            sel.kept_paths.discard(p)
        else:
            self._state.marked_paths.discard(p)
            sel.deleted_paths.discard(p)
        self._push_marked_paths_to_store()
        if self._browse_view:
            self._browse_view.refresh()

    def _apply_smart_rule_all_visible(self, rule: str) -> None:
        """Mark delete candidates in every visible duplicate group using the smart rule."""
        r = normalized_rule(rule)
        self._state.push_undo_snapshot()
        groups_touched = 0
        files_marked = 0
        for group in self._state.visible_groups():
            if any(self._state.is_path_protected(str(f.path)) for f in group.files):
                continue
            to_delete = paths_to_delete(r, group.files)
            if not to_delete:
                continue
            self._apply_paths_for_group(group, set(to_delete))
            groups_touched += 1
            files_marked += len(to_delete)
        label = next((lbl for key, lbl in RULE_LABELS if key == r), r)
        if files_marked:
            self._show_toast(f"Smart select ({label}): {files_marked} file(s) in {groups_touched} group(s).")
        else:
            self._show_toast("Nothing to mark — adjust filters or pick another rule.")
        if self._browse_view:
            self._browse_view.refresh()
        self._rebuild_sidebar_in_place()
        self._defer_safe_update_content()

    def _defer_safe_update_content(self) -> None:
        """Defer parent content paint one frame — avoids blank main after heavy Browse refresh + dialog."""
        page = getattr(self._bridge, "flet_page", None)
        if page is None or not hasattr(page, "run_task"):
            self._safe_update(self._content)
            return

        async def _tick() -> None:
            await asyncio.sleep(0)
            self._safe_update(self._content)

        page.run_task(_tick)

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
        self._restore_inspect_layout_for_set(ids[idx])
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
        self._restore_inspect_layout_for_set(ids[idx])
        self._render_active_screen()

    def _inspect_strip_tap(self, member_index: int) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group or not group.files:
            return
        n = len(group.files)
        i = max(0, min(int(member_index), n - 1))
        if i == self._state.inspect_ref_index:
            return
        self._state.inspect_cmp_index = i
        self._state.inspect_ref_index, self._state.inspect_cmp_index = normalize_inspect_ref_cmp(
            n, self._state.inspect_ref_index, self._state.inspect_cmp_index
        )
        self._persist_inspect_layout()
        self._render_active_screen()

    def _inspect_strip_make_reference(self, member_index: int) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group or not group.files:
            return
        n = len(group.files)
        new_ref = max(0, min(int(member_index), n - 1))
        r, c = make_index_reference(n, self._state.inspect_ref_index, self._state.inspect_cmp_index, new_ref)
        self._state.inspect_ref_index, self._state.inspect_cmp_index = r, c
        self._persist_inspect_layout()
        self._render_active_screen()

    def _inspect_swap_panels(self, _e=None) -> None:
        self._state.inspect_swap_panels = not self._state.inspect_swap_panels
        self._persist_inspect_layout()
        self._render_active_screen()

    def _inspect_pin_compare_as_reference(self, _e=None) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group or not group.files:
            return
        n = len(group.files)
        if n < 2:
            return
        r, c = pin_compare_as_new_reference(n, self._state.inspect_ref_index, self._state.inspect_cmp_index)
        self._state.inspect_ref_index, self._state.inspect_cmp_index = r, c
        self._persist_inspect_layout()
        self._render_active_screen()

    def _inspect_step_compare(self, delta: int) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group or not group.files:
            return
        n = len(group.files)
        if n <= 2:
            return
        self._state.inspect_cmp_index = step_inspect_cmp(
            n, self._state.inspect_ref_index, self._state.inspect_cmp_index, int(delta)
        )
        self._persist_inspect_layout()
        self._render_active_screen()

    def _apply_paths_for_group(self, group: DuplicateGroup, delete_paths: set[str]) -> None:
        self._state.push_undo_snapshot()
        sel = self._state.set_selections.setdefault(group.group_id, SetSelection())
        sel.deleted_paths = set(delete_paths)
        sel.kept_paths = {str(f.path) for f in group.files if str(f.path) not in delete_paths}
        self._state.marked_paths.update(delete_paths)
        self._push_marked_paths_to_store()

    def _inspect_keep_physical_side(self, physical_side: int) -> None:
        """physical_side 0 = left column file, 1 = right column file (after swap)."""
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group or not group.files:
            return
        n = len(group.files)
        left_i, right_i = inspect_left_right_indices(
            self._state.inspect_swap_panels,
            self._state.inspect_ref_index,
            self._state.inspect_cmp_index,
        )
        pick_i = left_i if physical_side == 0 else right_i
        keep = group.files[pick_i]
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

    def _schedule_inspect_previews(self, slot_a: Optional[ft.Container], slot_b: Optional[ft.Container]) -> None:
        self._inspect_preview_generation += 1
        gen = self._inspect_preview_generation
        page = getattr(self._bridge, "flet_page", None)
        if page is None or (slot_a is None and slot_b is None):
            return
        if hasattr(page, "run_task"):
            page.run_task(self._load_inspect_previews_async, slot_a, slot_b, gen)
        else:
            self._load_inspect_previews_sync(slot_a, slot_b, gen)

    async def _load_inspect_previews_async(
        self,
        slot_a: Optional[ft.Container],
        slot_b: Optional[ft.Container],
        gen: int,
    ) -> None:
        loop = asyncio.get_event_loop()
        cache = get_thumbnail_cache()
        rm = self._reduce_motion

        async def _decode(slot: Optional[ft.Container]) -> None:
            if slot is None or gen != self._inspect_preview_generation:
                return
            path = getattr(slot, "data", None)
            if not path:
                return
            p = Path(str(path))
            tiny_b64 = await loop.run_in_executor(cache._pool, cache.get_preview_tiny_base64, p, TINY_INSPECT_EDGE)
            if gen != self._inspect_preview_generation:
                return
            layers: list[ft.Control] = []
            if tiny_b64:
                layers.append(
                    ft.Image(
                        src=f"data:image/jpeg;base64,{tiny_b64}",
                        width=340,
                        height=400,
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                    )
                )
            full_img = ft.Image(
                src=IMAGE_PLACEHOLDER_SRC,
                width=340,
                height=400,
                fit=ft.BoxFit.CONTAIN,
                border_radius=8,
            )
            full_wrap = ft.Container(
                content=full_img,
                opacity=1.0 if rm else 0.0,
                animate_opacity=None if rm else ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            )
            layers.append(full_wrap)
            slot.content = ft.Stack(controls=layers, width=340, height=400)
            self._safe_update(slot)

            full_b64 = await loop.run_in_executor(cache._pool, cache.get_compare_preview_base64, p)
            if gen != self._inspect_preview_generation or not full_b64:
                return
            full_img.src = f"data:image/jpeg;base64,{full_b64}"
            if not rm:
                full_wrap.opacity = 1.0
            self._safe_update(slot)

        await _decode(slot_a)
        await _decode(slot_b)

    def _load_inspect_previews_sync(
        self,
        slot_a: Optional[ft.Container],
        slot_b: Optional[ft.Container],
        gen: int,
    ) -> None:
        cache = get_thumbnail_cache()
        for slot in (slot_a, slot_b):
            if slot is None or gen != self._inspect_preview_generation:
                continue
            path = getattr(slot, "data", None)
            if not path:
                continue
            p = Path(str(path))
            tiny_b64 = cache.get_preview_tiny_base64(p, TINY_INSPECT_EDGE)
            layers: list[ft.Control] = []
            if tiny_b64:
                layers.append(
                    ft.Image(
                        src=f"data:image/jpeg;base64,{tiny_b64}",
                        width=340,
                        height=400,
                        fit=ft.BoxFit.CONTAIN,
                        border_radius=8,
                    )
                )
            full_b64 = cache.get_compare_preview_base64(p)
            if not full_b64:
                continue
            full_img = ft.Image(
                src=f"data:image/jpeg;base64,{full_b64}",
                width=340,
                height=400,
                fit=ft.BoxFit.CONTAIN,
                border_radius=8,
            )
            full_wrap = ft.Container(content=full_img, opacity=1.0)
            layers.append(full_wrap)
            slot.content = ft.Stack(controls=layers, width=340, height=400)
            self._safe_update(slot)

    def _toggle_inspect_diff(self, e: ft.ControlEvent) -> None:
        self._state.inspect_diff_enabled = bool(getattr(e.control, "value", False))
        self._run_inspect_diff_if_enabled()
        self._render_active_screen()

    def _toggle_inspect_diff_keyboard(self) -> None:
        self._state.inspect_diff_enabled = not self._state.inspect_diff_enabled
        self._run_inspect_diff_if_enabled()
        self._render_active_screen()

    def _run_inspect_diff_if_enabled(self) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group or len(group.files) < 2 or not self._state.inspect_diff_enabled:
            return
        from cerebro.v2.ui.flet_app.pages.review_flow.image_diff import build_diff_heatmap_path

        n = len(group.files)
        ref_i, cmp_i = normalize_inspect_ref_cmp(
            n, self._state.inspect_ref_index, self._state.inspect_cmp_index
        )
        build_diff_heatmap_path(group.files[ref_i].path, group.files[cmp_i].path)

    def _toggle_inspect_blink(self, e: ft.ControlEvent) -> None:
        self._state.inspect_blink_enabled = bool(getattr(e.control, "value", False))
        self._render_active_screen()

    def _show_modal(self, dialog: ft.AlertDialog) -> None:
        self._bridge.show_modal_dialog(dialog)

    def _rebuild_sidebar_in_place(self) -> None:
        """Rebuild the sidebar stat counts without recreating the full screen."""
        page_width = getattr(self._bridge.flet_page, "width", None)
        if not is_narrow_viewport(page_width):
            self._workstation_sidebar = build_progress_sidebar(
                self._t, self._router.active_screen(), self._state, self._on_progress_jump
            )
            self.controls[0].controls[0] = self._workstation_sidebar
        self._safe_update(self)

    def _navigate_browse_after_modal_from_overview(self) -> None:
        """Defer one frame so dialog dismiss finishes before rebuilding Browse (avoids blank main)."""
        page = self._bridge.flet_page

        def _paint_browse() -> None:
            if self._router.active_screen() == "overview":
                self._router.navigate("browse")
            elif self._router.active_screen() == "browse" and self._browse_view is not None:
                self._browse_view.refresh()
            self._safe_update(self._content)

        if hasattr(page, "run_task"):

            async def _deferred() -> None:
                await asyncio.sleep(0)
                _paint_browse()

            page.run_task(_deferred)
        else:
            _paint_browse()

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
            self._close_overlay()
            self._show_toast(f"Applied {rule}")
            if self._router.active_screen() == "overview":
                self._navigate_browse_after_modal_from_overview()
            elif self._browse_view:
                self._browse_view.refresh()
                self._schedule_browse_apply_wave()
            else:
                self._render_active_screen()

        dlg = ft.AlertDialog(
            title=ft.Text("Auto-Select"),
            content=dd,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_overlay()),
                ft.FilledButton("OK", on_click=apply_rule),
            ],
        )
        self._show_modal(dlg)

    def _schedule_browse_apply_wave(self) -> None:
        if self._reduce_motion or self._browse_view is None:
            return
        page = getattr(self._bridge, "flet_page", None)
        if page is None or not hasattr(page, "run_task"):
            return
        page.run_task(self._browse_apply_wave_async)

    async def _browse_apply_wave_async(self) -> None:
        view = self._browse_view
        if view is None:
            return
        t = self._t
        flash = ft.Colors.with_opacity(0.22, t.colors.success)
        lst = view.list_host
        prepared: list[tuple[ft.Container, object]] = []
        for ctrl in list(lst.controls)[:40]:
            if isinstance(ctrl, ft.Container):
                prepared.append((ctrl, ctrl.bgcolor))
        for row, orig in prepared:
            try:
                row.bgcolor = flash
                lst.update()
            except Exception:
                pass
            await asyncio.sleep(0.05)
            try:
                row.bgcolor = orig
                lst.update()
            except Exception:
                pass

    def _close_filter_sheet(self) -> None:
        if self._filter_sheet is None:
            return
        try:
            self._bridge.dismiss_top_dialog()
        except Exception:
            pass
        self._filter_sheet = None

    def _open_filter_sheet(self, _e=None) -> None:
        min_size = ft.TextField(label="Min size bytes", value=str(self._state.min_size_bytes))
        query = ft.TextField(label="Search", value=self._state.text_filter)

        def apply_filters(_ev=None) -> None:
            try:
                self._state.min_size_bytes = int(min_size.value or "0")
            except ValueError:
                self._state.min_size_bytes = 0
            self._state.text_filter = query.value or ""
            self._close_filter_sheet()
            if self._router.active_screen() == "overview":
                self._navigate_browse_after_modal_from_overview()
                return
            if self._browse_view:
                self._browse_view.refresh()
            else:
                self._render_active_screen()

        sheet = ft.BottomSheet(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Filter & Sort", weight=ft.FontWeight.W_700),
                        query,
                        min_size,
                        ft.Row(
                            [
                                ft.TextButton("Cancel", on_click=lambda e: self._close_filter_sheet()),
                                ft.FilledButton("OK", on_click=apply_filters),
                            ],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    tight=True,
                ),
                padding=16,
                width=400,
            ),
            on_dismiss=lambda e: setattr(self, "_filter_sheet", None),
            scrollable=True,
            bgcolor=self._t.colors.bg2,
            show_drag_handle=True,
        )
        self._filter_sheet = sheet
        self._bridge.show_modal_dialog(sheet)

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
        self._show_modal(dlg)

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

        def export_csv(_ev=None) -> None:
            out = Path(self._bridge.get_settings().get("general", {}).get("export_dir", ".")) / "review_export.csv"
            lines = ["path,action"]
            for path in sorted(self._state.marked_paths):
                lines.append(f"{path},delete")
            out.write_text("\n".join(lines), encoding="utf-8")
            self._show_toast(f"Exported {out.name}")
            self._close_overlay()

        def export_html(_ev=None) -> None:
            out = Path(self._bridge.get_settings().get("general", {}).get("export_dir", ".")) / "review_export.html"
            rows = "".join(f"<li>{p}</li>" for p in sorted(self._state.marked_paths))
            out.write_text(f"<html><body><h1>Review export</h1><ul>{rows}</ul></body></html>", encoding="utf-8")
            self._show_toast(f"Exported {out.name}")
            self._close_overlay()

        dlg = ft.AlertDialog(
            title=ft.Text("Export"),
            content=ft.Text("Export current review session."),
            actions=[
                ft.TextButton("Close", on_click=lambda e: self._close_overlay()),
                ft.FilledButton("JSON", on_click=export_json),
                ft.FilledButton("CSV", on_click=export_csv),
                ft.FilledButton("HTML", on_click=export_html),
            ],
        )
        self._show_modal(dlg)

    def _close_overlay(self) -> None:
        self._close_filter_sheet()
        self._overlay_layer.controls.clear()
        try:
            self._bridge.dismiss_top_dialog()
        except Exception:
            page = self._bridge.flet_page
            if getattr(page, "dialog", None):
                page.dialog.open = False
            page.update()

    def _show_toast(
        self,
        message: str,
        *,
        action_label: Optional[str] = None,
        on_action: Optional[Callable[[ft.ControlEvent], None]] = None,
    ) -> None:
        row_children: list[ft.Control] = [ft.Text(message, color=self._t.colors.fg)]
        if action_label and on_action is not None:
            row_children.append(ft.TextButton(action_label, on_click=on_action))
        toast = ft.Container(
            content=ft.Row(row_children, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=ft.Colors.with_opacity(0.92, self._t.colors.bg2),
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

    def _try_resume_session(self) -> None:
        path = Path("review_session.v1.json")
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._state.marked_paths = set(payload.get("marked_paths", []))
        self._state.selected_set_ids = set(payload.get("selected_set_ids", []))
        layout_raw = payload.get("inspect_layout_by_set", {})
        if isinstance(layout_raw, dict):
            parsed: dict[int, tuple[int, int, bool]] = {}
            for k, v in layout_raw.items():
                try:
                    gid = int(k)
                    if isinstance(v, (list, tuple)) and len(v) >= 3:
                        parsed[gid] = (int(v[0]), int(v[1]), bool(v[2]))
                except (TypeError, ValueError):
                    continue
            self._state.inspect_layout_by_set_id = parsed
        screen = payload.get("active_screen")
        if screen == "cart":
            screen = "browse"
        if screen in {"execute", "report"}:
            screen = "browse"
        if screen in {"overview", "browse", "inspect"}:
            self._router.reset_to_overview()
            self._router.navigate(screen)

    def _save_session(self) -> None:
        payload = {
            "version": 1,
            "active_screen": self._router.active_screen(),
            "marked_paths": sorted(self._state.marked_paths),
            "selected_set_ids": sorted(self._state.selected_set_ids),
            "inspect_layout_by_set": {
                str(gid): [ref, cmp_i, swap]
                for gid, (ref, cmp_i, swap) in sorted(self._state.inspect_layout_by_set_id.items())
            },
        }
        path = Path(".") / "review_session.v1.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._show_toast("Session saved")

    def _recent_review_lines(self) -> list[str]:
        path = Path("review_session.v1.json")
        if path.exists():
            return [f"Resumable session ({path.name})"]
        return ["No saved sessions yet"]

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
