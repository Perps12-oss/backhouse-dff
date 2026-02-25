# path: cerebro/core/visual_hashing.py
"""Visual hashing primitives for Similar Match.

Implements:
- dHash (difference hash): fast, robust to resize/compression
- pHash (perceptual hash via DCT): more accurate for near-duplicates

All hashes are unsigned 64-bit integers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".heic", ".avif"
}


@dataclass(frozen=True, slots=True)
class VisualHashSettings:
    bitmap_size: int = 64
    algorithm: str = "phash"  # "dhash" | "phash"
    orientation_invariant: bool = True
    phash_hash_size: int = 8  # 8x8 => 64-bit


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def hamming_distance(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def compute_visual_hash(path: Path, settings: VisualHashSettings) -> Optional[int]:
    algo = (settings.algorithm or "phash").strip().lower()
    if algo == "dhash":
        return compute_dhash(path, orientation_invariant=settings.orientation_invariant)
    if algo == "phash":
        return compute_phash(
            path,
            bitmap_size=settings.bitmap_size,
            hash_size=settings.phash_hash_size,
            orientation_invariant=settings.orientation_invariant,
        )
    raise ValueError(f"Unknown similarity algorithm: {algo}")


def compute_dhash(path: Path, *, orientation_invariant: bool) -> Optional[int]:
    """Classic 64-bit dHash using an 9x8 grayscale sample."""
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError("Pillow is required for Similar Match (pip install pillow).") from e

    target_w, target_h = 9, 8  # 8 comparisons per row => 64 bits

    def _hash(img: "Image.Image") -> int:
        g = img.convert("L").resize((target_w, target_h), Image.Resampling.LANCZOS)
        px = list(g.getdata())
        out = 0
        bit = 1 << 63
        for y in range(target_h):
            row = px[y * target_w:(y + 1) * target_w]
            for x in range(8):
                if row[x] > row[x + 1]:
                    out |= bit
                bit >>= 1
        return out

    try:
        img = Image.open(path)
        img.load()
    except Exception:
        return None

    variants = [img]
    if orientation_invariant:
        try:
            variants = [
                img,
                img.rotate(90, expand=True),
                img.rotate(180, expand=True),
                img.rotate(270, expand=True),
                img.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                img.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
                img.transpose(Image.Transpose.FLIP_LEFT_RIGHT).rotate(90, expand=True),
                img.transpose(Image.Transpose.FLIP_TOP_BOTTOM).rotate(90, expand=True),
            ]
        except Exception:
            variants = [img]

    best: Optional[int] = None
    for v in variants:
        try:
            hv = _hash(v)
        except Exception:
            continue
        best = hv if best is None else min(best, hv)
    return best


def compute_phash(
    path: Path,
    *,
    bitmap_size: int,
    hash_size: int,
    orientation_invariant: bool,
) -> Optional[int]:
    """64-bit pHash using 2D DCT. bitmap_size should be >= 2*hash_size."""
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError("Pillow is required for Similar Match (pip install pillow).") from e

    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError("numpy is required for Similar Match (pip install numpy).") from e

    try:
        from scipy.fftpack import dct
    except Exception as e:
        raise RuntimeError("scipy is required for Similar Match (pip install scipy).") from e

    hash_size = max(4, int(hash_size))
    bitmap_size = max(int(bitmap_size), hash_size * 2)

    def _dct2(a: "np.ndarray") -> "np.ndarray":
        return dct(dct(a, axis=0, norm="ortho"), axis=1, norm="ortho")

    def _hash(img: "Image.Image") -> int:
        g = img.convert("L").resize((bitmap_size, bitmap_size), Image.Resampling.LANCZOS)
        arr = np.asarray(g, dtype=np.float32)
        coeff = _dct2(arr)
        low = coeff[:hash_size, :hash_size].copy()
        med = np.median(low[1:, 1:])
        bits = (low > med).flatten()[:64]
        out = 0
        for b in bits:
            out = (out << 1) | int(bool(b))
        return out & ((1 << 64) - 1)

    try:
        img = Image.open(path)
        img.load()
    except Exception:
        return None

    variants = [img]
    if orientation_invariant:
        try:
            variants = [
                img,
                img.rotate(90, expand=True),
                img.rotate(180, expand=True),
                img.rotate(270, expand=True),
                img.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
                img.transpose(Image.Transpose.FLIP_TOP_BOTTOM),
                img.transpose(Image.Transpose.FLIP_LEFT_RIGHT).rotate(90, expand=True),
                img.transpose(Image.Transpose.FLIP_TOP_BOTTOM).rotate(90, expand=True),
            ]
        except Exception:
            variants = [img]

    best: Optional[int] = None
    for v in variants:
        try:
            hv = _hash(v)
        except Exception:
            continue
        best = hv if best is None else min(best, hv)
    return best
