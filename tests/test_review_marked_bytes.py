"""Consistency checks for Review marked-bytes incremental updates."""

from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review.review_mixins import _marked_bytes_total


def _f(name: str, size: int) -> DuplicateFile:
    return DuplicateFile(
        path=Path(name),
        size=size,
        modified=0.0,
        extension=Path(name).suffix or "",
    )


def test_incremental_toggle_matches_full_scan() -> None:
    a = _f("/x/a.bin", 100)
    b = _f("/x/b.bin", 200)
    c = _f("/x/c.bin", 50)
    g1 = DuplicateGroup(group_id=1, files=[a, b])
    g2 = DuplicateGroup(group_id=2, files=[c])
    groups = [g1, g2]
    marked: set[str] = set()
    total = 0

    def apply_toggle(file: DuplicateFile) -> None:
        nonlocal total
        fp = str(file.path)
        sz = int(file.size)
        if fp in marked:
            marked.discard(fp)
            total -= sz
        else:
            marked.add(fp)
            total += sz
        if total < 0:
            total = 0
        assert total == _marked_bytes_total(groups, marked), (fp, marked, total)

    apply_toggle(a)
    apply_toggle(b)
    apply_toggle(c)
    apply_toggle(b)
    apply_toggle(a)
    apply_toggle(c)
