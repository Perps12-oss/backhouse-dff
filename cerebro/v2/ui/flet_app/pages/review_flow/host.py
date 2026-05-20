from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.state.actions import FileSelectionChanged, GroupsPruned
from cerebro.v2.ui.flet_app.components.layout.responsive_grid import is_narrow_viewport
from cerebro.v2.ui.flet_app.pages.review_flow.apply_sheet import ApplyOutcomeModel, ApplyStep, build_apply_sheet_column
from cerebro.v2.ui.flet_app.pages.review_flow.browse_workbench import (
    build_browse_workstation_sidebar,
    refresh_browse_workstation_sidebar,
)
from cerebro.v2.ui.flet_app.pages.review_flow.progress_sidebar import (
    ProgressSidebarRefs,
    build_progress_sidebar,
    refresh_progress_sidebar,
)
from cerebro.v2.ui.flet_app.pages.review_flow.router import ReviewFlowRouter
from cerebro.v2.ui.flet_app.pages.review_flow.screens.browse import BrowseScreenView
from cerebro.v2.ui.flet_app.pages.review_flow.screens.inspect import build_inspect_screen
from cerebro.v2.ui.flet_app.pages.review_flow.screens.overview import build_overview_screen
from cerebro.v2.ui.flet_app.pages.review_flow.media_filter import (
    filter_paths_for_media_scope,
    normalized_media_type,
)
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
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.v2.ui.flet_app.components.common.safe_controls import IMAGE_PLACEHOLDER_SRC
from cerebro.v2.ui.flet_app.media_preview import build_media_placeholder
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
        self._sidebar_refs: Optional[ProgressSidebarRefs] = None
        self._browse_sidebar_shell: Optional[ft.Container] = None
        self._browse_workbench_slot: Optional[ft.Container] = None
        self._toast_layer = ft.Stack([])
        self._overlay_layer = ft.Stack([])
        self._filter_sheet: Optional[ft.AlertDialog] = None
        self._apply_dialog: Optional[ft.AlertDialog] = None
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
        self._skip_content_fade = False
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
        if self._state.scan_results:
            self._state._recompute_cart_counters()
        self._reduce_motion = bool(self._bridge.is_reduce_motion_enabled())
        prev_screen = self._last_render_screen
        page_width = getattr(self._bridge.flet_page, "width", None)
        narrow = is_narrow_viewport(page_width)
        if narrow:
            self._workstation_sidebar = ft.Container(width=0)
            self._sidebar_refs = None
        elif screen == "browse":
            if self._browse_sidebar_shell is None:
                self._browse_sidebar_shell, self._sidebar_refs, self._browse_workbench_slot = (
                    build_browse_workstation_sidebar(t, self._state, self._on_progress_jump)
                )
            else:
                refresh_browse_workstation_sidebar(
                    self._sidebar_refs, self._browse_sidebar_shell, self._state
                )
            self._workstation_sidebar = self._browse_sidebar_shell
        else:
            self._workstation_sidebar, self._sidebar_refs = build_progress_sidebar(
                t, screen, self._state, self._on_progress_jump
            )
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
                self._content.content = ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    content=overview_body,
                )
            else:
                # Plain Column(expand=True) as the only child of Container(expand=True) can get
                # zero height on some Flet builds (blank after Apply → "Back to review").
                self._content.content = ft.Container(
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    content=overview_body,
                )
        elif screen == "browse":
            page = getattr(self._bridge, "flet_page", None)
            if self._browse_view is None:
                self._browse_view = BrowseScreenView(
                    t,
                    self._state,
                    on_back=self._on_back,
                    on_open_inspect=self._open_inspect,
                    on_open_group_detail=self._browse_open_detail,
                    on_close_group_detail=self._browse_close_detail,
                    on_toggle_file_mark=self._browse_toggle_file_mark,
                    on_start_delete_ceremony=self._open_apply_sheet,
                    on_proceed_execute=self._open_apply_sheet,
                    on_apply_smart_rule=self._apply_smart_rule_to_all,
                    on_undo_smart=self._undo,
                    on_media_filter_changed=self._on_media_filter_changed,
                    reduce_motion=self._reduce_motion,
                )
                if page is not None:
                    self._browse_view.attach_page(page)
            else:
                self._browse_view.apply_theme(t)
                self._browse_view.set_reduce_motion(self._reduce_motion)
                if page is not None:
                    self._browse_view.attach_page(page)
            self._content.content = self._browse_view.root
            self._grid = self._browse_view.list_host
            self._ensure_content_visible()
            if narrow:
                self._browse_view.set_narrow_mode(True)
            else:
                self._browse_view.set_narrow_mode(False)
                if self._browse_workbench_slot is not None:
                    self._browse_view.attach_workbench(self._browse_workbench_slot)
            if prev_screen != "browse" or not list(getattr(self._browse_view.list_host, "controls", None) or []):
                self._browse_view.refresh()
            else:
                self._browse_view.refresh_workbench_chrome(
                    in_detail=self._state.browse_detail_group_id is not None
                )
            self._update_sidebar_counts_only()
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
            and not self._skip_content_fade
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
            self._state.rebuild_group_index()
            self._state.invalidate_visible_cache()
        self._try_resume_session()
        if self._state.scan_results:
            self._state._recompute_cart_counters()
            self._repair_review_surface(self._state.active_screen)
        else:
            self._render_active_screen()

    def reset_to_overview_after_scan(self) -> None:
        """Show the results summary screen after a scan completes."""
        store_groups = list(getattr(self._bridge.state, "groups", []) or [])
        if store_groups:
            self._state.scan_results = store_groups
            self._state.scan_mode = getattr(self._bridge.state, "scan_mode", None) or "files"
            self._state.rebuild_group_index()
            self._state.invalidate_visible_cache()
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
        self._state.rebuild_group_index()
        self._state.invalidate_visible_cache()
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
            else:
                self._ensure_content_visible()
                self._repair_review_surface(screen)
        else:
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
        # P0-4 — cap inspect_layout_by_set_id at 200 entries
        if len(self._state.inspect_layout_by_set_id) > 200:
            oldest = next(iter(self._state.inspect_layout_by_set_id))
            del self._state.inspect_layout_by_set_id[oldest]

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

    def _push_delete_undo_bundle(self, paths_to_delete: list) -> None:
        """Phase 2 — Build a lightweight undo bundle without deepcopy of all scan_results."""
        path_set = set(paths_to_delete)
        affected_groups = [
            g for g in self._state.scan_results
            if any(str(f.path) in path_set for f in g.files)
        ]
        affected_gids = {g.group_id for g in affected_groups}
        self._state.undo_stack.append({
            "type": "delete_batch",
            "deleted_paths": list(paths_to_delete),
            "affected_groups_before": affected_groups,
            "marked_paths_before": set(self._state.marked_paths),
            "set_selections_before": {
                gid: SetSelection(
                    kept_paths=set(sel.kept_paths),
                    deleted_paths=set(sel.deleted_paths),
                    protected_paths=set(sel.protected_paths),
                )
                for gid, sel in self._state.set_selections.items()
                if gid in affected_gids
            },
        })
        self._state.redo_stack.clear()
        while len(self._state.undo_stack) > 50:
            self._state.undo_stack.pop(0)

    def _undo_delete_bundle(self, bundle: dict) -> None:
        """Phase 2 — Restore state from a delete_batch undo bundle."""
        restored_groups = bundle.get("affected_groups_before", [])
        restored_gids = {g.group_id for g in restored_groups}
        new_results = [g for g in self._state.scan_results if g.group_id not in restored_gids]
        new_results.extend(restored_groups)
        self._state.scan_results = new_results
        self._state.marked_paths = set(bundle.get("marked_paths_before", set()))
        for gid, sel in bundle.get("set_selections_before", {}).items():
            self._state.set_selections[gid] = sel
        self._state.rebuild_group_index()
        self._state.invalidate_visible_cache()
        self._state._recompute_cart_counters()


    def _restore_apply_undo_bundle(self, snap: dict) -> None:
        self._state.rebuild_group_index()
        self._state.invalidate_visible_cache()
        self._state.marked_paths = set(snap.get("marked_paths", set()))
        restored = snap.get("set_selections", {})
        if isinstance(restored, dict):
            self._state.set_selections = dict(restored)
        self._state._recompute_cart_counters()

    def _reconcile_state_after_delete(self, new_groups: List[DuplicateGroup]) -> None:
        self._state.scan_results = new_groups
        self._state.rebuild_group_index()
        self._state.invalidate_visible_cache()
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
        for gid in list(self._state.smart_rule_by_group.keys()):
            if gid not in alive_gids:
                del self._state.smart_rule_by_group[gid]
        self._state._recompute_cart_counters()
        try:
            self._bridge.store.dispatch(GroupsPruned(groups=tuple(new_groups)))
        except Exception:
            _log.debug("GroupsPruned dispatch failed", exc_info=True)

    def _apply_dialog_closed(self, _e=None) -> None:
        self._apply_dialog = None
        self._apply_confirm_chk = None

    def _apply_close_sheet(self, _e=None) -> None:
        try:
            self._bridge.dismiss_top_dialog()
        except Exception:
            pass
        self._apply_dialog_closed()

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
            self._show_toast("No files marked for removal. Use checkboxes on groups, then try again.")
            return
        self._push_marked_paths_to_store()
        self._apply_step = "summary"
        self._last_apply_outcome = None
        self._apply_undo_snapshot = None
        self._apply_confirm_chk = ft.Checkbox(
            label="I understand these files will be moved to app-managed storage (not the OS Recycle Bin).",
            value=False,
        )
        self._apply_progress = ft.ProgressBar(value=0, width=400)
        self._apply_progress_label = ft.Text("Preparing…", size=self._t.typography.size_xs)
        self._apply_outer = ft.Container(padding=0, width=480)
        self._apply_refresh_body()
        # BottomSheet + show_dialog never painted on Flet 0.84 desktop in the field;
        # AlertDialog matches dashboard pattern and is reliably visible on Flet 0.84.
        self._apply_dialog = ft.AlertDialog(
            modal=True,
            content=self._apply_outer,
            content_padding=ft.padding.all(16),
            bgcolor=self._t.colors.bg2,
            shape=ft.RoundedRectangleBorder(radius=16),
            inset_padding=ft.padding.symmetric(horizontal=24, vertical=48),
        )
        self._bridge.show_modal_dialog(self._apply_dialog)

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
            self._push_delete_undo_bundle(paths)
            self._apply_undo_snapshot = self._state.undo_stack[-1] if self._state.undo_stack else None
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

        self._push_delete_undo_bundle(paths)
        self._apply_undo_snapshot = self._state.undo_stack[-1] if self._state.undo_stack else None

        def on_progress(done: int, total: int, _name: str) -> None:
            frac = (done / total) if total else 0.0
            pct = int(frac * 100)

            def _ui_progress() -> None:
                self._state.execute_progress = (done, total)
                if self._apply_progress:
                    self._apply_progress.value = frac
                if self._apply_progress_label:
                    self._apply_progress_label.value = f"{done}/{total} processed ({pct}%)"
                self._safe_update(self._apply_outer)

            flet_page = self._bridge.flet_page
            if hasattr(flet_page, "run_thread"):
                flet_page.run_thread(_ui_progress)
            else:
                _ui_progress()

        def on_done(new_groups, deleted_count, failed_count, bytes_reclaimed, exc) -> None:
            def _finish() -> None:
                if exc is not None:
                    self._state.execute_errors = [str(exc)]
                    self._apply_step = "outcome"
                    self._apply_refresh_body()
                    return
                self._state.execute_failures_detail = []
                self._state.execute_errors = (
                    [f"{failed_count} file(s) could not be moved"] if failed_count else []
                )
                self._state.report_deleted_count = deleted_count
                self._state.report_freed_bytes = bytes_reclaimed
                self._reconcile_state_after_delete(new_groups)
                self._push_marked_paths_to_store()
                self._bridge.invalidate_stats_cache()
                self._last_apply_outcome = ApplyOutcomeModel(
                    deleted_count=deleted_count,
                    freed_bytes=bytes_reclaimed,
                    error_count=failed_count,
                    failures=[],
                )
                self._apply_step = "outcome"
                self._apply_refresh_body()
                self._update_sidebar_counts_only()
                self._show_apply_undo_toast(simulated=False)

            flet_page = self._bridge.flet_page
            if hasattr(flet_page, "run_thread"):
                flet_page.run_thread(_finish)
            else:
                _finish()

        self._delete_service.delete_and_prune_async(
            paths,
            self._state.scan_results,
            DeletionPolicy.TRASH,
            progress_callback=on_progress,
            done_callback=on_done,
        )

    def _show_apply_undo_toast(self, *, simulated: bool) -> None:
        msg = "Simulated apply (no files moved)." if simulated else "Last batch can be restored from managed storage."
        self._show_toast(msg, action_label="Undo", on_action=self._toast_undo_last_apply)

    def _toast_undo_last_apply(self, _e=None) -> None:
        simulate = os.environ.get("CEREBRO_REVIEW_SIMULATE_APPLY", "").strip() in ("1", "true", "yes")
        if not simulate:
            self._delete_service.undo_last_trash_delete()
        if self._apply_undo_snapshot is not None:
            bundle = self._apply_undo_snapshot
            if isinstance(bundle, dict) and bundle.get("type") == "delete_batch":
                self._undo_delete_bundle(bundle)
            else:
                self._restore_apply_undo_bundle(bundle)
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
        """Return to browse (or overview if nothing left) after delete outcome."""
        self._apply_close_sheet()
        self._state.browse_detail_group_id = None
        self._state.page_index = 0
        if len(self._state.scan_results) > 0:
            self._state.screen_stack = ["overview", "browse"]
            self._state.active_screen = "browse"
        else:
            self._state.screen_stack = ["overview"]
            self._state.active_screen = "overview"

        def _paint_after_dialog() -> None:
            self._ensure_content_visible()
            self._render_active_screen()
            if self._state.active_screen == "browse" and self._browse_view is not None:
                # Stale list_host controls after delete skip refresh() and leave a blank pane.
                self._browse_view.refresh(rebuild=True)
            self._ensure_content_visible()
            self._safe_update(self._content)

        self._schedule_after_handler_frame(_paint_after_dialog)

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
        group = self._state.group_by_id(gid)
        if group is not None:
            file_row = next((f for f in group.files if str(f.path) == p), None)
            if file_row is not None and not self._state.file_in_selection_media_scope(file_row):
                self._show_toast(
                    f"Media filter is on — only "
                    f"{normalized_media_type(self._state.selection_media_type)} files can be marked."
                )
                if self._browse_view:
                    self._browse_view.sync_checkbox_marks()
                return
        sel = self._state.set_selections.setdefault(gid, SetSelection())
        if mark:
            self._state.marked_paths.add(p)
            sel.deleted_paths.add(p)
            sel.kept_paths.discard(p)
        else:
            self._state.marked_paths.discard(p)
            sel.deleted_paths.discard(p)
        # Manual toggle invalidates any smart rule reason label for this group.
        self._state.smart_rule_by_group.pop(gid, None)
        self._state._recompute_cart_counters()
        self._push_marked_paths_to_store()
        if self._browse_view:
            self._browse_view.sync_checkbox_marks()
            self._browse_view.update_cart_chrome()
        self._update_sidebar_counts_only()

    def _apply_smart_rule_to_all(self, rule: str) -> None:
        from cerebro.v2.ui.flet_app.pages.review_flow.smart_rules import apply_rule_with_pipeline

        self._state.push_undo_snapshot()
        groups = self._state.visible_groups()
        for group in groups:
            scoped = (
                [f for f in group.files if self._state.file_in_selection_media_scope(f)]
                if self._state.selection_media_filter_enabled
                else list(group.files)
            )
            if len(scoped) < 2:
                continue
            try:
                keeper = apply_rule_with_pipeline(rule, scoped)
            except Exception:
                keeper = scoped[0]
            gid = group.group_id
            sel = self._state.set_selections.setdefault(gid, SetSelection())
            keeper_path = str(keeper.path)
            for f in group.files:
                p = str(f.path)
                if not self._state.file_in_selection_media_scope(f):
                    continue
                if p == keeper_path:
                    sel.kept_paths.add(p)
                    sel.deleted_paths.discard(p)
                    self._state.marked_paths.discard(p)
                else:
                    sel.kept_paths.discard(p)
                    sel.deleted_paths.add(p)
                    self._state.marked_paths.add(p)
            self._state.smart_rule_by_group[gid] = rule
        self._state._recompute_cart_counters()
        self._push_marked_paths_to_store()
        if self._browse_view:
            self._browse_view.refresh()
        self._update_sidebar_counts_only()

    def _on_media_filter_changed(self, enabled: bool, media_type: str) -> None:
        self._state.selection_media_filter_enabled = bool(enabled)
        self._state.selection_media_type = normalized_media_type(media_type)
        self._state.prune_marks_outside_media_scope()
        self._state.invalidate_visible_cache()
        self._state.page_index = 0
        self._state._recompute_cart_counters()
        self._push_marked_paths_to_store()
        if self._browse_view:
            self._browse_view.refresh_media_filter_chrome()
            self._browse_view.refresh(rebuild=True)
        self._update_sidebar_counts_only()

    def _ensure_content_visible(self) -> None:
        try:
            self._content.opacity = 1.0
            self._content.animate_opacity = None
        except Exception:
            pass

    def _update_sidebar_counts_only(self) -> None:
        """Refresh sidebar stats in place — never replace the Row child (avoids blank main pane)."""
        page_width = getattr(self._bridge.flet_page, "width", None)
        narrow = is_narrow_viewport(page_width)
        screen = self._router.active_screen()
        if narrow:
            if self._browse_view is not None and screen == "browse":
                self._browse_view.refresh_workbench_chrome(
                    in_detail=self._state.browse_detail_group_id is not None
                )
            return
        if screen == "browse" and self._browse_sidebar_shell is not None and self._sidebar_refs is not None:
            refresh_browse_workstation_sidebar(
                self._sidebar_refs, self._browse_sidebar_shell, self._state
            )
            if self._browse_view is not None:
                self._browse_view.refresh_workbench_chrome(
                    in_detail=self._state.browse_detail_group_id is not None
                )
            return
        if self._sidebar_refs is None:
            self._workstation_sidebar, self._sidebar_refs = build_progress_sidebar(
                self._t, screen, self._state, self._on_progress_jump
            )
            self.controls[0].controls[0] = self._workstation_sidebar
        else:
            refresh_progress_sidebar(
                self._sidebar_refs, self._workstation_sidebar, screen, self._state
            )

    def _repair_review_surface(self, screen: str) -> None:
        """Rebind browse content when empty; never force rebuild if groups are already on screen."""
        self._ensure_content_visible()
        if screen == "browse" and self._state.scan_results:
            page = getattr(self._bridge, "flet_page", None)
            if self._browse_view is None:
                self._skip_content_fade = True
                try:
                    self._render_active_screen()
                finally:
                    self._skip_content_fade = False
                return
            if page is not None:
                self._browse_view.attach_page(page)
            self._content.content = self._browse_view.root
            self._grid = self._browse_view.list_host
            host_controls = list(getattr(self._browse_view.list_host, "controls", None) or [])
            if not host_controls:
                self._browse_view.refresh(rebuild=True)
            self._update_sidebar_counts_only()
            return
        self._skip_content_fade = True
        try:
            self._render_active_screen()
        finally:
            self._skip_content_fade = False

    def _schedule_after_handler_frame(self, fn: Callable[[], None]) -> None:
        """Run *fn* on the Flet UI loop after the current event handler returns.

        Uses ``page.run_task`` only. ``page.run_thread`` runs on a worker thread and must
        not mutate controls (see ``BackendService._deliver_on_ui_thread``).
        """
        page = getattr(self._bridge, "flet_page", None)
        if page is not None and hasattr(page, "run_task"):

            async def _deferred() -> None:
                await asyncio.sleep(0)
                fn()

            page.run_task(_deferred)
        else:
            fn()

    def _defer_safe_update_content(self) -> None:
        """Defer parent content paint one frame — avoids blank main after heavy Browse refresh + dialog."""
        self._schedule_after_handler_frame(lambda: self._safe_update(self._content))

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

    def _apply_paths_for_group(
        self,
        group: DuplicateGroup,
        delete_paths: set[str],
        *,
        notify: bool = True,
        _recompute: bool = True,
    ) -> None:
        scoped_deletes = filter_paths_for_media_scope(
            group.files,
            delete_paths,
            enabled=self._state.selection_media_filter_enabled,
            media_type=self._state.selection_media_type,
        )
        sel = self._state.set_selections.setdefault(group.group_id, SetSelection())
        for f in group.files:
            p = str(f.path)
            if not self._state.file_in_selection_media_scope(f):
                continue
            self._state.marked_paths.discard(p)
            sel.deleted_paths.discard(p)
            sel.kept_paths.discard(p)
        for p in scoped_deletes:
            sel.deleted_paths.add(p)
            self._state.marked_paths.add(p)
        for f in group.files:
            p = str(f.path)
            if self._state.file_in_selection_media_scope(f) and p not in scoped_deletes:
                sel.kept_paths.add(p)
        if _recompute:
            self._state._recompute_cart_counters()
        if notify:
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
        delete_paths = {
            str(f.path)
            for f in group.files
            if str(f.path) != str(keep.path) and self._state.file_in_selection_media_scope(f)
        }
        self._state.push_undo_snapshot()
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
        self._state._recompute_cart_counters()
        self._render_active_screen()

    def _inspect_delete_all(self) -> None:
        group = self._state.group_by_id(self._state.inspect_set_id or -1)
        if not group:
            return
        self._state.push_undo_snapshot()
        delete_paths = {
            str(f.path) for f in group.files if self._state.file_in_selection_media_scope(f)
        }
        self._apply_paths_for_group(group, delete_paths)

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
            if not tiny_b64:
                slot.content = ft.Container(
                    width=340,
                    height=400,
                    alignment=ft.Alignment.CENTER,
                    content=build_media_placeholder(p, 72, color=self._t.colors.fg_muted),
                )
                self._safe_update(slot)
                return
            layers: list[ft.Control] = [
                ft.Image(
                    src=f"data:image/jpeg;base64,{tiny_b64}",
                    width=340,
                    height=400,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                )
            ]
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
            if not tiny_b64:
                slot.content = ft.Container(
                    width=340,
                    height=400,
                    alignment=ft.Alignment.CENTER,
                    content=build_media_placeholder(p, 72, color=self._t.colors.fg_muted),
                )
                self._safe_update(slot)
                continue
            layers: list[ft.Control] = [
                ft.Image(
                    src=f"data:image/jpeg;base64,{tiny_b64}",
                    width=340,
                    height=400,
                    fit=ft.BoxFit.CONTAIN,
                    border_radius=8,
                )
            ]
            full_b64 = cache.get_compare_preview_base64(p)
            if not full_b64:
                slot.content = ft.Stack(controls=layers, width=340, height=400)
                self._safe_update(slot)
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
        self._update_sidebar_counts_only()
        self._safe_update(self)

    def _navigate_browse_after_modal_from_overview(self) -> None:
        """Defer one frame so dialog dismiss finishes before rebuilding Browse (avoids blank main)."""
        page = self._bridge.flet_page

        def _paint_browse() -> None:
            if self._router.active_screen() == "overview":
                self._router.navigate("browse")
            elif self._router.active_screen() == "browse" and self._browse_view is not None:
                self._browse_view.refresh(rebuild=False)
            self._ensure_content_visible()
            self._safe_update(self._content)

        if hasattr(page, "run_task"):

            async def _deferred() -> None:
                await asyncio.sleep(0)
                _paint_browse()

            page.run_task(_deferred)
        else:
            _paint_browse()

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
            # Phase 3.2 — reset page on filter change
            self._state.page_index = 0
            self._close_filter_sheet()
            if self._router.active_screen() == "overview":
                self._navigate_browse_after_modal_from_overview()
                return
            if self._browse_view:
                self._browse_view.refresh()
            else:
                self._render_active_screen()

        body = ft.Container(
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
        )
        self._filter_sheet = ft.AlertDialog(
            modal=True,
            content=body,
            content_padding=0,
            bgcolor=self._t.colors.bg2,
            shape=ft.RoundedRectangleBorder(radius=16),
        )
        self._bridge.show_modal_dialog(self._filter_sheet)

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
                self._show_toast("Bulk rule marking was removed — use checkboxes on each group.")
            elif "grid" in cmd:
                self._state.view_mode = "grid"
            self._close_overlay()
            if self._browse_view:
                self._browse_view.refresh()

        dlg = ft.AlertDialog(
            title=ft.Text("Command Palette"),
            content=ft.Column([field, ft.Text("Try: invert, grid")], tight=True),
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
            export_dir_str = self._bridge.get_settings().get("general", {}).get("export_dir", "")
            export_dir = Path(export_dir_str) if export_dir_str else Path.home() / ".cerebro" / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            out = export_dir / "review_session.json"
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
        self._state._recompute_cart_counters()
        if self._browse_view:
            self._browse_view.refresh()
        self._update_sidebar_counts_only()

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
        self._state._recompute_cart_counters()
        if self._browse_view:
            self._browse_view.refresh()
        self._update_sidebar_counts_only()

    def _try_resume_session(self) -> None:
        path = Path.home() / ".cerebro" / "review_session.v1.json"
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
            # P0-4 — cap inspect_layout_by_set_id at 200 entries
            while len(self._state.inspect_layout_by_set_id) > 200:
                oldest = next(iter(self._state.inspect_layout_by_set_id))
                del self._state.inspect_layout_by_set_id[oldest]
        screen = payload.get("active_screen")
        if screen == "cart":
            screen = "browse"
        if screen in {"execute", "report"}:
            screen = "browse"
        if screen in {"overview", "browse", "inspect"}:
            self._router.reset_to_overview()
            self._router.navigate(screen)
        self._state._recompute_cart_counters()

    def _save_snapshot_async(self, path_str: str, snapshot_json: str, done_cb=None) -> None:
        """Phase 4 — Write snapshot to disk on a daemon thread (atomic via .tmp rename)."""
        import threading
        import pathlib

        def _worker() -> None:
            try:
                p = pathlib.Path(path_str)
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".tmp")
                tmp.write_text(snapshot_json, encoding="utf-8")
                tmp.replace(p)
                if done_cb:
                    done_cb(True)
            except Exception:
                _log.exception("Snapshot save failed")
                if done_cb:
                    done_cb(False)

        threading.Thread(target=_worker, daemon=True).start()

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
        path = Path.home() / ".cerebro" / "review_session.v1.json"
        self._save_snapshot_async(str(path), json.dumps(payload, indent=2))
        self._show_toast("Session saved")

    def _recent_review_lines(self) -> list[str]:
        path = Path.home() / ".cerebro" / "review_session.v1.json"
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
