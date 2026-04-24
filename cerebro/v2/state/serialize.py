"""
JSON-friendly snapshot of :class:`AppState` (Blueprint §6 / §7 — engine web-ready prep).

Full ``DuplicateGroup`` payloads are not embedded; use path lists or engine APIs for that.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from cerebro.v2.state.app_state import AppState, AppMode


def _mode_value(m: AppMode) -> str:
    return m.value if isinstance(m, AppMode) else str(m)


def app_state_to_doc(state: AppState) -> Dict[str, Any]:
    """Return a JSON-serialisable dict (no engine objects)."""
    ui = dict(state.ui) if state.ui else {}
    return {
        "mode": _mode_value(state.mode),
        "theme": state.theme,
        "groups_count": len(state.groups),
        "selected_group_id": state.selected_group_id,
        "selected_files_count": len(state.selected_files),
        "filters": dict(state.filters),
        "scan_progress": dict(state.scan_progress),
        "ui": ui,
        "scan_mode": state.scan_mode,
        "active_tab": state.active_tab,
        "review_unlocked": state.review_unlocked,
        "dry_run": state.dry_run,
        "advanced_mode": state.advanced_mode,
        "history_scan_rows_count": len(state.history_scan_rows),
        "history_sort_column": state.history_sort_column,
        "history_sort_asc": state.history_sort_asc,
        "history_filter": state.history_filter,
        "history_page": state.history_page,
        "history_page_size": state.history_page_size,
        "results_file_filter": state.results_file_filter,
        "results_group_sort_column": state.results_group_sort_column,
        "results_group_sort_asc": state.results_group_sort_asc,
        "results_text_filter": state.results_text_filter,
        "review_file_filter": state.review_file_filter,
        "history_deletion_rows_count": len(state.history_deletion_rows),
        "scan_can_pause": state.scan_can_pause,
        "scan_can_resume": state.scan_can_resume,
        "scan_is_cancelled": state.scan_is_cancelled,
    }


def app_state_to_json(state: AppState, **json_kw: Any) -> str:
    return json.dumps(app_state_to_doc(state), **json_kw)


def action_to_json(action: object) -> str:
    """Best-effort JSON for a dispatched action (for logging / tests)."""
    if is_dataclass(action) and not isinstance(action, type):
        d: Dict[str, Any] = {"_type": type(action).__name__}
        d.update(asdict(action))  # type: ignore[arg-type]
        return json.dumps(d, default=str)
    return json.dumps({"_type": str(type(action)), "repr": repr(action)})
