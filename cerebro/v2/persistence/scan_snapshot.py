"""Persist last scan duplicate groups to disk so Welcome can re-open results."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.core.paths import cerebro_user_root

_log = logging.getLogger(__name__)

_VERSION = 1
_LAST_NAME = "last.json"


def _snap_dir() -> Path:
    p = cerebro_user_root() / "scan_snapshots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file_to_dict(f: DuplicateFile) -> Dict[str, Any]:
    return {
        "path": str(f.path),
        "size": int(f.size),
        "modified": float(f.modified),
        "extension": str(f.extension or ""),
        "is_keeper": bool(f.is_keeper),
        "similarity": float(f.similarity),
        "metadata": dict(f.metadata) if f.metadata else {},
    }


def _file_from_dict(d: Dict[str, Any]) -> DuplicateFile:
    return DuplicateFile(
        path=Path(str(d.get("path", ""))),
        size=int(d.get("size", 0) or 0),
        modified=float(d.get("modified", 0) or 0.0),
        extension=str(d.get("extension", "") or ""),
        is_keeper=bool(d.get("is_keeper", False)),
        similarity=float(d.get("similarity", 1.0) or 1.0),
        metadata=dict(d.get("metadata", {})) if isinstance(d.get("metadata"), dict) else {},
    )


def _group_to_dict(g: DuplicateGroup) -> Dict[str, Any]:
    return {
        "group_id": int(g.group_id),
        "similarity_type": str(g.similarity_type or "exact"),
        "files": [_file_to_dict(f) for f in g.files],
    }


def _group_from_dict(d: Dict[str, Any]) -> DuplicateGroup:
    files = [_file_from_dict(x) for x in (d.get("files") or []) if isinstance(x, dict)]
    return DuplicateGroup(
        group_id=int(d.get("group_id", 0)),
        files=files,
        similarity_type=str(d.get("similarity_type", "exact") or "exact"),
    )


def save_scan_results_snapshot(
    groups: List[DuplicateGroup],
    scan_mode: str,
    session_ts: float,
) -> None:
    """Write ``last.json`` + a session-keyed file for history matching."""
    if not groups:
        return
    try:
        payload: Dict[str, Any] = {
            "version": _VERSION,
            "session_ts": float(session_ts),
            "scan_mode": str(scan_mode or "files"),
            "groups": [_group_to_dict(g) for g in groups],
        }
        data = json.dumps(payload, ensure_ascii=False, indent=0)
        d = _snap_dir()
        (d / _LAST_NAME).write_text(data, encoding="utf-8")
        key = f"{float(session_ts):.9f}".replace(".", "_")
        (d / f"scan_{key}.json").write_text(data, encoding="utf-8")
    except (OSError, TypeError, ValueError, AttributeError) as e:
        _log.warning("save_scan_results_snapshot: %s", e)


def _read_payload(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        _log.debug("read snapshot %s: %s", path, e)
        return None


def _groups_from_payload(payload: Dict[str, Any]) -> Tuple[List[DuplicateGroup], str]:
    mode = str(payload.get("scan_mode", "files") or "files")
    gl = payload.get("groups") or []
    if not isinstance(gl, list):
        return [], mode
    out: List[DuplicateGroup] = []
    for item in gl:
        if isinstance(item, dict):
            try:
                out.append(_group_from_dict(item))
            except (TypeError, ValueError, KeyError, OSError) as e:
                _log.debug("skip group: %s", e)
                continue
    return out, mode


def load_last_scan_snapshot() -> Optional[Tuple[List[DuplicateGroup], str, float]]:
    """Return ``(groups, mode, session_ts)`` from ``last.json``."""
    p = _snap_dir() / _LAST_NAME
    if not p.is_file():
        return None
    payload = _read_payload(p)
    if not payload or int(payload.get("version", 0) or 0) < 1:
        return None
    groups, mode = _groups_from_payload(payload)
    if not groups:
        return None
    ts = float(payload.get("session_ts", 0.0) or 0.0)
    return groups, mode, ts


def load_scan_results_for_session_timestamp(
    entry_ts: float,
    tolerance: float = 1.0,
) -> Optional[Tuple[List[DuplicateGroup], str]]:
    """
    If ``entry_ts`` matches the last saved snapshot (same run as DB row), return groups.
    Also tries ``scan_*.json`` with matching ``session_ts``.
    """
    last = load_last_scan_snapshot()
    if last is not None:
        groups, mode, st = last
        if abs(float(entry_ts) - st) <= tolerance:
            return groups, mode
    d = _snap_dir()
    key = f"{float(entry_ts):.9f}".replace(".", "_")
    p = d / f"scan_{key}.json"
    if p.is_file():
        payload = _read_payload(p)
        if payload:
            g, mode = _groups_from_payload(payload)
            if g:
                return g, mode
    # Fuzzy: best match in directory
    best: Optional[Tuple[float, List[DuplicateGroup], str]] = None
    try:
        for child in d.glob("scan_*.json"):
            pl = _read_payload(child)
            if not pl:
                continue
            st = float(pl.get("session_ts", 0.0) or 0.0)
            g, mode = _groups_from_payload(pl)
            if not g:
                continue
            delta = abs(st - float(entry_ts))
            if best is None or delta < best[0]:
                best = (delta, g, mode)
    except OSError:
        pass
    if best is not None and best[0] <= tolerance * 2:
        return best[1], best[2]
    return None
