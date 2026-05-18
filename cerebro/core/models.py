# cerebro/core/models.py

from __future__ import annotations
from dataclasses import dataclass, field
import dataclasses
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any
import time

# -- Modes & Policies --

class PipelineMode(str, Enum):
    EXACT = "exact"
    VISUAL = "visual"
    FUZZY = "fuzzy"

class DeletionPolicy(str, Enum):
    """
    H-2/B-3: This is a legacy alias kept for old imports.
    Canonical: cerebro.core.deletion.DeletionPolicy
    Values are identical strings so comparisons still work.
    """
    MOVE_TO_TRASH = "trash"
    DELETE_PERMANENTLY = "permanent"

class FileStatus(str, Enum):
    DUPLICATE = "duplicate"
    SURVIVOR = "survivor"
    PROTECTED = "protected"
    UNKNOWN = "unknown"

# -- Scan Request Config --

@dataclass
class StartScanConfig:
    root: Path
    mode: PipelineMode = PipelineMode.EXACT
    min_size_bytes: int = 102_400  # 100 KB
    hash_bytes: int = 1024
    follow_symlinks: bool = False
    include_hidden: bool = False
    fast_mode: bool = True
    max_workers: int = 4
    allowed_extensions: Optional[List[str]] = None
    exclude_dirs: Optional[List[Path]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": str(self.root),
            "mode": self.mode.value,
            "min_size_bytes": self.min_size_bytes,
            "hash_bytes": self.hash_bytes,
            "follow_symlinks": self.follow_symlinks,
            "include_hidden": self.include_hidden,
            "fast_mode": self.fast_mode,
            "max_workers": self.max_workers,
            "allowed_extensions": self.allowed_extensions,
            "exclude_dirs": [str(p) for p in self.exclude_dirs or []],
        }

# -- Pipeline Request for scanning --

@dataclass
class PipelineRequest:
    scan_id: str
    config: StartScanConfig

    def to_dict(self):
        return {
            "scan_id": self.scan_id,
            "config": self.config.to_dict(),
        }

    def to_history_entry(self, name: str, engine_version: str) -> "ScanHistoryEntry":
        from cerebro.history.models import ScanHistoryEntry, ScanStatus

        return ScanHistoryEntry(
            scan_id=self.scan_id,
            name=name,
            root_path=str(self.config.root),
            status=ScanStatus.IN_PROGRESS,
            engine_version=engine_version,
            settings_snapshot=self.config.to_dict(),
        )

# H-2/B-3: models.DeletionRequest is retired.
# Canonical: cerebro.core.deletion.DeletionRequest
# Kept as stub to avoid ImportError on stale imports.

@dataclass
class DeletionRequest:
    """Retired stub. Canonical: cerebro.core.deletion.DeletionRequest"""
    scan_id: str = ""
    deletion_policy: object = None
    files_to_delete: List[Path] = None  # type: ignore[assignment]

# -- Match Grouping / Rendering --

@dataclass
class FileCandidate:
    path: Path
    size_bytes: int
    mtime: float
    hash: Optional[str] = None
    score: Optional[float] = None
    status: FileStatus = FileStatus.UNKNOWN
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class GroupCandidate:
    group_id: str
    files: List[FileCandidate]
    reason: str = "hash"
    cluster_score: Optional[float] = None

# Add at bottom of cerebro/core/models.py

@dataclass
class FileMetadata:
    path: Path
    size: int
    mtime: float
    is_symlink: bool = False
    is_hidden: bool = False
    extension: Optional[str] = None
    hash_partial: Optional[str] = None
    hash_full: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path),
            "size": self.size,
            "mtime": self.mtime,
            "is_symlink": self.is_symlink,
            "is_hidden": self.is_hidden,
            "extension": self.extension,
            "hash_partial": self.hash_partial,
            "hash_full": self.hash_full,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FileMetadata":
        return FileMetadata(
            path=Path(d["path"]),
            size=d.get("size", 0),
            mtime=d.get("mtime", 0.0),
            is_symlink=d.get("is_symlink", False),
            is_hidden=d.get("is_hidden", False),
            extension=d.get("extension"),
            hash_partial=d.get("hash_partial"),
            hash_full=d.get("hash_full"),
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
        )


    @staticmethod
    def from_path(path: "str | Path") -> Optional["FileMetadata"]:
        """Create FileMetadata from a filesystem path.

        Returns None only if the file does not exist or cannot be stat'ed.
        """
        try:
            p = Path(path)
            if not p.exists() or not p.is_file():
                return None

            st = p.stat()
            is_symlink = p.is_symlink()
            # Windows hidden detection is non-trivial; keep a simple heuristic
            is_hidden = p.name.startswith(".") or p.name.lower() in {"desktop.ini", "thumbs.db"}

            ext = p.suffix.lower() if p.suffix else None

            return FileMetadata(
                path=p,
                size=int(st.st_size),
                mtime=float(st.st_mtime),
                is_symlink=bool(is_symlink),
                is_hidden=bool(is_hidden),
                extension=ext,
                hash_partial=None,
                hash_full=None,
                tags=[],
                metadata={}
            )
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return None

# H-2: DuplicateGroup is removed from models.py.
# Canonical definition: cerebro.engines.base_engine.DuplicateGroup
# The old models.DuplicateGroup (group_id: str, files: List[FileMetadata]) is now retired.
# trash_manager.py (which imported it) has been retired too.

@dataclass
class DuplicateItem:
    """A specific file within a duplicate group (scored, ranked)."""
    file: FileMetadata
    is_selected: bool = False
    is_survivor: bool = False
    score: float = 0.0
    deletion_candidate: bool = False
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file.to_dict(),
            "is_selected": self.is_selected,
            "is_survivor": self.is_survivor,
            "score": self.score,
            "deletion_candidate": self.deletion_candidate,
            "notes": self.notes,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DuplicateItem":
        return DuplicateItem(
            file=FileMetadata.from_dict(d["file"]),
            is_selected=d.get("is_selected", False),
            is_survivor=d.get("is_survivor", False),
            score=d.get("score", 0.0),
            deletion_candidate=d.get("deletion_candidate", False),
            notes=d.get("notes", ""),
        )

class FileType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    ARCHIVE = "archive"
    OTHER = "other"

    @staticmethod
    def from_extension(ext: str) -> "FileType":
        ext = ext.lower()
        if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic"}:
            return FileType.IMAGE
        if ext in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            return FileType.VIDEO
        if ext in {".mp3", ".wav", ".aac", ".flac", ".ogg"}:
            return FileType.AUDIO
        if ext in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"}:
            return FileType.DOCUMENT
        if ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
            return FileType.ARCHIVE
        return FileType.OTHER

# H-2/IS-1: models.ScanProgress is retired — zero import sites confirmed.
# Canonical: cerebro.engines.base_engine.ScanProgress
# Stub retained only to prevent ImportError on stale imports.
@dataclass
class ScanProgress:
    """Retired stub. Canonical: cerebro.engines.base_engine.ScanProgress"""
    phase: str = ""
    message: str = ""
    percent: float = 0.0
    scanned_files: int = 0
    scanned_bytes: int = 0
    elapsed_seconds: float = 0.0
    estimated_total_files: Optional[int] = None
    estimated_total_bytes: Optional[int] = None
    speed_files_per_sec: Optional[float] = None
    throughput_mb_per_sec: Optional[float] = None
    eta_seconds: Optional[float] = None
    warnings_count: Optional[int] = None
    groups_found: Optional[int] = None
    current_path: Optional[str] = None
    scan_id: Optional[str] = None
    timestamp: Optional[float] = None
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScanProgress":
        valid = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(cls)}}
        return cls(**valid)

    def copy_with(self, **kwargs) -> "ScanProgress":
        from dataclasses import replace
        return replace(self, **kwargs)

@dataclass
class ComparisonStats:
    total_groups: int = 0
    total_files: int = 0
    confirmed_duplicates: int = 0
    potential_matches: int = 0
    survivor_kept: int = 0
    deleted_files: int = 0
    deleted_bytes: int = 0

# Note: DeletionPolicy is already defined at the top, so we remove the duplicate