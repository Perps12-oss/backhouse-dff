"""
Scan History grid: serializable row dicts, sort/filter/page projection (Blueprint §3).

The v2 DB model is :class:`cerebro.v2.core.scan_history_db.ScanHistoryEntry`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Tree column ids (match _ScanHistoryPanel._COLS)
HISTORY_SCAN_SORT_KEYS: Dict[str, str] = {
    "date": "ts",
    "mode": "mode",
    "folders": "folder_count",
    "groups": "groups",
    "files": "files",
    "reclaimable": "bytes",
    "duration": "duration",
}

HISTORY_SCAN_VALID_COLUMNS: frozenset[str] = frozenset(HISTORY_SCAN_SORT_KEYS.keys())


def default_sort_asc_for_column(col: str) -> bool:
    """First click on a column: numeric/time columns default to descending (largest/newest first)."""
    if col in ("date", "folders", "groups", "files", "reclaimable", "duration"):
        return False
    if col == "mode":
        return True
    return True


def scan_entry_to_row(e: Any) -> Dict[str, Any]:
    """Snapshot one DB row for ``AppState.history_scan_rows``."""
    return {
        "ts": float(e.timestamp),
        "mode": str(e.mode),
        "folder_count": int(len(e.folders)),
        "groups": int(e.groups_found),
        "files": int(e.files_found),
        "bytes": int(e.bytes_reclaimable),
        "duration": float(e.duration_seconds),
        "folders": list(e.folders),
    }


def row_to_entry_proxy(d: Dict[str, Any]) -> Any:
    """Rebuild a v2 :class:`ScanHistoryEntry` for double-click (session) hooks."""
    from cerebro.v2.core.scan_history_db import ScanHistoryEntry

    return ScanHistoryEntry(
        timestamp=float(d["ts"]),
        mode=str(d["mode"]),
        folders=list(d.get("folders", [])),
        groups_found=int(d["groups"]),
        files_found=int(d["files"]),
        bytes_reclaimable=int(d["bytes"]),
        duration_seconds=float(d["duration"]),
    )


def _row_filter_match(row: Dict[str, Any], q: str) -> bool:
    if not q or not str(q).strip():
        return True
    qn = str(q).strip().lower()
    parts = [
        str(row.get("mode", "")),
        str(row.get("ts", "")),
        str(row.get("folder_count", "")),
        str(row.get("groups", "")),
        str(row.get("files", "")),
        str(row.get("bytes", "")),
        str(row.get("duration", "")),
    ]
    parts.extend(str(f) for f in row.get("folders", []))
    blob = " ".join(parts).lower()
    return qn in blob


def _sort_key_value(row: Dict[str, Any], col: str) -> Any:
    sk = HISTORY_SCAN_SORT_KEYS.get(col, "ts")
    v = row.get(sk)
    if v is None:
        return 0
    if sk == "mode":
        return str(v).lower()
    return v


def apply_scan_history_view(
    rows: List[Dict[str, Any]],
    sort_column: str,
    sort_asc: bool,
    filter_text: str,
    page_index: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], int, int, int, int]:
    """
    Return (page_slice, total_filtered, num_pages, page_clamped, total_all).

    ``page_clamped`` is the 0-based index used after bounds check.
    """
    total_all = len(rows)
    if sort_column not in HISTORY_SCAN_VALID_COLUMNS:
        sort_column = "date"
    filtered = [r for r in rows if _row_filter_match(r, filter_text)]
    key = sort_column
    sk = HISTORY_SCAN_SORT_KEYS[key]

    reverse = not sort_asc
    try:
        if sk == "mode":
            filtered.sort(
                key=lambda r: str(r.get("mode", "")).lower(),
                reverse=reverse,
            )
        else:
            filtered.sort(
                key=lambda r: _sort_key_value(r, key),
                reverse=reverse,
            )
    except (TypeError, ValueError):
        pass

    n = len(filtered)
    if page_size <= 0:
        page_size = 30
    num_pages = max(1, (n + page_size - 1) // page_size) if n else 1
    page = max(0, min(int(page_index), num_pages - 1))
    start = page * page_size
    page_rows = filtered[start : start + page_size]
    return page_rows, n, num_pages, page, total_all
