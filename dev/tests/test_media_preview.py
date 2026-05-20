from __future__ import annotations

from pathlib import Path

import flet as ft

from cerebro.v2.ui.flet_app.media_preview import (
    flet_icon_for_bucket,
    media_bucket_for_path,
    preview_kind_for_path,
)
from cerebro.v2.ui.flet_app.services.thumbnail_cache import decode_preview_jpeg_b64


def test_media_bucket_and_icons() -> None:
    assert media_bucket_for_path("/a/photo.jpg") == "pictures"
    assert media_bucket_for_path("/a/song.mp3") == "music"
    assert flet_icon_for_bucket("videos") == ft.icons.Icons.MOVIE_OUTLINED


def test_preview_kind() -> None:
    assert preview_kind_for_path("x.png") == "image"
    assert preview_kind_for_path("readme.txt") == "text"
    assert preview_kind_for_path("clip.bin") == "icon"


def test_text_preview_decode(tmp_path: Path) -> None:
    p = tmp_path / "sample.txt"
    p.write_text("line one\nline two\n", encoding="utf-8")
    b64 = decode_preview_jpeg_b64(p, 64, 70)
    assert b64
    assert len(b64) > 100
