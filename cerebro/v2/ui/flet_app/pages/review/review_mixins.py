"""Behavior mixins for ``ReviewPage`` — keeps ``review_page.py`` under the line budget."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import flet as ft

from cerebro.core.deletion import DeletionPolicy
from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.components.common.chunked_view import REVIEW_GROUPS_CHUNK_CONFIG
from cerebro.v2.ui.flet_app.components.common.safe_controls import safe_update
from cerebro.v2.ui.flet_app.components.files.group_card import build_group_card
from cerebro.v2.ui.flet_app.components.filters.filter_bar import FILTER_TABS
from cerebro.v2.ui.flet_app.pages.review.delete_flow import run_delete_with_progress, show_smart_delete_paths_dialog
from cerebro.v2.ui.flet_app.pages.review.review_scope import filter_groups_by_review_scope
from cerebro.v2.ui.flet_app.pages.review.theme_detect import app_theme_is_light
from cerebro.v2.ui.flet_app.pages.review.smart_rules import (
    RULE_LABELS,
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
        t = self._t
        self._btn_back.style = pill_text_button_style(t, variant="primary")
        self._empty_go_home_btn.style = pill_filled_accent(t, text_size=12, weight=ft.FontWeight.W_700)
        self._sync_view_toggle_pills()
        self._grid_view.sync_zoom_pill_styles(t)
        for b in (self._btn_back, self._empty_go_home_btn):
            safe_update(b)


class ReviewPageModeMixin:
    def _sync_empty_workspace_message(self) -> None:
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
        "empty": {"smart": False, "toggle": False, "sort": False},
        "loading": {"smart": False, "toggle": False, "sort": False},
        "groups": {"smart": True, "toggle": True, "sort": True},
        "grid": {"smart": True, "toggle": True, "sort": False},
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
        self.scroll = None
        if mode != "grid":
            self._grid_view.bump_thumb_generation()
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
        self._smart_row.visible = vis["smart"]
        self._view_toggle_row.visible = vis["toggle"]
        self._group_sort_row.visible = vis["sort"]
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

        if mode == "empty":
            self._content.controls.append(self._empty_state)
            self._sync_empty_workspace_message()
        elif mode == "loading":
            self._content.controls.append(self._loading_state)
        elif mode == "groups":
            self._refresh_filter_labels()
            self._content.controls.append(
                ft.Container(content=self._groups_overview, padding=ft.padding.all(16), expand=True)
            )
            self._refresh_groups_overview()
        elif mode == "grid":
            self._content.controls.append(self._grid_view)
            self._refresh_grid()

        slot = getattr(self, "_workspace_slot", None)
        if slot is not None:
            self._content_frame.content = self._content
            slot.content = self._content_frame
            slot.alignment = ft.Alignment(0, 0)

        safe_update(self._content)
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
        try:
            if self._ctrl_page_set(self):
                self.update()
        except Exception:
            pass

    async def _finish_load_to_grid_async(self, group_id: int) -> None:
        await asyncio.sleep(0)
        self._loading = False
        if not self._groups:
            self._enter_mode("empty")
            return
        self._open_group_in_grid_workspace(group_id)

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
        self._open_group_in_grid_workspace(g.group_id)

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
            self._open_group_in_grid_workspace(group.group_id, preferred_a=f)

    def _keep_paths_for_current_filter(self) -> Set[str]:
        rule = normalized_rule(self._smart_rule or "keep_largest")
        kp: Set[str] = set()
        for g in self._groups:
            files = [f for f in g.files if self._passes_filter(f)]
            if len(files) < 2:
                continue
            try:
                keeper = apply_rule_with_pipeline(rule, files)
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

    def _refresh_groups_overview(self) -> None:
        filtered_groups = self._sorted_groups_for_current_filter()
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
            self._open_group_in_grid_workspace(group.group_id, preferred_a=f)

    def _open_group_in_grid_workspace(
        self,
        gid: int,
        *,
        preferred_a: Optional[DuplicateFile] = None,
    ) -> None:
        _t0 = time.perf_counter()
        files = self._group_files.get(gid) or []
        if not files:
            self._to_grid()
            self._log_if_slow("review:on_click_group_nav", _t0)
            return
        self._active_group_id = gid
        self._selected_group_id = gid
        if preferred_a is not None and any(
            f is preferred_a or str(f.path) == str(preferred_a.path) for f in files
        ):
            pick = next(f for f in files if f is preferred_a or str(f.path) == str(preferred_a.path))
            self._selected_file = pick
        else:
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
        self._log_if_slow("review:on_click_group_nav", _t0)

    def _toggle_mark_file(self, file: DuplicateFile) -> None:
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
        self._refresh_action_bar()
        self._stats_header.update_marked_metrics(len(self._marked_paths), self._marked_bytes)

    def _recompute_marked_bytes(self) -> None:
        self._marked_bytes = _marked_bytes_total(self._groups, self._marked_paths)
        self._refresh_action_bar()
        self._refresh_stats_header()

    def _trash_marked_files(self, e=None) -> None:
        if not self._marked_paths:
            return
        self._execute_smart_delete(sorted(self._marked_paths), DeletionPolicy.TRASH)

    def _delete_marked_permanently(self, e=None) -> None:
        if not self._marked_paths:
            return
        paths = sorted(self._marked_paths)
        self._show_smart_delete_dialog(paths)


class ReviewPageSmartMixin:
    def _on_smart_seg_change(self, e: ft.ControlEvent) -> None:
        sel = getattr(e.control, "selected", None) or {"keep_largest"}
        self._smart_rule = next(iter(sel), "keep_largest")
        if self._mode == "grid":
            self._refresh_grid()
        elif self._mode == "groups":
            self._refresh_groups_overview()
        self._refresh_stats_header()
        self._refresh_action_bar()

    def _deselect_all(self, e=None) -> None:
        self._marked_paths.clear()
        self._recompute_marked_bytes()
        self._push_marked_paths_to_store()
        if self._mode == "grid":
            self._grid_view.refresh_marks(self._marked_paths, self._keep_paths_for_current_filter())
        elif self._mode == "groups":
            self._refresh_groups_overview()

    def _apply_smart_select_review(self, e=None):
        self._apply_rule_to_all_groups()

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
        elif self._mode == "groups":
            self._refresh_groups_overview()

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
        elif self._mode == "groups":
            self._refresh_groups_overview()

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
        elif self._mode == "grid":
            self._refresh_grid()
        elif self._mode == "groups":
            self._refresh_groups_overview()

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


class ReviewPageFilterMixin:
    def _sync_workspace_preferences_from_state(self) -> None:
        state = self._bridge.state
        self._filter_key = str(state.review_file_filter or "all")
        self._search_query = str(state.results_text_filter or "").strip()
        ui = state.ui or {}
        self._cross_folder_only = bool(ui.get("workspace_cross_folder_only", False))
        if "workspace_view_mode" in ui:
            try:
                self._bridge.coordinator.workspace_set_ui_preferences({"workspace_view_mode": None})
            except Exception:
                pass
        self._review_scope = str(ui.get("workspace_review_scope", "all"))
        self._reviewed_group_ids = {int(x) for x in ui.get("workspace_reviewed_group_ids", [])}
        self._workstation_sidebar.set_review_scope(self._review_scope)
        stack = getattr(self, "_workspace_filter_stack", None)
        if stack is not None:
            stack.sync_from_state(
                filter_key=self._filter_key,
                text_filter=self._search_query,
                cross_folder_only=self._cross_folder_only,
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
        stack = getattr(self, "_workspace_filter_stack", None)
        if stack is not None:
            stack.filter_bar.update_counts(self._filter_counts, self._filter_sizes, self._filter_key)
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
        elif self._mode == "grid":
            self._refresh_grid()

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


class ReviewPageKeyboardMixin:
    def _bind_keys(self) -> None:
        self._bridge.flet_page.on_keyboard_event = self._on_key

    def _on_key(self, e: ft.KeyboardEvent) -> None:
        k = e.key.lower().replace(" ", "")
        if k == "escape":
            self._go_back()
            return
        if self._mode == "groups" and k == "g":
            self._enter_mode("grid")
        elif self._mode == "grid" and k == "g":
            self._enter_mode("groups")


class ReviewPageNavThemeMixin:
    def _go_back(self, e=None) -> None:
        if self._mode == "grid":
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
        self._grid_view.sync_theme(self._t)

        self._stats_header.bgcolor = self._t.colors.glass_bg
        edge_h = ft.Colors.with_opacity(0.1, ft.Colors.BLACK if app_theme_is_light(self._bridge) else ft.Colors.WHITE)
        self._stats_header.border = ft.border.only(bottom=ft.BorderSide(1, edge_h))
        self._workstation_sidebar.sync_theme(self._t)
        self._inspector_panel.sync_theme(self._t)
        self._review_action_bar.sync_theme(self._t)
        self._refresh_filter_labels()

        self._empty_state.bgcolor = self._t.colors.glass_bg
        self._empty_state.border = ft.border.all(1, self._t.colors.glass_border)
        self._empty_title_lbl.color = self._t.colors.fg
        self._empty_body_lbl.color = self._t.colors.fg_muted
        self._empty_title_lbl.size = self._t.typography.size_lg
        self._empty_body_lbl.size = self._t.typography.size_base
        if self._mode == "empty":
            self._sync_empty_workspace_message()

        self._apply_pill_chrome()

        if self._is_mounted():
            self.update()
