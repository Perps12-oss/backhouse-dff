# path: cerebro/core/reporting/json_report.py
"""
cerebro/core/reporting/json_report.py — JSON audit report exporter

Produces a single JSON file containing:
- scan metadata (if provided)
- duplicate groups summary (if provided)
- delete plan (if provided)
- deletion policy / dry-run flags

Everything is "duck typed" to avoid tight coupling.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_path(p: Any) -> str:
    try:
        return str(Path(p))
    except Exception:
        return str(p)


def _serialize_plan(plan: Any) -> Dict[str, Any]:
    if not plan:
        return {"items": [], "policy": None, "dry_run": True}

    items_out: List[Dict[str, Any]] = []
    items = getattr(plan, "items", None) or []
    for it in items:
        items_out.append(
            {
                "path": _safe_path(getattr(it, "path", it)),
                "reason": str(getattr(it, "reason", "")),
            }
        )

    return {
        "policy": getattr(getattr(plan, "policy", None), "value", getattr(plan, "policy", None)),
        "dry_run": bool(getattr(plan, "dry_run", False)),
        "token_present": bool(getattr(plan, "token", None)),
        "items": items_out,
    }


def _serialize_groups(groups: Any) -> List[Dict[str, Any]]:
    if not groups:
        return []
    out: List[Dict[str, Any]] = []

    for g in groups:
        if isinstance(g, dict):
            out.append(
                {
                    "key": g.get("hash") or g.get("key") or g.get("id"),
                    "size": g.get("size"),
                    "count": g.get("count") or (len(g.get("paths") or []) if isinstance(g.get("paths"), list) else None),
                    "paths": [str(p) for p in (g.get("paths") or [])],
                }
            )
        else:
            paths = getattr(g, "paths", None) or getattr(g, "files", None) or []
            out.append(
                {
                    "key": getattr(g, "key", None) or getattr(g, "hash", None) or getattr(g, "id", None),
                    "size": getattr(g, "size", None),
                    "count": getattr(g, "count", None) or (len(paths) if isinstance(paths, list) else None),
                    "paths": [str(p) for p in paths] if isinstance(paths, list) else [],
                }
            )
    return out


def write_json_report(
    out_path: Path,
    *,
    scan_id: str = "",
    request: Any = None,
    stats: Optional[Dict[str, Any]] = None,
    groups: Any = None,
    delete_plan: Any = None,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload: Dict[str, Any] = {
        "schema": "cerebro.report.v1",
        "generated_ts": time.time(),
        "scan_id": scan_id,
        "request": {
            "roots": [str(p) for p in (getattr(request, "roots", []) or [])],
            "mode": getattr(getattr(request, "mode", None), "value", getattr(request, "mode", None)),
            "use_full_hash": bool(getattr(request, "use_full_hash", False)),
            "validation_mode": bool(getattr(request, "validation_mode", False)),
            "options": getattr(request, "options", None),
        }
        if request is not None
        else {},
        "stats": stats or {},
        "groups": _serialize_groups(groups),
        "delete_plan": _serialize_plan(delete_plan),
    }

    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
