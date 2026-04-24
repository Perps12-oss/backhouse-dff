"""Map SQLite deletion history rows to plain dicts for :class:`AppState`."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def deletion_db_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    """``get_recent_history`` row: ``(id, filename, path, size, deletion_date, mode)``."""
    _id, filename, path, size, deletion_date, mode = row
    return {
        "id": _id,
        "filename": filename,
        "path": str(path),
        "size": int(size or 0),
        "deletion_date": str(deletion_date),
        "mode": str(mode),
    }
