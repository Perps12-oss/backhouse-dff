# cerebro/ui/ui_state.py
"""Persist UI state (e.g. Start page locations, sidebar collapsed) across sessions."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

def _state_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path.home() / ".local" / "share"
    path = base / "CEREBRO" / "ui_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def load_locations() -> List[str]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return list(data.get("locations") or [])
    except Exception:
        return []

def save_locations(locations: List[str]) -> None:
    path = _state_path()
    data = {}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    data["locations"] = list(locations)[:50]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def load_sidebar_collapsed() -> bool:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return bool(data.get("locations_sidebar_collapsed", False))
    except Exception:
        return False

def save_sidebar_collapsed(collapsed: bool) -> None:
    path = _state_path()
    data = {}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    data["locations_sidebar_collapsed"] = collapsed
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
