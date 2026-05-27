"""Thumbnail cache rejects oversized files."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cerebro.v2.ui.flet_app.services.thumbnail_cache import ThumbnailCache


def test_oversized_file_skipped(monkeypatch) -> None:
    monkeypatch.setenv("CEREBRO_PREVIEW_MAX_BYTES", "100")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "big.bin"
        p.write_bytes(b"x" * 200)
        cache = ThumbnailCache(max_entries=4)
        assert cache.get_base64(p) is None
