from __future__ import annotations

from pathlib import Path
from typing import Optional


def build_diff_heatmap_path(left: Path, right: Path) -> Optional[str]:
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    if not left.exists() or not right.exists():
        return None
    try:
        a = Image.open(left).convert("RGB")
        b = Image.open(right).convert("RGB")
        if a.size != b.size:
            b = b.resize(a.size)
        diff = ImageChops.difference(a, b)
        out = left.parent / f".diff_{left.stem}_{right.stem}.png"
        diff.save(out)
        return str(out)
    except OSError:
        return None
