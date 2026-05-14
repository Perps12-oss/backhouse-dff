"""Tests for shared UI helpers and design system wrappers."""

from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.components.common.chunked_view import (
    REVIEW_GRID_FILES_CHUNK,
    REVIEW_GROUPS_CHUNK,
    RESULTS_GRID_CHUNK,
    RESULTS_LIST_CHUNK,
)
from cerebro.v2.ui.flet_app.components.files.group_card import group_duplicate_summary, group_path_hint, is_machine_generated_name
from cerebro.v2.ui.flet_app.components.layout.responsive_grid import (
    NARROW_BREAKPOINT_PX,
    inspector_overlay_width,
    is_narrow_viewport,
)
from cerebro.v2.ui.flet_app.design_system.accents import PRIMARY
from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.design_system.skeleton import skeleton_block
from cerebro.v2.ui.flet_app.theme import theme_for_mode

import flet as ft


def test_glass_container_uses_theme_tokens() -> None:
    t = theme_for_mode("dark")
    ctrl = glass_container(content=ft.Text("hello"), t=t)
    assert ctrl.bgcolor == t.colors.glass_bg
    assert ctrl.border is not None


def test_chunked_view_presets_match_live_thresholds() -> None:
    assert RESULTS_LIST_CHUNK.async_threshold == 72
    assert RESULTS_GRID_CHUNK.async_threshold == 36
    assert REVIEW_GROUPS_CHUNK.first_sync_count == 40
    assert REVIEW_GRID_FILES_CHUNK.batch_size == 30


def test_group_duplicate_summary_exact_copies() -> None:
    group = DuplicateGroup(
        group_id=1,
        files=[
            DuplicateFile(path=Path("a.jpg"), size=1, modified=0.0, extension=".jpg"),
            DuplicateFile(path=Path("b.jpg"), size=1, modified=0.0, extension=".jpg"),
        ],
        similarity_type="exact",
    )
    summary = group_duplicate_summary(group)
    assert "2 byte-identical files" in summary


def test_group_path_hint_same_folder() -> None:
    files = [
        DuplicateFile(path=Path("C:/data/a.txt"), size=1, modified=0.0, extension=".txt"),
        DuplicateFile(path=Path("C:/data/b.txt"), size=1, modified=0.0, extension=".txt"),
    ]
    hint = group_path_hint(files)
    assert hint.startswith("Same folder")


def test_machine_generated_name_heuristic() -> None:
    assert is_machine_generated_name("short-name.txt") is False
    assert is_machine_generated_name("12345678901234567890123456789012345678901234567890.jpg") is True


def test_responsive_breakpoint() -> None:
    assert is_narrow_viewport(NARROW_BREAKPOINT_PX - 1) is True
    assert is_narrow_viewport(NARROW_BREAKPOINT_PX) is False
    assert inspector_overlay_width(800) is None
    assert inspector_overlay_width(1200) == 336


def test_skeleton_block_uses_theme() -> None:
    t = theme_for_mode("dark")
    block = skeleton_block(t, width=80, height=20)
    assert block.height == 20
    assert block.width == 80


def test_accent_primary_token() -> None:
    assert PRIMARY.startswith("#")
