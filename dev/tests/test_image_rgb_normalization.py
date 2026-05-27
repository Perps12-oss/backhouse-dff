"""
test_image_rgb_normalization.py — M-6: CMYK / GIF images produce stable hashes after RGB normalization.
"""
from __future__ import annotations

import io
import pytest


def _pil_available():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _pil_available(), reason="Pillow not installed")
def test_cmyk_image_normalizes_to_rgb():
    from PIL import Image as _Image
    from cerebro.engines.image_dedup_engine import _normalize_pillow_image

    # Create a tiny CMYK image in memory.
    img = _Image.new("CMYK", (4, 4), (0, 128, 64, 32))
    normalized = _normalize_pillow_image(img)
    assert normalized.mode == "RGB", f"Expected RGB, got {normalized.mode}"


@pytest.mark.skipif(not _pil_available(), reason="Pillow not installed")
def test_gif_image_normalizes_to_rgb():
    from PIL import Image as _Image
    from cerebro.engines.image_dedup_engine import _normalize_pillow_image

    img = _Image.new("P", (4, 4))
    normalized = _normalize_pillow_image(img)
    assert normalized.mode == "RGB"


@pytest.mark.skipif(not _pil_available(), reason="Pillow not installed")
def test_rgb_image_stays_rgb():
    from PIL import Image as _Image
    from cerebro.engines.image_dedup_engine import _normalize_pillow_image

    img = _Image.new("RGB", (8, 8), (10, 20, 30))
    normalized = _normalize_pillow_image(img)
    assert normalized.mode == "RGB"


@pytest.mark.skipif(not _pil_available(), reason="Pillow not installed")
def test_normalization_is_stable():
    """Applying _normalize_pillow_image twice must produce the same hash."""
    from PIL import Image as _Image
    from cerebro.engines.image_dedup_engine import _normalize_pillow_image

    img = _Image.new("CMYK", (4, 4), (0, 0, 0, 0))
    n1 = _normalize_pillow_image(img)
    n2 = _normalize_pillow_image(img)
    assert list(n1.getdata()) == list(n2.getdata())
