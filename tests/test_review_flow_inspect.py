from __future__ import annotations

from pathlib import Path

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.pages.review_flow.screens.inspect import metadata_match_flags


def test_metadata_match_flags_exact_pair() -> None:
    left = DuplicateFile(path=Path("/a/file.jpg"), size=100, modified=1.0, extension="jpg", metadata={"hash": "abc"})
    right = DuplicateFile(path=Path("/b/file.jpg"), size=100, modified=1.0, extension="jpg", metadata={"hash": "abc"})
    rows = metadata_match_flags(left, right)
    assert rows[0][3] == "✓"
    assert rows[2][3] == "⚠"
