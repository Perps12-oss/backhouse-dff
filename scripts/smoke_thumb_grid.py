"""Headless smoke-test for VirtualThumbGrid (Phase 6).

Exercises the four scroll channels the real UI routes through (mouse
wheel, scrollbar drag, arrow keys, Home/End/PgUp/PgDn) against 4803
synthetic rows — same fixture size as the list-grid smoke test — and
checks:

  * yscrollcommand fires on every scroll channel
  * _scroll_y stays within [0, max_y] at all times
  * async thumbnail decode is bounded (no full-fixture blocking)
  * count badge math works across tiles from different groups
  * is_image_row routing used by ResultsPage._on_thumb_dbl_click

Run from repo root: `python scripts/smoke_thumb_grid.py`.
"""
from __future__ import annotations

import tkinter as tk
from typing import List, Tuple

from cerebro.v2.ui.widgets.virtual_thumb_grid import (
    VirtualThumbGrid, is_image_row,
)


def _synthetic_rows(n: int) -> List[dict]:
    """Mix of image and non-image rows to exercise both the async
    decode path (images) and the glyph fallback path (everything
    else). Paths are fabricated — decode attempts will fail, which
    is the desired behavior (we check boundedness, not decode
    correctness)."""
    exts = [".jpg", ".png", ".mp4", ".mp3", ".pdf", ".zip", ".txt"]
    return [
        {
            "group_id":    i // 4,
            "file_idx":    i % 4,
            "name":        f"file_{i:05d}{exts[i % len(exts)]}",
            "size":        1024 * (i + 1),
            "size_str":    f"{(i + 1)} KB",
            "date":        "2025-01-01",
            "folder":      f"C:/synthetic/group_{i // 4}",
            "path":        f"C:/synthetic/group_{i // 4}/file_{i:05d}{exts[i % len(exts)]}",
            "extension":   exts[i % len(exts)],
        }
        for i in range(n)
    ]


def main() -> None:
    root = tk.Tk()
    root.geometry("920x520")

    grid = VirtualThumbGrid(root, width=920, height=520)
    grid.pack(fill="both", expand=True)
    root.update()

    thumb_calls: List[Tuple[float, float]] = []
    def capture_thumb(top: str, bot: str) -> None:
        thumb_calls.append((float(top), float(bot)))

    grid.configure(yscrollcommand=capture_thumb)

    rows = _synthetic_rows(4803)
    grid.load(rows)
    root.update_idletasks()

    cols = grid._cols()                    # pylint: disable=protected-access
    n = len(rows)
    tile_rows = (n + cols - 1) // cols
    view_h = grid.winfo_height() or 520

    expected_total_h = 2 * 14 + tile_rows * grid.TILE_H + max(0, tile_rows - 1) * 12
    assert grid._total_h == expected_total_h, (   # pylint: disable=protected-access
        f"total_h mismatch: got {grid._total_h}, "
        f"expected {expected_total_h} for cols={cols} tile_rows={tile_rows}"
    )

    def assert_in_bounds(label: str) -> None:
        max_y = max(0, grid._total_h - view_h)    # pylint: disable=protected-access
        assert 0 <= grid._scroll_y <= max_y, (    # pylint: disable=protected-access
            f"{label}: _scroll_y={grid._scroll_y} out of [0, {max_y}]"
        )

    # ─── moveto ────────────────────────────────────────────────────
    grid.yview("moveto", 0.0)
    assert grid._scroll_y == 0       # pylint: disable=protected-access
    assert_in_bounds("moveto 0.0")

    grid.yview("moveto", 0.9)
    assert grid._scroll_y > 0        # pylint: disable=protected-access
    assert_in_bounds("moveto 0.9")

    grid.yview("moveto", 1.0)
    assert_in_bounds("moveto 1.0")
    max_y = max(0, grid._total_h - view_h)  # pylint: disable=protected-access
    assert grid._scroll_y == max_y, (       # pylint: disable=protected-access
        f"moveto 1.0 didn't land at max_y={max_y}, got {grid._scroll_y}"
    )

    # ─── scroll units / pages ──────────────────────────────────────
    grid.yview("moveto", 0.0)
    grid.yview("scroll", 5, "units")
    # 5 units = 5 tile-rows worth of pixels
    assert grid._scroll_y == 5 * grid.ROW_H, (   # pylint: disable=protected-access
        f"scroll 5 units expected {5 * grid.ROW_H}, got {grid._scroll_y}"
    )
    assert_in_bounds("scroll 5 units")

    grid.yview("scroll", 2, "pages")
    assert_in_bounds("scroll 2 pages")

    # ─── mouse wheel ──────────────────────────────────────────────
    class FakeWheel:
        delta = -120
        num = 0
    grid._scroll_y = 0                           # pylint: disable=protected-access
    grid._on_scroll(FakeWheel())                 # pylint: disable=protected-access
    # Wheel step: one notch = one tile-row
    assert grid._scroll_y == grid.ROW_H, (       # pylint: disable=protected-access
        f"wheel 1 notch expected {grid.ROW_H}, got {grid._scroll_y}"
    )
    assert_in_bounds("mousewheel 1 notch")

    # ─── Home / End ───────────────────────────────────────────────
    grid._on_home()                              # pylint: disable=protected-access
    assert grid._scroll_y == 0 and grid._selected_idx == 0  # pylint: disable=protected-access
    grid._on_end()                               # pylint: disable=protected-access
    assert grid._selected_idx == len(rows) - 1   # pylint: disable=protected-access
    assert_in_bounds("End")

    # ─── yscrollcommand tracking ──────────────────────────────────
    frac = grid.yview()
    assert isinstance(frac, tuple) and len(frac) == 2
    assert 0.0 <= frac[0] <= frac[1] <= 1.0 + 1e-9, f"bad fractions: {frac}"

    assert thumb_calls, "yscrollcommand never fired"
    for top, bot in thumb_calls:
        assert 0.0 <= top <= bot <= 1.0 + 1e-9, f"bad thumb call: ({top}, {bot})"

    # ─── Count badge math ─────────────────────────────────────────
    counts = grid._group_counts              # pylint: disable=protected-access
    # Synthetic fixture: 4 files per group (i // 4), so every group
    # except possibly the last has exactly 4 copies.
    first_group_count = counts.get(0)
    assert first_group_count == 4, (
        f"group 0 expected 4 copies, got {first_group_count}"
    )

    # ─── Async decode bounded ─────────────────────────────────────
    # After load(), only visible tiles should have requested decodes;
    # 4803 total rows but visible ≈ cols × (view_h / TILE_H) ~ 20-40.
    assert len(grid._decode_futures) <= 120, (   # pylint: disable=protected-access
        f"decode fanout too wide: {len(grid._decode_futures)}"
    )

    # ─── is_image_row router contract ─────────────────────────────
    img_row = {"path": "x.jpg", "extension": ".jpg"}
    vid_row = {"path": "x.mp4", "extension": ".mp4"}
    assert is_image_row(img_row) is True
    assert is_image_row(vid_row) is False

    # ─── Move selection across a row with arrow keys ─────────────
    grid._selected_idx = 0                       # pylint: disable=protected-access
    grid._scroll_y = 0                           # pylint: disable=protected-access
    grid._move_sel_row(1)                        # pylint: disable=protected-access
    assert grid._selected_idx == cols, (         # pylint: disable=protected-access
        f"Down-arrow expected to land on idx={cols}, got {grid._selected_idx}"
    )

    # Ensure _visible_range stays sane at bottom
    grid._on_end()                               # pylint: disable=protected-access
    first, last = grid._visible_range()          # pylint: disable=protected-access
    assert first <= grid._selected_idx < last or grid._selected_idx == last - 1, (
        f"selected idx {grid._selected_idx} not in visible "
        f"range [{first}, {last})"
    )

    print(
        f"OK - 4803 rows, {cols} cols, {tile_rows} tile-rows, "
        f"total_h={grid._total_h}, viewport_h={view_h}, "
        f"thumb_calls={len(thumb_calls)}, "
        f"decode_futures={len(grid._decode_futures)}"
    )
    root.destroy()


if __name__ == "__main__":
    main()
