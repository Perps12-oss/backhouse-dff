"""
cerebro/core/safety/trash_manager.py — RETIRED

This module has been retired. The managed-trash logic with rollback now lives in:
    cerebro.v2.ui.flet_app.services.delete_service.DeleteService._delete_to_managed_trash()

Kept as a stub to avoid ImportError for any out-of-tree code that still imports it.
"""
from __future__ import annotations

import warnings as _warnings


class TrashAction:
    """Retired stub — do not use."""
    def __init__(self, moved=None):
        self.moved = moved or []


class TrashManager:
    """Retired stub — do not use. See DeleteService._delete_to_managed_trash."""

    def __init__(self, *args, **kwargs):
        _warnings.warn(
            "TrashManager is retired. Use DeleteService._delete_to_managed_trash instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    def move_duplicates(self, *args, **kwargs) -> TrashAction:
        raise NotImplementedError("TrashManager is retired.")

    def undo(self, action: TrashAction) -> bool:
        raise NotImplementedError("TrashManager is retired.")
