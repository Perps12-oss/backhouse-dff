# cerebro/engines/image_formats.py
"""
Cerebro v2 Image Format Support Registry

Provides format detection and loading helpers for various image formats.

Supported formats:
- Common: JPG, JPEG, PNG, GIF, BMP, TIFF, TIF, WebP
- Modern: HEIC, HEIF
- RAW: CR2, CR3, NEF, ARW, DNG, ORF, RW2, PEF, RAF, SR2

Format loading handles different libraries for different formats:
- Pillow: Base image loading (supports most common formats)
- pillow-heif: HEIC/HEIF support
- rawpy: Camera RAW format support
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ============================================================================
# Image Format Categories
# ============================================================================


class ImageFormatCategory(Enum):
    """Categories of image formats."""

    COMMON = "common"      # JPG, PNG, GIF, etc.
    MODERN = "modern"      # HEIC, HEIF
    RAW = "raw"            # Camera RAW formats
    OTHER = "other"        # Other image types


# ============================================================================
# Image Format Definition
# ============================================================================


@dataclass
class ImageFormat:
    """Definition of an image format."""

    extensions: List[str]      # File extensions (e.g., [".jpg", ".jpeg"])
    mime_type: str             # MIME type
    category: ImageFormatCategory
    description: str
    is_lossy: bool = False    # True for lossy formats
    supports_exif: bool = True  # EXIF metadata support
    priority: int = 0            # Loading priority (higher = try first)


# ============================================================================
# Format Registry
# ============================================================================


class ImageFormatRegistry:
    """
    Registry of supported image formats.

    Provides:
        - Format lookup by extension
        - Format filtering by category
        - Loading helpers for different format types
    """

    # All supported formats
    _FORMATS: Dict[str, ImageFormat] = {}

    # Extension to format lookup cache
    _EXTENSION_MAP: Dict[str, ImageFormat] = {}

    @classmethod
    def register(cls, fmt: ImageFormat) -> None:
        """
        Register a new image format.

        Args:
            fmt: ImageFormat to register
        """
        for ext in fmt.extensions:
            ext_lower = ext.lower()
            cls._FORMATS[ext_lower] = fmt
            cls._EXTENSION_MAP[ext_lower] = fmt

    @classmethod
    def get_format(cls, extension: str) -> Optional[ImageFormat]:
        """
        Look up format by file extension.

        Args:
            extension: File extension (with or without dot, case-insensitive)

        Returns:
            ImageFormat if found, None otherwise
        """
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        return cls._EXTENSION_MAP.get(ext)

    @classmethod
    def is_supported(cls, path: Path) -> bool:
        """
        Check if a file path has a supported image extension.

        Args:
            path: File path to check

        Returns:
            True if extension is in registry
        """
        ext = path.suffix.lower()
        return ext in cls._EXTENSION_MAP

    @classmethod
    def get_supported_extensions(cls, categories: Optional[List[ImageFormatCategory]] = None) -> Set[str]:
        """
        Get all supported extensions, optionally filtered by category.

        Args:
            categories: Optional list of categories to filter

        Returns:
            Set of supported extensions
        """
        if categories is None:
            return set(cls._EXTENSION_MAP.keys())

        result = set()
        for fmt in cls._FORMATS.values():
            if fmt.category in categories:
                result.update(fmt.extensions)
        return result

    @classmethod
    def get_by_category(cls, category: ImageFormatCategory) -> List[ImageFormat]:
        """
        Get all formats in a specific category.

        Args:
            category: Category to filter by

        Returns:
            List of ImageFormat objects
        """
        return [fmt for fmt in cls._FORMATS.values() if fmt.category == category]

    @classmethod
    def get_all(cls) -> List[ImageFormat]:
        """Return all registered formats."""
        return list(cls._FORMATS.values())


# Register common formats
ImageFormatRegistry.register(ImageFormat(
    extensions=[".jpg", ".jpeg"],
    mime_type="image/jpeg",
    category=ImageFormatCategory.COMMON,
    description="JPEG Image",
    is_lossy=True,
    priority=10,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".png"],
    mime_type="image/png",
    category=ImageFormatCategory.COMMON,
    description="PNG Image",
    is_lossy=False,
    priority=10,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".gif"],
    mime_type="image/gif",
    category=ImageFormatCategory.COMMON,
    description="GIF Image",
    is_lossy=True,
    priority=10,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".bmp"],
    mime_type="image/bmp",
    category=ImageFormatCategory.COMMON,
    description="BMP Image",
    is_lossy=False,
    priority=5,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".tiff", ".tif"],
    mime_type="image/tiff",
    category=ImageFormatCategory.COMMON,
    description="TIFF Image",
    is_lossy=False,
    priority=8,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".webp"],
    mime_type="image/webp",
    category=ImageFormatCategory.COMMON,
    description="WebP Image",
    is_lossy=True,
    priority=9,
))

# Register modern formats
ImageFormatRegistry.register(ImageFormat(
    extensions=[".heic", ".heif"],
    mime_type="image/heic",
    category=ImageFormatCategory.MODERN,
    description="HEIC/HEIF Image",
    is_lossy=True,
    priority=7,
))

# Register RAW formats
ImageFormatRegistry.register(ImageFormat(
    extensions=[".cr2", ".cr3"],
    mime_type="image/x-canon-cr2",
    category=ImageFormatCategory.RAW,
    description="Canon RAW",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".nef"],
    mime_type="image/x-nikon-nef",
    category=ImageFormatCategory.RAW,
    description="Nikon RAW",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".arw"],
    mime_type="image/x-sony-arw",
    category=ImageFormatCategory.RAW,
    description="Sony RAW",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".dng"],
    mime_type="image/x-adobe-dng",
    category=ImageFormatCategory.RAW,
    description="Adobe DNG",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".orf"],
    mime_type="image/x-olympus-orf",
    category=ImageFormatCategory.RAW,
    description="Olympus RAW",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".rw2"],
    mime_type="image/x-panasonic-rw2",
    category=ImageFormatCategory.RAW,
    description="Panasonic RAW",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".pef"],
    mime_type="image/x-pentax-pef",
    category=ImageFormatCategory.RAW,
    description="Pentax RAW",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".raf"],
    mime_type="image/x-fuji-raf",
    category=ImageFormatCategory.RAW,
    description="Fujifilm RAW",
    is_lossy=False,
    priority=6,
))

ImageFormatRegistry.register(ImageFormat(
    extensions=[".sr2"],
    mime_type="image/x-sony-sr2",
    category=ImageFormatCategory.RAW,
    description="Sony RAW (SR2)",
    is_lossy=False,
    priority=6,
))


# ============================================================================
# Image Loading Helpers
# ============================================================================


def load_image(path: Path) -> Optional["Image"]:
    """
    Load an image file using appropriate loader.

    Tries different libraries based on file extension:
    - Pillow (PIL) for most formats
    - pillow-heif for HEIC/HEIF
    - rawpy for RAW formats

    Args:
        path: Path to image file

    Returns:
        PIL Image object if successful, None otherwise
    """
    try:
        from PIL import Image as PILImage
    except ImportError:
        return None

    ext = path.suffix.lower()
    fmt = ImageFormatRegistry.get_format(ext)

    if fmt is None:
        # Try with default Pillow loader
        try:
            return PILImage.open(path)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return None

    # HEIC/HEIF formats - need pillow-heif
    if fmt.category == ImageFormatCategory.MODERN:
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            return PILImage.open(path)
        except ImportError:
            # Fallback: try standard Pillow
            try:
                return PILImage.open(path)
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                return None

    # RAW formats - need rawpy
    if fmt.category == ImageFormatCategory.RAW:
        try:
            import rawpy
            with rawpy.imread(str(path)) as raw:
                # rawpy returns numpy array, convert to PIL Image
                rgb = raw.postprocess()
                return PILImage.fromarray(rgb)
        except ImportError:
            return None
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return None

    # Common formats - standard Pillow
    try:
        return PILImage.open(path)
    except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
        return None


def get_image_metadata(path: Path) -> Dict:
    """
    Extract metadata from an image file.

    Extracts:
        - Resolution (width, height)
        - Format (from Pillow or registry)
        - EXIF data (date, camera, etc.)

    Args:
        path: Path to image file

    Returns:
        Dict with metadata fields
    """
    metadata = {
        "resolution": None,
        "width": 0,
        "height": 0,
        "format": None,
        "exif_date": None,
        "exif_camera": None,
        "exif_iso": None,
        "exif_focal": None,
        "has_exif": False,
    }

    try:
        from PIL import Image as PILImage, ExifTags
    except ImportError:
        return metadata

    img = load_image(path)
    if img is None:
        return metadata

    metadata["width"] = img.width
    metadata["height"] = img.height
    metadata["resolution"] = f"{img.width} × {img.height}"
    metadata["format"] = img.format.upper() if img.format else "UNKNOWN"

    # Try to extract EXIF data
    try:
        exif_data = img._getexif()
        if exif_data is not None:
            metadata["has_exif"] = True

            # Map EXIF tags to readable names
            exif = {ExifTags.TAGS.get(k, k): v for k, v in exif_data.items()}

            # Extract common EXIF fields
            if "DateTimeOriginal" in exif:
                metadata["exif_date"] = exif["DateTimeOriginal"]
            if "Make" in exif or "Model" in exif:
                camera = f"{exif.get('Make', '')} {exif.get('Model', '')}".strip()
                metadata["exif_camera"] = camera if camera else None
            if "ISOSpeedRatings" in exif:
                metadata["exif_iso"] = exif["ISOSpeedRatings"]
            if "FocalLength" in exif:
                focal = exif["FocalLength"]
                if focal and focal > 0:
                    metadata["exif_focal"] = f"{focal/10:.1f}mm"
    except (AttributeError, KeyError, Exception):
        pass

    return metadata


# ============================================================================
# Union-Find for Clustering
# ============================================================================


class UnionFind:
    """
    Union-Find (Disjoint Set) data structure.

    Used for clustering similar images:
        If A~B and B~C, then {A, B, C} are in the same group.
    """

    def __init__(self, size: int = 0) -> None:
        """
        Initialize Union-Find.

        Args:
            size: Number of elements (optional, can grow dynamically)
        """
        self.parent: Dict[int, int] = {}
        self.rank: Dict[int, int] = {}
        self._count = 0

    def add(self, x: int) -> None:
        """Add a new element as its own set."""
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            self._count += 1

    def find(self, x: int) -> int:
        """
        Find the root/representative of x's set.

        Implements path compression.
        """
        if x not in self.parent:
            self.add(x)
            return x

        # Path compression
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        """
        Merge the sets containing x and y.

        Implements union by rank.
        """
        root_x = self.find(x)
        root_y = self.find(y)

        if root_x == root_y:
            return  # Already in same set

        # Union by rank
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1

    def get_groups(self) -> List[List[int]]:
        """
        Get all disjoint sets as groups.

        Returns:
            List of groups, each group is a list of indices
        """
        groups: Dict[int, List[int]] = {}

        for x in self.parent:
            root = self.find(x)
            if root not in groups:
                groups[root] = []
            groups[root].append(x)

        return list(groups.values())

    @property
    def count(self) -> int:
        """Number of elements."""
        return self._count


# ============================================================================
# Hamming Distance
# ============================================================================


def hamming_distance(hash1: int, hash2: int) -> int:
    """
    Compute Hamming distance between two integer hashes.

    Hamming distance = number of bits that differ.

    Args:
        hash1: First hash as integer
        hash2: Second hash as integer

    Returns:
        Number of differing bits
    """
    return bin(hash1 ^ hash2).count("1")


def similarity_from_hamming(distance: int, max_distance: int) -> float:
    """
    Convert Hamming distance to similarity score.

    Args:
        distance: Hamming distance
        max_distance: Maximum possible Hamming distance (hash size in bits)

    Returns:
        Similarity score from 0.0 to 1.0
    """
    if max_distance == 0:
        return 1.0
    return max(0.0, 1.0 - (distance / max_distance))


__all__ = [
    "ImageFormatCategory",
    "ImageFormat",
    "ImageFormatRegistry",
    "load_image",
    "get_image_metadata",
    "UnionFind",
    "hamming_distance",
    "similarity_from_hamming",
]
