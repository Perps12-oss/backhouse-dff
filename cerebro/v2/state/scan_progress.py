"""
Serialize :class:`cerebro.engines.base_engine.ScanProgress` into a JSON-friendly dict
for :class:`cerebro.v2.state.app_state.AppState` ``scan_progress``.
"""

from __future__ import annotations

from typing import Any, Dict

from cerebro.engines.base_engine import ScanProgress, ScanState


def scan_progress_to_dict(p: ScanProgress) -> Dict[str, Any]:
    st = p.state
    st_val = st.value if isinstance(st, ScanState) else str(st)
    d: Dict[str, Any] = {
        "state": st_val,
        "files_scanned": p.files_scanned,
        "files_total": p.files_total,
        "duplicates_found": p.duplicates_found,
        "groups_found": p.groups_found,
        "bytes_reclaimable": p.bytes_reclaimable,
        "elapsed_seconds": p.elapsed_seconds,
        "current_file": p.current_file,
        "eta_seconds": p.eta_seconds,
        "stage": p.stage,
    }
    return d
