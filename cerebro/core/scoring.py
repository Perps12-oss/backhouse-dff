from __future__ import annotations

from cerebro.core.models import MediaItem


def enrich_item(item: MediaItem) -> MediaItem:
    """Lightweight enrichment; extend later (EXIF, duration, etc.) without changing core logic."""
    return item
