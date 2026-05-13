"""Compatibility shim — group cards live in ``components.files.group_card``."""

from cerebro.v2.ui.flet_app.components.files.group_card import (
    GroupCardWidget,
    build_group_card,
    group_duplicate_summary,
    group_path_hint,
)

__all__ = [
    "GroupCardWidget",
    "build_group_card",
    "group_duplicate_summary",
    "group_path_hint",
]
