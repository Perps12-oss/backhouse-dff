"""Behavior mixins for ``ReviewPage`` — keeps ``review_page.py`` under the line budget."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.components.common.chunked_view import REVIEW_GROUPS_CHUNK_CONFIG
from cerebro.v2.ui.flet_app.pages.review.filter_bar import FILTER_TABS
from cerebro.v2.ui.flet_app.components.files.group_card import build_group_card
from cerebro.v2.ui.flet_app.pages.review.compare_flags import COMPARE_SIDE_BY_SIDE_ENABLED
from cerebro.v2.ui.flet_app.pages.review.review_scope import filter_groups_by_review_scope
from cerebro.v2.ui.flet_app.pages.review.delete_flow import run_delete_with_progress, show_smart_delete_paths_dialog
from cerebro.v2.ui.flet_app.pages.review.safe_controls import safe_update
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.pages.review.smart_rules import (
    RULE_LABELS,
    apply_rule,
    apply_rule_with_pipeline,
    normalized_rule,
    paths_to_delete,
)
from cerebro.v2.ui.flet_app.services.delete_service import DeleteService
from cerebro.v2.ui.flet_app.pill_button_styles import (
    pill_filled_accent,
    pill_text_button_style,
    pill_text_button_selected,
)
from cerebro.v2.ui.flet_app.theme import EXT_ALL_KNOWN, FILTER_EXTS, fmt_size, theme_for_mode

_log = logging.getLogger(__name__)
_UI_SLOW_MS = 80.0


def _marked_bytes_total(groups: List[DuplicateGroup], marked_paths: Set[str]) -> int:
    total = 0
    for g in groups:
        for f in g.files:
            if str(f.path) in marked_paths:
                total += int(getattr(f, "size", 0) or 0)
    return total

class ReviewPageChromeMixin:
    @staticmethod
    def _hwrap_strip(strip: ft.Control) -> ft.Row:
        return ft.Row(
            [
                ft.Container(expand=True),
                strip,
                ft.Container(expand=True),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    def _sync_view_toggle_pills(self) -> None:
        t = self._t
        if self._mode == "groups":
            self._btn_view_groups.style = pill_text_button_selected(t)
            self._btn_view_tiles.style = pill_text_button_style(t, variant="muted")
        elif self._mode == "grid":
            self._btn_view_groups.style = pill_text_button_style(t, variant="muted")
            self._btn_view_tiles.style = pill_text_button_selected(t)
        else:
            self._btn_view_groups.style = pill_text_button_style(t, variant="primary")
            self._btn_view_tiles.style = pill_text_button_style(t, variant="muted")
        for b in (self._btn_view_groups, self._btn_view_tiles):
            safe_update(b)

    def _apply_pill_chrome(self) -> None:
        """Reapply nav-matched pill styles (theme/mode changes).

        Bisect / partial checkout: keep compare_view + compare_delegate + shell_attach +
        review_mixins + review_page on one ref — old mixins may reference delete_btn/keep_btn
        while newer compare chrome only exposes hero_delete_marked_btn (AttributeError).
        Same for grid_view vs mixins.
        """
        t = self._t
        self._btn_back.style = pill_text_button_style(t, variant="primary")
        self._compare_ui.btn_cmp_grid.style = pill_text_button_style(t)
        self._compare_ui.btn_cmp_prev.style = pill_text_button_style(t)
        self._compare_ui.btn_cmp_next.style = pill_text_button_style(t, variant="primary")
        self._empty_go_home_btn.style = pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700)
        hd = self._compare_ui.hero_delete_marked_btn
        hd.style = ft.ButtonStyle(
            bgcolor=t.colors.danger,
            color="#FFFFFF",
            icon_color="#FFFFFF",
            overlay_color=ft.Colors.with_opacity(0.22, t.colors.danger_hover),
            padding=ft.Padding.symmetric(horizontal=28, vertical=16),
            shape=ft.RoundedRectangleBorder(radius=12),
            text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_800),
        )
        self._sync_view_toggle_pills()
        self._grid_view.sync_zoom_pill_styles(t)
        for b in (
            self._btn_back,
            self._compare_ui.btn_cmp_grid,
            self._compare_ui.btn_cmp_prev,
            self._compare_ui.btn_cmp_next,
            self._empty_go_home_btn,
            hd,
        ):
            safe_update(b)


class ReviewPageModeMixin:
    def _sync_empty_workspace_message(self) -> None:
        """Empty-state copy: pre-scan vs scan completed with zero duplicate groups."""
        try:
            unlocked = bool(getattr(self._bridge.state, "review_unlocked", False))
        except Exception:
            unlocked = False
        title = getattr(self, "_empty_title_lbl", None)
        body = getattr(self, "_empty_body_lbl", None)
        if not isinstance(title, ft.Text) or not isinstance(body, ft.Text):
            return
        if unlocked and not self._groups:
            title.value = "No duplicate groups in this run"
            body.value = (
                "The scan finished without any duplicate sets to review. "
                "Try different folders or options on Home, then run another scan."
            )
        else:
            title.value = "Nothing to review yet"
            body.value = "Run a scan first, then come here to visually triage duplicates."
        safe_update(title)
        safe_update(body)

    _MODE_VISIBILITY: Dict[str, Dict[str, bool]] = {
        "empty": {"cmp_bar": False, "smart": False, "toggle": False, "sort": False},
        "loading": {"cmp_bar": False, "smart": False, "toggle": False, "sort": False},
        "groups": {"cmp_bar": False, "smart": True, "toggle": True, "sort": True},
        "grid": {"cmp_bar": False, "smart": True, "toggle": True, "sort": False},
        "compare": {"cmp_bar": True, "smart": False, "toggle": False, "sort": False},
        "batch": {"cmp_bar": False, "smart": False, "toggle": False, "sort": False},
    }

    @staticmethod
    def _ctrl_page_set(ctrl) -> bool:
        try:
            return ctrl.page is not None
        except RuntimeError:
            return False

    def _enter_mode(self, mode: str) -> None:
        if mode == "empty" and bool(self._groups):
            mode = "groups"
        self._mode = mode
        self._pending_deferred_render = False
        # Keep outer Column non-scrollable; inner ListView / GridView / compare body scroll.
        self.scroll = None
        if mode != "grid":
            self._grid_view.bump_thumb_generation()
        # Bind keyboard for interactive modes; clear only for empty/loading states.
        fp = getattr(self._bridge, "flet_page", None)
        if fp:
            if mode in ("empty", "loading"):
                fp.on_keyboard_event = None
            else:
                self._bind_keys()

        self._content.controls.clear()
        if mode != "grid":
            self._grid_view.set_rendering(False)

        vis = self._MODE_VISIBILITY[mode]
        self._cmp_bar.visible = vis["cmp_bar"]
        self._smart_row.visible = vis["smart"]
        self._view_toggle_row.visible = vis["toggle"]
        self._group_sort_row.visible = vis["sort"]
        self._workstation_sidebar.set_compare_mode(mode == "compare")
        # Compare owns the main workspace width. Keeping the right inspector mounted
        # leaves too little room for the A/B row on common desktop sizes, causing the
        # preview surface to overflow into the inspector and appear blank/overlapped.
        if mode == "compare":
            self._inspector_panel.visible = False
            # Collapse layout + decoration so the Row cannot paint an invisible 336px strip
            # on top of the center column on overflow (Flet desktop compositor quirk).
            self._inspector_panel.width = 0
            self._inspector_panel.expand = False
            self._inspector_panel.padding = ft.padding.all(0)
            self._inspector_panel.border = None
        else:
            self._inspector_panel.visible = True
            self._inspector_panel.width = 336
            self._inspector_panel.expand = False
            self._inspector_panel.padding = ft.padding.all(14)
            edge = ft.Colors.with_opacity(
                0.12, ft.Colors.BLACK if app_theme_is_light(self._bridge) else ft.Colors.WHITE
            )
            self._inspector_panel.border = ft.border.only(left=ft.BorderSide(1, edge))

        self._smart_host.visible = mode in ("groups", "grid")
        filter_host = getattr(self, "_filter_stack_host", None)
        if filter_host is not None:
            filter_host.visible = mode in ("groups", "grid")
        batch_btn = getattr(self, "_btn_batch_review", None)
        if batch_btn is not None:
            batch_btn.visible = mode in ("groups", "grid")

        if mode == "empty":
            self._content.controls.append(self._empty_state)
            self._sync_empty_workspace_message()
        elif mode == "loading":
            self._content.controls.append(self._loading_state)
        elif mode == "groups":
            # Append *before* filling _groups_overview: after controls.clear() the overview
            # is detached; safe_update() on it would no-op (no .page), leaving Workspace blank.
            self._refresh_filter_labels()
            self._content.controls.append(
                ft.Container(content=self._groups_overview, padding=ft.padding.all(16), expand=True)
            )
            self._refresh_groups_overview()
        elif mode == "grid":
            self._content.controls.append(self._grid_view)
            self._refresh_grid()
        elif mode == "batch":
            self._batch_index = 0
            self._batch_undo.clear()
            self._batch_review_view.visible = True
            self._content.controls.append(self._batch_review_view)
            self._refresh_batch_review()
        elif mode == "compare":
            self._compare_view.visible = True
            self._compare_ui.body.visible = True
            self._content.controls.append(self._compare_view)

        slot = getattr(self, "_workspace_slot", None)
        if slot is not None:
            self._content_frame.content = self._content
            slot.content = self._content_frame
            slot.alignment = ft.Alignment(0, 0)
            if mode != "compare":
                self._compare_view.visible = False
                self._compare_ui.body.visible = False
            if mode != "batch":
                self._batch_review_view.visible = False

        try:
            _log.debug(
                "[COMPARE_DEBUG] enter_mode mode=%s content_controls=%s compare_visible=%s "
                "compare_page=%s cmp_bar_visible=%s cmp_bar_page=%s inspector_visible=%s",
                mode,
                [type(c).__name__ for c in self._content.controls],
                getattr(self._compare_view, "visible", None),
                self._ctrl_page_set(self._compare_view),
                getattr(self._cmp_bar, "visible", None),
                self._ctrl_page_set(self._cmp_bar),
                getattr(self._inspector_panel, "visible", None),
            )
        except Exception:
            _log.debug("[COMPARE_DEBUG] enter_mode failed to collect state", exc_info=True)

        safe_update(self._content)
        safe_update(self._cmp_bar)
        safe_update(self._smart_row)
        safe_update(self._view_toggle_row)
        safe_update(self._group_sort_row)
        safe_update(self._workstation_sidebar)
        safe_update(self._inspector_panel)
        safe_update(getattr(self, "_filter_stack_host", None))
        safe_update(getattr(self, "_workspace_slot", None))
        safe_update(self._center_column)
        self._refresh_stats_header()
        self._refresh_action_bar()
        self._apply_pill_chrome()
        # Ensure the shell repaints after swapping the body subtree (Flet desktop can skip
        # partial updates when only nested controls changed).
        try:
            if self._ctrl_page_set(self):
                self.update()
        except Exception:
            pass

    async def _finish_load_to_grid_async(self) -> None:
        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_mode("grid")

    async def _finish_load_to_compare_async(self, group_id: int) -> None:
        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._enter_compare(group_id)

    def _to_grid(self, e=None) -> None:
        self._enter_mode("grid")


class ReviewPageGroupsGridMixin:
    def _build_group_card(self, g: DuplicateGroup, idx: int, total_reclaim_scan: int) -> ft.Container:
        return build_group_card(
            self._t,
            self._bridge,
            g,
            idx,
            total_reclaim_scan,
            self._reviewed_group_ids,
            smart_rule=self._smart_rule,
            on_group_click=self._on_group_card_click,
            on_inspector_select=self._on_group_inspector_select,
            on_file_click=self._on_file_inspector_click,
        )

    def _on_group_card_click(self, g: DuplicateGroup) -> None:
        self._enter_compare(g.group_id)

    def _on_group_inspector_select(self, g: DuplicateGroup) -> None:
        self._selected_group_id = g.group_id
        self._selected_file = None
        self._inspector_panel.show_group(g, self._smart_rule, self._marked_paths)

    def _on_file_inspector_click(self, f: DuplicateFile) -> None:
        self._selected_file = f
        group = next((g for g in self._groups if any(str(fi.path) == str(f.path) for fi in g.files)), None)
        if group:
            self._selected_group_id = group.group_id
            self._inspector_panel.show_file(f, self._smart_rule, group, self._marked_paths)
            self._enter_compare(group.group_id, preferred_a=f)

    def _on_inspector_compare_file(self, f: DuplicateFile) -> None:
        """Called from the inspector 'Compare in context →' button."""
        self._selected_file = f
        group = next((g for g in self._groups if any(str(fi.path) == str(f.path) for fi in g.files)), None)
        if group:
            self._selected_group_id = group.group_id
            self._enter_compare(group.group_id, preferred_a=f)

    def _keep_paths_for_current_filter(self) -> Set[str]:
        """Paths the active smart rule would keep (one per multi-file group in filter)."""
        rule = normalized_rule(self._smart_rule or "keep_largest")
        kp: Set[str] = set()
        for g in self._groups:
            files = [f for f in g.files if self._passes_filter(f)]
            if len(files) < 2:
                continue
            try:
                keeper = apply_rule_with_pipeline(
                    rule,
                    files,
                    filename_regex=getattr(self, "_advanced_filename_keep_regex", ""),
                )
                kp.add(str(keeper.path))
            except Exception:
                continue
        return kp

    def _sorted_groups_for_current_filter(self) -> List[DuplicateGroup]:
        q = (getattr(self, "_search_query", "") or "").strip().lower()
        filtered = [
            g for g in self._groups
            if (self._filter_key == "all" or any(self._passes_filter(f) for f in g.files))
            and (not q or any(q in str(f.path).lower() for f in g.files))
        ]
        if getattr(self, "_cross_folder_only", False):
            filtered = [
                g
                for g in filtered
                if len({Path(str(f.path)).parent for f in g.files}) > 1
            ]
        keep_paths = self._keep_paths_for_current_filter()
        filtered = filter_groups_by_review_scope(
            filtered,
            str(getattr(self, "_review_scope", "all")),
            reviewed_ids=self._reviewed_group_ids,
            ignored_ids=getattr(self, "_ignored_group_ids", set()),
            marked_paths=self._marked_paths,
            smart_rule=self._smart_rule,
            keep_paths=keep_paths,
        )
        key = str(self._group_sort_key or "files_desc")
        if key == "files_desc":
            return sorted(filtered, key=lambda g: len(g.files), reverse=True)
        if key == "path_asc":
            return sorted(
                filtered,
                key=lambda g: str(Path(str(g.files[0].path)).parent).lower() if g.files else "",
            )
        return sorted(filtered, key=lambda g: int(getattr(g, "reclaimable", 0) or 0), reverse=True)

    def _on_search_changed(self, e: ft.ControlEvent) -> None:
        self._search_query = str(e.control.value or "").strip()
        if self._mode in ("groups", "grid"):
            self._refresh_groups_overview() if self._mode == "groups" else self._refresh_grid()
            self._refresh_stats_header()

    def _refresh_groups_overview(self) -> None:
        filtered_groups = self._sorted_groups_for_current_filter()
        if getattr(self, "_workspace_view_mode", "triage") == "dashboard":
            filtered_groups = filtered_groups[:12]
        _log.debug(
            "_refresh_groups_overview: total=%d filtered=%d filter_key=%r",
            len(self._groups),
            len(filtered_groups),
            self._filter_key,
        )
        total_r = sum(int(getattr(x, "reclaimable", 0) or 0) for x in self._groups) or 1

        def after_chunk() -> None:
            safe_update(self._groups_overview)

        self._groups_chunked.render(
            self._groups_overview,
            filtered_groups,
            config=REVIEW_GROUPS_CHUNK_CONFIG,
            card_builder=lambda g, i: self._build_group_card(g, i, total_r),
            after_chunk=after_chunk,
            on_complete=after_chunk,
        )
        safe_update(self._content)

    def _on_group_sort_changed(self, e: ft.ControlEvent) -> None:
        self._group_sort_key = str(e.control.value or "files_desc")
        if self._mode == "groups":
            self._refresh_groups_overview()
            self._refresh_stats_header()

    def _refresh_grid(self) -> None:
        files = self._files_by_filter.get(self._filter_key, [])
        self._refresh_filter_labels()
        self._grid_view.set_reduce_motion(self._reduce_motion)
        self._grid_view.refresh(files, self._marked_paths, self._keep_paths_for_current_filter())

    def _passes_filter(self, f: DuplicateFile) -> bool:
        path_text = str(f.path)
        regex = str(getattr(self, "_advanced_path_regex", "") or "").strip()
        if regex:
            try:
                if not re.search(regex, path_text, re.IGNORECASE):
                    return False
            except re.error:
                pass
        if self._filter_key == "all":
            return True
        ext = getattr(f, "extension", Path(str(f.path)).suffix.lower())
        if self._filter_key == "other":
            return ext.lower() not in EXT_ALL_KNOWN
        exts = FILTER_EXTS.get(self._filter_key)
        return ext.lower() in exts if exts else True

    def _on_tile_clicked(self, f: DuplicateFile) -> None:
        self._selected_file = f
        group = next((g for g in self._groups if f in g.files), None)
        if group:
            self._selected_group_id = group.group_id
            self._inspector_panel.show_file(f, self._smart_rule, group, self._marked_paths)
            self._enter_compare(group.group_id)


class ReviewPageSmartMixin:
    def _on_smart_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"keep_largest"}
        self._smart_rule = next(iter(sel), "keep_largest")
        self._cmp_smart_rule = self._smart_rule
        if self._mode == "compare" and self._compare_gid is not None:
            self._sync_compare_group_marks_to_rule(self._compare_gid)
            self._update_compare_panels()
            self._refresh_grid()
            self._update_progress_and_marked_bar()
        elif self._mode == "grid":
            self._refresh_grid()
        elif self._mode == "groups":
            self._refresh_groups_overview()
        self._refresh_stats_header()
        self._refresh_action_bar()

    def _sync_compare_group_marks_to_rule(self, gid: Optional[int] = None) -> None:
        """Reset marks for files in this group to match the grid smart rule (per-group)."""
        gid = gid if gid is not None else self._compare_gid
        if gid is None:
            return
        files = [f for f in self._group_files.get(gid, []) if self._passes_filter(f)]
        group_paths = {str(f.path) for f in files}
        for p in list(self._marked_paths):
            if p in group_paths:
                self._marked_paths.discard(p)
        rule = normalized_rule(self._smart_rule or "keep_largest")
        for p in paths_to_delete(rule, files):
            self._marked_paths.add(str(p))
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()

    def _apply_smart_select_review(self, e=None):
        rule = self._smart_rule or "keep_largest"
        rule_lbl = dict(RULE_LABELS).get(rule, "Keep Largest")

        def _apply_all(_e):
            self._bridge.dismiss_top_dialog()
            self._apply_rule_to_all_groups()

        def _suggest_only(_e):
            self._bridge.dismiss_top_dialog()
            self._bridge.show_snackbar(f"Suggestion mode enabled: {rule_lbl}.", info=True)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Apply rule"),
            content=ft.Text(f'Use "{rule_lbl}" for all groups, or only as a suggestion while reviewing?'),
            actions=[
                ft.TextButton("Cancel", on_click=lambda _e: self._bridge.dismiss_top_dialog()),
                ft.OutlinedButton("Suggest per-group", on_click=_suggest_only),
                ft.ElevatedButton("Apply to all groups", on_click=_apply_all),
            ],
        )
        self._bridge.show_modal_dialog(dlg)

    def _deselect_all(self, e=None) -> None:
        self._marked_paths.clear()
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        if self._mode == "grid":
            self._grid_view.refresh_marks(self._marked_paths, self._keep_paths_for_current_filter())
        elif self._mode == "compare":
            self._update_compare_panels()
        elif self._mode == "groups":
            self._refresh_groups_overview()

    def _apply_rule_to_all_groups(self) -> None:
        page = self._bridge.flet_page
        if hasattr(page, "run_task"):
            page.run_task(self._apply_rule_to_all_groups_async)
        else:
            self._apply_rule_to_all_groups_sync()

    async def _apply_rule_to_all_groups_async(self) -> None:
        rule = normalized_rule(self._smart_rule or "keep_largest")
        to_delete: List[str] = []
        for i, g in enumerate(self._groups):
            files = [f for f in g.files if self._passes_filter(f)]
            to_delete.extend(paths_to_delete(rule, files))
            if i % 50 == 0:
                await asyncio.sleep(0)
        if not to_delete:
            return
        self._marked_paths = set(to_delete)
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        if self._mode == "grid":
            self._refresh_grid()
        else:
            self._update_compare_panels()
        self._update_progress_and_marked_bar()

    def _apply_rule_to_all_groups_sync(self) -> None:
        rule = normalized_rule(self._smart_rule or "keep_largest")
        to_delete: List[str] = []
        for g in self._groups:
            files = [f for f in g.files if self._passes_filter(f)]
            to_delete.extend(paths_to_delete(rule, files))
        if not to_delete:
            return
        self._marked_paths = set(to_delete)
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        if self._mode == "grid":
            self._refresh_grid()
        else:
            self._update_compare_panels()
        self._update_progress_and_marked_bar()

    def _apply_smart_select_compare_current(self, e=None) -> None:
        """Re-apply the grid smart rule to marks for the current compare group."""
        if self._compare_gid is None:
            return
        self._sync_compare_group_marks_to_rule(self._compare_gid)
        self._update_compare_panels()
        self._refresh_grid()
        self._update_progress_and_marked_bar()

    def _show_smart_delete_dialog(self, paths: List[str]) -> None:
        show_smart_delete_paths_dialog(
            self._bridge,
            self._t,
            paths,
            lambda policy: self._execute_smart_delete(paths, policy),
        )

    def _on_smart_delete_complete(
        self,
        paths: List[str],
        policy: DeletionPolicy,
        new_groups: List[DuplicateGroup],
        deleted: int,
        failed: int,
        bytes_reclaimed: int,
        err: Exception | None,
    ) -> None:
        if err is not None:
            self._bridge.show_snackbar(f"Deletion failed: {err}", error=True)
            return
        self._groups = list(new_groups)
        self._group_files = {g.group_id: list(g.files) for g in self._groups}
        self._rebuild_group_index()
        self._rebuild_filter_index()
        self._sync_total_reclaimable_cache()
        for p in paths:
            self._marked_paths.discard(str(p))
        self._recompute_marked_bytes()
        self._bridge.coordinator.results_groups_pruned(self._groups)
        self._push_marked_paths_to_store()
        if deleted > 0:
            if policy == DeletionPolicy.TRASH:
                self._bridge.show_snackbar(
                    f"Moved {deleted:,} files to Trash ({fmt_size(bytes_reclaimed)} reclaimed).",
                    success=True,
                    action_label="Undo",
                    on_action=lambda _e: self._undo_last_trash_delete(),
                )
            else:
                self._bridge.show_snackbar(
                    f"Permanently deleted {deleted:,} files ({fmt_size(bytes_reclaimed)} reclaimed).",
                    success=True,
                )
        if failed > 0:
            self._bridge.show_snackbar(
                f"{failed:,} file(s) were unavailable (for example disconnected drive) and were skipped.",
                error=True,
            )
        if not self._groups:
            self._enter_mode("empty")
        else:
            if self._mode == "compare":
                gid = self._compare_gid
                if gid is None or gid not in self._group_files:
                    gid = self._groups[0].group_id
                self._enter_compare(gid)
            else:
                self._refresh_grid()

    def _execute_smart_delete(self, paths: List[str], policy: DeletionPolicy) -> None:
        if not paths:
            return
        paths_copy = list(paths)

        def _on_complete(
            new_groups: List[DuplicateGroup],
            deleted: int,
            failed: int,
            bytes_reclaimed: int,
            err: Exception | None,
        ) -> None:
            self._on_smart_delete_complete(paths_copy, policy, new_groups, deleted, failed, bytes_reclaimed, err)

        # safe_update: module function (not ReviewPage._safe_update) — see safe_controls docstring.
        run_delete_with_progress(
            service=self._delete_service,
            bridge=self._bridge,
            t=self._t,
            paths=paths,
            policy=policy,
            groups=self._groups,
            safe_update=safe_update,
            on_complete=_on_complete,
        )


class ReviewPageCompareNavMixin:
    """Compare navigation; slow-path logging uses ``ReviewPage._log_if_slow`` on the concrete class."""

    def _open_group_in_grid_workspace(
        self,
        gid: int,
        *,
        preferred_a: Optional[DuplicateFile] = None,
    ) -> None:
        files = self._group_files.get(gid) or []
        self._compare_gid = gid
        self._selected_group_id = gid
        if preferred_a is not None and any(
            f is preferred_a or str(f.path) == str(preferred_a.path) for f in files
        ):
            pick = next(f for f in files if f is preferred_a or str(f.path) == str(preferred_a.path))
            others = [f for f in files if f is not pick]
            self._compare_a = pick
            self._compare_b = others[0] if others else None
            self._selected_file = pick
        else:
            self._compare_a = files[0] if files else None
            self._compare_b = files[1] if len(files) > 1 else None
            self._selected_file = None
        group = next((g for g in self._groups if g.group_id == gid), None)
        if group is not None:
            if self._selected_file is not None:
                self._inspector_panel.show_file(
                    self._selected_file,
                    self._smart_rule,
                    group,
                    self._marked_paths,
                )
            else:
                self._inspector_panel.show_group(group, self._smart_rule, self._marked_paths)
        if self._mode != "grid":
            self._enter_mode("grid")
        else:
            self._refresh_grid()
            self._refresh_stats_header()
            self._refresh_action_bar()

    def _enter_compare(self, gid: int, *, preferred_a: Optional[DuplicateFile] = None) -> None:
        _t0 = time.perf_counter()
        if self._compare_nav_in_flight:
            return
        self._compare_nav_in_flight = True
        files = self._group_files.get(gid) or []
        try:
            if not files:
                self._to_grid()
                self._log_if_slow("review:on_click_group_nav", _t0)
                return
            if not COMPARE_SIDE_BY_SIDE_ENABLED:
                self._open_group_in_grid_workspace(gid, preferred_a=preferred_a)
                self._log_if_slow("review:on_click_group_nav", _t0)
                return
            if self._compare_gid is not None:
                self._reviewed_group_ids.add(self._compare_gid)
            self._compare_gid = gid
            if preferred_a is not None and any(f is preferred_a or str(f.path) == str(preferred_a.path) for f in files):
                a = next(f for f in files if f is preferred_a or str(f.path) == str(preferred_a.path))
                others = [f for f in files if f is not a]
                self._compare_a = a
                self._compare_b = others[0] if others else None
            else:
                self._compare_a = files[0]
                self._compare_b = files[1] if len(files) > 1 else None
            self._enter_mode("compare")
            self._cmp_smart_rule = self._smart_rule
            self._sync_compare_group_marks_to_rule(gid)
            self._update_compare_panels()
            self._refresh_group_list_panel()
            self._update_compare_chrome()
            group = next((g for g in self._groups if g.group_id == gid), None)
            if group and not self._selected_file:
                self._inspector_panel.show_group(group, self._smart_rule, self._marked_paths)
            # _enter_mode already updated once; compare panels mount after that — force a
            # full relayout so bounded flex + thumbnails paint on first open (Flet desktop).
            try:
                if self._ctrl_page_set(self):
                    self.update()
            except Exception:
                pass
            self._log_if_slow("review:on_click_group_nav", _t0)
        finally:
            self._compare_nav_in_flight = False

    def _update_compare_panels(self) -> None:
        self._compare_ui.update_compare_panels()

    def _apply_compare_panel_tints(self) -> None:
        self._compare_ui.apply_compare_panel_tints()

    def _reset_compare_panels_idle_chrome(self) -> None:
        self._compare_ui.reset_compare_panels_idle_chrome()

    def _keep_only_file(self, keep_file: DuplicateFile) -> None:
        gid = self._compare_gid
        if gid is None:
            return
        files = self._group_files.get(gid, [])
        for f in files:
            fp = str(f.path)
            if f is keep_file:
                self._marked_paths.discard(fp)
            else:
                self._marked_paths.add(fp)
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        self._update_compare_panels()

    def _toggle_mark_file(self, file: DuplicateFile) -> None:
        # Single-path toggle: O(1) bytes delta. Engine output treats each path as belonging to at most one group.
        fp = str(file.path)
        sz = int(getattr(file, "size", 0) or 0)
        if fp in self._marked_paths:
            self._marked_paths.discard(fp)
            self._marked_bytes -= sz
        else:
            self._marked_paths.add(fp)
            self._marked_bytes += sz
        if self._marked_bytes < 0:
            self._marked_bytes = 0
        self._push_marked_paths_to_store()
        if self._mode == "grid":
            self._grid_view.refresh_marks(self._marked_paths, self._keep_paths_for_current_filter())
        elif self._mode == "compare":
            self._compare_ui.refresh_compare_marks()
        self._refresh_action_bar()
        self._stats_header.update_marked_metrics(len(self._marked_paths), self._marked_bytes)

    def _refresh_group_list_panel(self) -> None:
        self._compare_ui.refresh_group_list_panel()

    def _recompute_marked_bytes(self) -> None:
        self._marked_bytes = _marked_bytes_total(self._groups, self._marked_paths)
        self._refresh_action_bar()
        self._refresh_stats_header()

    def _update_progress_and_marked_bar(self) -> None:
        self._compare_ui.update_progress_and_marked_bar()

    def _delete_marked_files(self, e=None) -> None:
        if not self._marked_paths:
            return
        self._show_smart_delete_dialog(sorted(self._marked_paths))

    def _update_compare_chrome(self) -> None:
        self._compare_ui.update_compare_chrome()

    def _prev_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = self._group_index.get(self._compare_gid, 0)
        if idx > 0:
            self._enter_compare(self._groups[idx - 1].group_id)

    def _next_group(self, e=None) -> None:
        if self._compare_gid is None:
            return
        idx = self._group_index.get(self._compare_gid, 0)
        if idx < len(self._groups) - 1:
            self._enter_compare(self._groups[idx + 1].group_id)

class ReviewPageFilterMixin:
    def _sync_workspace_preferences_from_state(self) -> None:
        state = self._bridge.state
        self._filter_key = str(state.review_file_filter or "all")
        self._search_query = str(state.results_text_filter or "").strip()
        ui = state.ui or {}
        self._cross_folder_only = bool(ui.get("workspace_cross_folder_only", False))
        self._workspace_view_mode = str(ui.get("workspace_view_mode", "triage"))
        self._review_scope = str(ui.get("workspace_review_scope", "all"))
        self._reviewed_group_ids = {int(x) for x in ui.get("workspace_reviewed_group_ids", [])}
        self._ignored_group_ids = {int(x) for x in ui.get("workspace_ignored_group_ids", [])}
        self._override_paths = {str(x) for x in ui.get("workspace_override_paths", [])}
        self._advanced_path_regex = str(ui.get("workspace_advanced_path_regex", "") or "")
        rules = ui.get("advanced_rules") or {}
        if isinstance(rules, dict):
            self._advanced_filename_keep_regex = str(rules.get("filename_keep_regex", "") or "")
        else:
            self._advanced_filename_keep_regex = ""
        self._workstation_sidebar.set_review_scope(self._review_scope)
        drawer = getattr(self, "_advanced_drawer", None)
        if drawer is not None:
            drawer.sync_from_state(
                regex=self._advanced_path_regex,
                pipeline=self._advanced_filename_keep_regex,
                advanced_mode=bool(getattr(state, "advanced_mode", False)),
            )
        stack = getattr(self, "_workspace_filter_stack", None)
        if stack is not None:
            stack.sync_from_state(
                filter_key=self._filter_key,
                text_filter=self._search_query,
                cross_folder_only=self._cross_folder_only,
                view_mode=self._workspace_view_mode,
            )
            stack.filter_bar.update_counts(
                self._filter_counts,
                self._filter_sizes,
                self._filter_key,
            )

    def _push_workspace_review_state(self) -> None:
        try:
            self._bridge.coordinator.workspace_set_ui_preferences(
                {
                    "workspace_review_scope": self._review_scope,
                    "workspace_reviewed_group_ids": sorted(self._reviewed_group_ids),
                    "workspace_ignored_group_ids": sorted(self._ignored_group_ids),
                    "workspace_override_paths": sorted(self._override_paths),
                    "workspace_advanced_path_regex": self._advanced_path_regex,
                    "advanced_rules": {"filename_keep_regex": self._advanced_filename_keep_regex},
                }
            )
        except Exception:
            pass

    def _on_review_scope_changed(self, scope: str) -> None:
        self._review_scope = scope
        self._push_workspace_review_state()
        if self._mode == "groups":
            self._refresh_groups_overview()
        elif self._mode == "grid":
            self._refresh_grid()
        self._refresh_filter_labels()

    def _on_advanced_regex_changed(self, regex: str) -> None:
        self._advanced_path_regex = str(regex or "")
        self._push_workspace_review_state()
        if self._mode in ("groups", "grid"):
            if self._mode == "groups":
                self._refresh_groups_overview()
            else:
                self._refresh_grid()

    def _on_advanced_rule_pipeline_changed(self, regex: str) -> None:
        self._advanced_filename_keep_regex = str(regex or "")
        self._push_workspace_review_state()
        if self._mode in ("groups", "grid", "batch"):
            if self._mode == "groups":
                self._refresh_groups_overview()
            elif self._mode == "grid":
                self._refresh_grid()
            else:
                self._refresh_batch_review()

    def _on_export_marked_paths(self) -> None:
        from cerebro.v2.ui.flet_app.components.workspace.advanced_drawer import AdvancedWorkspaceDrawer

        payload = AdvancedWorkspaceDrawer.export_marked_json(self._marked_paths)
        try:
            self._bridge.flet_page.set_clipboard(payload)
            self._bridge.show_snackbar("Marked paths copied as JSON.", success=True)
        except Exception:
            self._bridge.show_snackbar("Could not export marked paths.", info=True)

    def _on_filter_changed(self, key: str) -> None:
        self._filter_key = key
        try:
            self._bridge.coordinator.review_set_filter(key)
        except Exception:
            pass
        if self._mode == "grid":
            self._refresh_grid()
        elif self._mode == "groups":
            self._refresh_filter_labels()
            self._refresh_groups_overview()
        elif self._mode == "compare":
            self._refresh_filter_labels()
            self._update_compare_panels()

    def _rebuild_group_index(self) -> None:
        self._group_index = {g.group_id: i for i, g in enumerate(self._groups)}

    def _rebuild_filter_index(self) -> None:
        self._grid_view.clear_tile_caches()
        by_filter: Dict[str, List[DuplicateFile]] = {k: [] for k, _ in FILTER_TABS}
        group_counts: Dict[str, int] = {k: 0 for k, _ in FILTER_TABS}
        file_sizes: Dict[str, int] = {k: 0 for k, _ in FILTER_TABS}
        for g in self._groups:
            group_counts["all"] += 1
            seen_group_kinds: set[str] = set()
            for f in g.files:
                ext = getattr(f, "extension", Path(str(f.path)).suffix.lower())
                if ext.lower() in EXT_ALL_KNOWN:
                    kind = next((k for k, exts in FILTER_EXTS.items() if exts and ext.lower() in exts), "other")
                else:
                    kind = "other"
                bucket = kind if kind in by_filter else "other"
                by_filter["all"].append(f)
                by_filter[bucket].append(f)
                file_sizes["all"] += f.size
                file_sizes[bucket] += f.size
                seen_group_kinds.add(kind if kind in group_counts else "other")
            for kind in seen_group_kinds:
                group_counts[kind] += 1
        self._files_by_filter = by_filter
        self._filter_counts = {k: len(v) for k, v in by_filter.items()}
        self._filter_sizes = file_sizes
        self._filter_group_counts = group_counts
        self._refresh_filter_labels()

    def _refresh_filter_labels(self) -> None:
        self._workstation_sidebar.update_counts(self._filter_counts, self._filter_sizes, self._filter_key)
        stack = getattr(self, "_workspace_filter_stack", None)
        if stack is not None:
            stack.filter_bar.update_counts(self._filter_counts, self._filter_sizes, self._filter_key)
        self._workstation_sidebar.refresh_group_rail(
            self._sorted_groups_for_current_filter(),
            active_group_id=self._compare_gid,
        )
        self._refresh_stats_header()

    def _on_workspace_text_filter(self, text: str) -> None:
        self._search_query = str(text or "").strip()
        try:
            self._bridge.coordinator.results_set_text_filter(self._search_query)
        except Exception:
            pass
        if self._mode in ("groups", "grid"):
            if self._mode == "groups":
                self._refresh_groups_overview()
            else:
                self._refresh_grid()
            self._refresh_stats_header()

    def _on_cross_folder_only_changed(self, enabled: bool) -> None:
        self._cross_folder_only = bool(enabled)
        try:
            self._bridge.coordinator.workspace_set_ui_preferences(
                {"workspace_cross_folder_only": self._cross_folder_only}
            )
        except Exception:
            pass
        if self._mode == "groups":
            self._refresh_groups_overview()

    def _on_rail_group_selected(self, group_id: int) -> None:
        self._enter_compare(int(group_id))
        self._refresh_filter_labels()

    def _on_rail_group_search(self) -> None:
        self._search_field.visible = True
        try:
            self._search_field.focus()
        except Exception:
            pass
        safe_update(self._search_field)

    def _on_rail_show_all_groups(self) -> None:
        self._enter_mode("groups")
        self._workspace_view_mode = "triage"
        self._refresh_groups_overview()

    def _on_workspace_view_mode_changed(self, mode: str) -> None:
        self._workspace_view_mode = mode if mode in ("triage", "dashboard") else "triage"
        try:
            self._bridge.coordinator.workspace_set_ui_preferences(
                {"workspace_view_mode": self._workspace_view_mode}
            )
        except Exception:
            pass
        if self._mode == "groups":
            self._refresh_groups_overview()
            self._refresh_stats_header()

    def _refresh_stats_header(self) -> None:
        fl = next((lab for k, lab in FILTER_TABS if k == self._filter_key), self._filter_key.title())
        self._stats_header.refresh(
            self._mode,
            fl,
            self._filter_key,
            self._filter_counts,
            self._filter_sizes,
            self._filter_group_counts,
            self._reviewed_group_ids,
            self._sorted_groups_for_current_filter(),
            self._t,
            marked_count=len(self._marked_paths),
            marked_bytes=self._marked_bytes,
        )

    def _refresh_action_bar(self) -> None:
        rule = normalized_rule(getattr(self, "_smart_rule", "keep_largest"))
        rule_lbl = next((lbl for k, lbl in RULE_LABELS if k == rule), rule)
        self._review_action_bar.refresh(
            self._mode,
            len(self._marked_paths),
            self._marked_bytes,
            f"Keeping per rule: {rule_lbl}",
        )


class ReviewPageBatchMixin:
    def _batch_groups(self) -> List[DuplicateGroup]:
        return self._sorted_groups_for_current_filter()

    def _current_batch_group(self) -> Optional[DuplicateGroup]:
        groups = self._batch_groups()
        idx = int(getattr(self, "_batch_index", 0))
        if 0 <= idx < len(groups):
            return groups[idx]
        return None

    def _record_batch_undo(self) -> None:
        self._batch_undo.record(
            marked_paths=self._marked_paths,
            reviewed_group_ids=self._reviewed_group_ids,
            ignored_group_ids=self._ignored_group_ids,
            override_paths=self._override_paths,
        )

    def _refresh_batch_review(self) -> None:
        groups = self._batch_groups()
        idx = min(int(getattr(self, "_batch_index", 0)), max(0, len(groups) - 1))
        self._batch_index = idx
        group = self._current_batch_group()
        self._batch_review_view.refresh(group=group, index=idx, total=max(1, len(groups)))
        safe_update(self._batch_review_view)
        self._refresh_stats_header()

    def _enter_batch_review(self, e=None) -> None:
        if not self._groups:
            self._bridge.show_snackbar("Nothing to review in this scope.", info=True)
            return
        self._enter_mode("batch")

    def _exit_batch_review(self) -> None:
        self._batch_undo.clear()
        self._push_workspace_review_state()
        self._enter_mode("groups")

    def _batch_apply_keep_rule(self) -> None:
        group = self._current_batch_group()
        if group is None:
            return
        self._record_batch_undo()
        files = list(group.files)
        try:
            keeper = apply_rule_with_pipeline(
                normalized_rule(self._smart_rule),
                files,
                filename_regex=self._advanced_filename_keep_regex,
            )
        except Exception:
            return
        for f in files:
            fp = str(f.path)
            if f is keeper:
                self._marked_paths.discard(fp)
            else:
                self._marked_paths.add(fp)
        self._reviewed_group_ids.add(int(group.group_id))
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        self._push_workspace_review_state()
        self._refresh_batch_review()

    def _batch_mark_extras(self) -> None:
        group = self._current_batch_group()
        if group is None:
            return
        self._record_batch_undo()
        for fp in paths_to_delete(self._smart_rule, list(group.files)):
            self._marked_paths.add(fp)
            self._override_paths.add(fp)
        self._reviewed_group_ids.add(int(group.group_id))
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        self._push_workspace_review_state()
        self._refresh_batch_review()

    def _batch_skip_group(self) -> None:
        group = self._current_batch_group()
        if group is None:
            return
        self._record_batch_undo()
        self._ignored_group_ids.add(int(group.group_id))
        self._push_workspace_review_state()
        self._batch_advance()

    def _batch_advance(self) -> None:
        self._batch_index = int(getattr(self, "_batch_index", 0)) + 1
        if self._batch_index >= len(self._batch_groups()):
            self._bridge.show_snackbar("Batch review finished for this scope.", success=True)
            self._exit_batch_review()
            return
        self._refresh_batch_review()

    def _batch_undo_last(self) -> None:
        frame = self._batch_undo.pop()
        if frame is None:
            self._bridge.show_snackbar("Nothing to undo in this batch session.", info=True)
            return
        self._marked_paths = set(frame.marked_paths)
        self._reviewed_group_ids = set(frame.reviewed_group_ids)
        self._ignored_group_ids = set(frame.ignored_group_ids)
        self._override_paths = set(frame.override_paths)
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        self._push_workspace_review_state()
        self._refresh_batch_review()
        self._bridge.show_snackbar("Undid the last batch action.", success=True)


class ReviewPageKeyboardMixin:
    def _bind_keys(self) -> None:
        self._bridge.flet_page.on_keyboard_event = self._on_key

    def _on_key(self, e: ft.KeyboardEvent) -> None:
        k = e.key.lower().replace(" ", "")
        # Escape works in all interactive modes.
        if k == "escape":
            self._go_back()
            return
        if self._mode == "compare":
            if k in ("arrowleft", "left", "arrowup", "up"):
                self._prev_group()
            elif k in ("arrowright", "right", "arrowdown", "down"):
                self._next_group()
            elif k in ("delete", "backspace"):
                if self._marked_paths:
                    self._delete_marked_files()
            elif k == "enter":
                self._next_group()
            elif k == "space":
                self._apply_smart_select_compare_current()
        elif self._mode == "groups":
            if k == "g":
                self._enter_mode("grid")
        elif self._mode == "grid":
            if k == "g":
                self._enter_mode("groups")
        elif self._mode == "batch":
            ctrl = bool(getattr(e, "ctrl", False))
            if ctrl and k == "z":
                self._batch_undo_last()
            elif k in ("k",):
                self._batch_apply_keep_rule()
            elif k in ("d",):
                self._batch_mark_extras()
            elif k in ("s",):
                self._batch_skip_group()
            elif k == "enter":
                self._batch_advance()


class ReviewPageNavThemeMixin:
    def _go_back(self, e=None) -> None:
        if self._mode == "batch":
            self._exit_batch_review()
            return
        if self._mode in ("compare", "grid"):
            self._enter_mode("groups")
        else:
            self._bridge.navigate("dashboard")

    def _undo_last_trash_delete(self) -> None:
        ok, restored = DeleteService.undo_last_trash_delete()
        if ok and restored > 0:
            self._bridge.show_snackbar(f"Restored {restored:,} file(s) from Trash.", success=True)
        elif restored > 0:
            self._bridge.show_snackbar(
                f"Partially restored {restored:,} file(s). Check missing paths.",
                info=True,
            )
        else:
            self._bridge.show_snackbar("Nothing to undo.", info=True)

    def apply_theme(self, mode: str) -> None:
        self._t = theme_for_mode(mode)
        self._compare_ui.sync_theme(self._t)
        self._grid_view.sync_theme(self._t)

        self._stats_header.bgcolor = self._t.colors.glass_bg
        edge_h = ft.Colors.with_opacity(0.1, ft.Colors.BLACK if app_theme_is_light(self._bridge) else ft.Colors.WHITE)
        self._stats_header.border = ft.border.only(bottom=ft.BorderSide(1, edge_h))
        self._workstation_sidebar.sync_theme(self._t)
        self._inspector_panel.sync_theme(self._t)
        self._review_action_bar.sync_theme(self._t)
        self._refresh_filter_labels()

        self._compare_ui.apply_cmp_bar_glass()

        self._empty_state.bgcolor = self._t.colors.glass_bg
        self._empty_state.border = ft.border.all(1, self._t.colors.glass_border)
        self._empty_title_lbl.color = self._t.colors.fg
        self._empty_body_lbl.color = self._t.colors.fg_muted
        self._empty_title_lbl.size = self._t.typography.size_lg
        self._empty_body_lbl.size = self._t.typography.size_base
        if self._mode == "empty":
            self._sync_empty_workspace_message()

        if self._mode == "compare":
            self._apply_compare_panel_tints()
        else:
            self._reset_compare_panels_idle_chrome()

        self._apply_pill_chrome()

        if self._is_mounted():
            self.update()
