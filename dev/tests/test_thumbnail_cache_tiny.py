"""ThumbnailCache tiny preview tier (perceived-performance)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cerebro.v2.ui.flet_app.services.thumbnail_cache import (
    TINY_BROWSE_EDGE,
    TINY_INSPECT_EDGE,
    ThumbnailCache,
)

pytest.importorskip("PIL")


def test_preview_tiny_smaller_payload_than_grid_thumb(tmp_path: Path) -> None:
    from PIL import Image

    p = tmp_path / "red.jpg"
    Image.new("RGB", (400, 300), (200, 10, 10)).save(p, quality=95)
    c = ThumbnailCache(max_entries=16)
    tiny = c.get_preview_tiny_base64(p, TINY_BROWSE_EDGE)
    small = c.get_preview_tiny_base64(p, TINY_INSPECT_EDGE)
    full = c.get_base64(p)
    assert tiny and small and full
    assert len(tiny) < len(full)
