"""
Advanced File Scanner - Enhanced
================================

High-performance file scanner with intelligent strategy selection,
multi-threading, real-time adaptation, and comprehensive filtering.

CONTRACT:
- Provides: FileScanner, ScanConfig, ScanStrategy, ScanPriority, ScanMode
- Requires: FileMetadata, FileType from core.models
- Interface: Generator[FileMetadata, None, None]
"""

from __future__ import annotations

import os
import sys
import time
import fnmatch
import hashlib
import threading
import queue
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from pathlib import Path
from typing import (
    List, Generator, Optional, Set, Dict,
    Callable, Any, Tuple, Union
)
from collections import defaultdict, deque
from cerebro.core.utils import(
    format_size,
    should_skip_directory,
    should_skip_file,
    calculate_file_hash,
    HashCache,
    is_system_file,          # NEW
)

# ------------------------------------------------------------
# Scanner-local tuning constants
# ------------------------------------------------------------

MAX_WORKERS_DEFAULT = 4
MAX_WORKERS_LIMIT = 16

HASH_CHUNK_SIZE = 1024 * 1024  # 1 MB

SCAN_CALLBACK_INTERVAL = 0.1   # seconds
PROGRESS_UPDATE_INTERVAL = 0.1 # seconds

# =====================================================================
# ENUMS
# =====================================================================

class ScanStrategy(Enum):
    """File scanning strategies with performance characteristics."""
    BASIC = auto()
    PARALLEL = auto()
    SMART = auto()
    QUICK = auto()
    DEEP = auto()
    INCREMENTAL = auto()
    PRIORITIZED = auto()


class ScanPriority(Enum):
    """Scan priority levels affecting CPU/memory allocation."""
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    REALTIME = auto()


class ScanMode(Enum):
    """Scan operation modes."""
    DISCOVERY = auto()
    ANALYSIS = auto()
    DEEP_ANALYSIS = auto()
    COMPARISON = auto()

class QuantumKind(str, Enum):
    """
    CEREBRO v5 "Quantum Scanning" selection.

    - INSTINCT  : gentle, fast, minimal analysis
    - INTUITION : balanced, learns, moderate analysis
    - REASON    : forensic, evidentiary, deep analysis
    """
    INSTINCT = "instinct"
    INTUITION = "intuition"
    REASON = "reason"



# =====================================================================
# SCAN CONFIG
# =====================================================================

@dataclass
class ScanConfig:
    """Complete scan configuration with sensible defaults."""

    # Core settings
    strategy: ScanStrategy = ScanStrategy.SMART
    priority: ScanPriority = ScanPriority.NORMAL
    mode: ScanMode = ScanMode.ANALYSIS

    # Performance tuning
    max_workers: int = 0  # 0 = auto-detect
    batch_size: int = 100
    timeout_seconds: int = 7200
    memory_limit_mb: int = 1024
    io_queue_size: int = 1000
    use_direct_io: bool = False

    # Behavior
    follow_symlinks: bool = False
    scan_hidden: bool = False
    max_depth: Optional[int] = None
    scan_subdirectories: bool = True
    preserve_directory_order: bool = False

    # Resource management
    cpu_threshold: float = 80.0
    memory_threshold: float = 85.0
    disk_read_threshold: float = 90.0
    adaptive_throttling: bool = True

    # Filtering
    min_file_size: int = 1024
    max_file_size: int = 0  # 0 = unlimited
    size_unit: str = "bytes"

    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    include_extensions: List[str] = field(default_factory=list)
    exclude_extensions: List[str] = field(default_factory=list)
    exclude_directories: List[str] = field(default_factory=list)

    # Smart filtering
    exclude_system_dirs: bool = True
    exclude_temp_files: bool = True
    exclude_backup_files: bool = True
    exclude_development_dirs: bool = True
    exclude_virtual_envs: bool = True
    exclude_node_modules: bool = True
    exclude_git_repos: bool = False
    exclude_cache_dirs: bool = True

    # Content analysis
    calculate_quick_hash: bool = True
    quick_hash_size: int = 4096
    calculate_full_hash: bool = False
    hash_algorithm: str = "md5"
    sample_content: bool = False
    sample_size: int = 16384

    # Progress reporting
    progress_interval: float = 0.25
    file_callback_batch: int = 50
    detailed_progress: bool = True

    # Recovery / persistence
    checkpoint_interval: int = 1000
    save_checkpoints: bool = False
    checkpoint_dir: Optional[Path] = None

    # Advanced
    use_mmap_for_large_files: bool = True
    mmap_threshold: int = 10485760
    buffer_size: int = 8192
    retry_failed_files: bool = True
    max_retries: int = 3
    retry_delay: float = 0.1

    def __post_init__(self):
        """Initialize derived settings."""
        if self.max_workers == 0:
            self.max_workers = self._auto_detect_workers()

        # Convert units
        if self.size_unit != "bytes":
            multiplier = {
                "KB": 1024,
                "MB": 1024 * 1024,
                "GB": 1024 * 1024 * 1024
            }.get(self.size_unit, 1)

            self.min_file_size *= multiplier

            if self.max_file_size > 0:
                self.max_file_size *= multiplier

    def _auto_detect_workers(self) -> int:
        """Auto-detect optimal number of workers."""
        try:
            cpu_count = os.cpu_count() or 1

            if self.strategy == ScanStrategy.BASIC:
                return 1
            elif self.strategy == ScanStrategy.PARALLEL:
                return min(cpu_count * 2, 16)
            elif self.strategy == ScanStrategy.QUICK:
                return min(cpu_count, 4)
            elif self.strategy == ScanStrategy.DEEP:
                return min(cpu_count, 8)
            else:
                return min(int(cpu_count * 1.5), 12)

        except Exception:
            return 4

    def to_dict(self) -> Dict[str, Any]:
        return {
            'strategy': self.strategy.name,
            'priority': self.priority.name,
            'mode': self.mode.name,
            'max_workers': self.max_workers,
            'memory_limit_mb': self.memory_limit_mb,
            'min_file_size': format_size(self.min_file_size),
            'max_file_size': (
                format_size(self.max_file_size)
                if self.max_file_size > 0 else "Unlimited"
            ),
            'follow_symlinks': self.follow_symlinks,
            'scan_hidden': self.scan_hidden,
            'max_depth': self.max_depth,
            'adaptive_throttling': self.adaptive_throttling,
            'exclude_system_dirs': self.exclude_system_dirs,
            'calculate_quick_hash': self.calculate_quick_hash,
            'calculate_full_hash': self.calculate_full_hash,
        }
# =====================================================================
# FILE SCANNER
# =====================================================================

class AdvancedScanner:
    """
    Core file scanning engine with strategy-based optimization.

    Features:
    - Multiple scanning strategies
    - Real-time resource adaptation
    - Progress tracking with ETA
    - Checkpointing and resume
    - Comprehensive error handling
    - Memory-efficient processing
    """

    def __init__(self, config: Optional[ScanConfig] = None):
        self.config = config or ScanConfig()
        self.scan_id = self._generate_scan_id()

        # State
        self.is_scanning = False
        self.is_paused = False
        self.is_stopping = False
        self.start_time = 0.0

        # Data structures
        self.file_queue = queue.Queue(maxsize=self.config.io_queue_size)
        self.directory_queue = queue.Queue()
        self.active_workers = 0

        # Statistics
        self.stats = {
            'files_scanned': 0,
            'files_found': 0,
            'files_skipped': 0,
            'directories_scanned': 0,
            'permission_errors': 0,
            'symlinks_skipped': 0,
            'system_files_skipped': 0,
            'temp_files_skipped': 0,
            'backup_files_skipped': 0,
            'hash_calculations': 0,
            'total_size': 0,
        }

        # Threading
        self.thread_pool: Optional[ThreadPoolExecutor] = None
        self.scan_futures: List[Future] = []
        self.lock = threading.RLock()

        # Pause control
        self.pause_event = threading.Event()
        self.pause_event.set()

        # Callbacks
        self.progress_callbacks: List[Callable[[ScanProgress], None]] = []
        self.file_callbacks: List[Callable[[FileMetadata], None]] = []
        self.error_callbacks: List[Callable[[str, Exception, Dict], None]] = []

        # Initialize strategy settings
        self._initialize_strategy()

    
# -----------------------------------------------------------------
# v5: Quantum scanning adapters
# -----------------------------------------------------------------

@classmethod
def create_for_request(
    cls,
    request: "PipelineRequest",
    *,
    kind: Optional[Union[str, QuantumKind]] = None,
) -> "AdvancedScanner":
    """
    Build an AdvancedScanner configured from PipelineRequest + (optional) QuantumKind.

    This is the canonical entrypoint for v5 "Quantum Scanning Engine" wiring.
    """
    cfg = cls.config_from_request(request, kind=kind)
    return cls(config=cfg)

@staticmethod
def config_from_request(
    request: "PipelineRequest",
    *,
    kind: Optional[Union[str, QuantumKind]] = None,
) -> "ScanConfig":
    """
    Map PipelineRequest into ScanConfig.

    Notes:
      - Scanning should be metadata-first. Hashing is optional and strategy-dependent.
      - The hashing pipeline (core/hashing.py) may still compute authoritative hashes later.
    """
    cfg = ScanConfig()

    # Basic request mapping
    cfg.follow_symlinks = bool(getattr(request, "follow_symlinks", False))
    cfg.scan_hidden = bool(getattr(request, "include_hidden", False))
    cfg.min_file_size = int(getattr(request, "min_size_bytes", cfg.min_file_size) or 0)
    cfg.max_workers = int(getattr(request, "max_workers", cfg.max_workers) or 0) or cfg.max_workers

    # Exclusions (directory names)
    exclude_dirs = getattr(request, "exclude_dirs", None)
    if isinstance(exclude_dirs, list):
        cfg.exclude_directories = [str(x) for x in exclude_dirs]

    # Quantum selection
    q = AdvancedScanner._infer_quantum_kind(request, kind=kind)
    AdvancedScanner._apply_quantum_kind_to_config(cfg, q)

    return cfg

@staticmethod
def _infer_quantum_kind(
    request: "PipelineRequest",
    *,
    kind: Optional[Union[str, QuantumKind]] = None,
) -> QuantumKind:
    if isinstance(kind, QuantumKind):
        return kind
    if isinstance(kind, str) and kind.strip():
        k = kind.strip().lower()
        if k in {"instinct", "intuition", "reason"}:
            return QuantumKind(k)

    intent = str(getattr(request, "scan_intent", "") or "").lower()
    state = str(getattr(request, "user_emotional_state", "") or "").lower()

    if state in {"stressed", "overwhelmed"} and "precious" not in intent:
        return QuantumKind.INSTINCT
    if any(x in intent for x in ("precious", "forensic", "meticulous")):
        return QuantumKind.REASON
    return QuantumKind.INTUITION

@staticmethod
def _apply_quantum_kind_to_config(cfg: "ScanConfig", kind: QuantumKind) -> None:
    # The scanner should not try to fully "decide" duplicates; it only discovers metadata.
    # But strategy affects traversal depth + optional hashing.
    if kind == QuantumKind.INSTINCT:
        cfg.strategy = ScanStrategy.QUICK
        cfg.priority = ScanPriority.LOW
        cfg.mode = ScanMode.DISCOVERY
        cfg.calculate_quick_hash = False
        cfg.calculate_full_hash = False
        cfg.max_depth = cfg.max_depth or 3
        cfg.max_workers = min(cfg.max_workers, 4) if cfg.max_workers else 4
        cfg.adaptive_throttling = True
    elif kind == QuantumKind.REASON:
        cfg.strategy = ScanStrategy.DEEP
        cfg.priority = ScanPriority.HIGH
        cfg.mode = ScanMode.DEEP_ANALYSIS
        cfg.calculate_quick_hash = True
        cfg.calculate_full_hash = True
        cfg.sample_content = True
        cfg.max_workers = min(cfg.max_workers, MAX_WORKERS_LIMIT) if cfg.max_workers else min(8, MAX_WORKERS_LIMIT)
    else:
        cfg.strategy = ScanStrategy.SMART
        cfg.priority = ScanPriority.NORMAL
        cfg.mode = ScanMode.ANALYSIS
        cfg.calculate_quick_hash = True
        cfg.calculate_full_hash = False
        cfg.sample_content = False
        cfg.max_workers = cfg.max_workers or MAX_WORKERS_DEFAULT

def scan_request(
    self,
    request: "PipelineRequest",
    *,
    progress_callback: Optional[Callable[[ScanProgress], None]] = None,
    file_callback: Optional[Callable[[FileMetadata], None]] = None,
    error_callback: Optional[Callable[[str, Exception, Dict], None]] = None,
    cancel_event: Optional[Any] = None,
) -> Generator[FileMetadata, None, None]:
    """Convenience wrapper: scan using a PipelineRequest."""
    paths = [str(p) for p in getattr(request, "roots", [])]
    yield from self.scan(
        paths,
        progress_callback=progress_callback,
        file_callback=file_callback,
        error_callback=error_callback,
        cancel_event=cancel_event,
    )
# -----------------------------------------------------------------
    # PATCHED: Legacy Compatibility Scanner (safe min/max sanitisation)
    # -----------------------------------------------------------------

    def scan_directory(self, directory: Path, options: Dict[str, Any]) -> List[FileMetadata]:
        """
        Backwards-compatibility adapter for older code that expects
        FileScanner.scan_directory(path, options).

        It performs a simple recursive walk of 'directory' and returns a
        list of FileMetadata objects, honoring the basic UI-driven options:
        - min_file_size / max_file_size
        - skip_hidden
        - skip_system
        - include_empty
        - include_patterns / exclude_patterns
        using the existing should_skip_* and is_system_file helpers.
        """
        directory = Path(directory)
        results: List[FileMetadata] = []

        # -----------------------------
        # 1. Sanitize numeric options
        # -----------------------------
        raw_min = options.get("min_file_size", self.config.min_file_size)
        if isinstance(raw_min, (int, float, str)):
            try:
                min_size = int(raw_min)
            except (TypeError, ValueError):
                min_size = self.config.min_file_size
        else:
            min_size = self.config.min_file_size

        raw_max = options.get("max_file_size", self.config.max_file_size or 0)
        if raw_max in (None, "", 0, "0"):
            max_size = 0  # 0 = unlimited
        elif isinstance(raw_max, (int, float, str)):
            try:
                max_size = int(raw_max)
            except (TypeError, ValueError):
                max_size = 0
        else:
            max_size = 0

        # -----------------------------
        # 2. Map UI flags → behaviour
        # -----------------------------
        skip_hidden = bool(options.get("skip_hidden", True))
        skip_system = bool(options.get("skip_system", True))
        include_empty = bool(options.get("include_empty", False))
        follow_symlinks = bool(options.get("follow_symlinks", self.config.follow_symlinks))

        include_patterns = options.get("include_patterns") or []
        exclude_patterns = options.get("exclude_patterns") or []

        # Helpers expect "include hidden?" flag
        scan_hidden = not skip_hidden

        # -----------------------------
        # 3. Walk the directory tree
        # -----------------------------
        for root, dirs, files in os.walk(directory, followlinks=follow_symlinks):
            root_path = Path(root)

            # Directory-level filter
            if should_skip_directory(root_path, scan_hidden):
                continue

            for name in files:
                file_path = root_path / name

                # System files (Thumbs.db, desktop.ini, etc.)
                if skip_system and is_system_file(file_path):
                    continue

                # Hidden / temp / backup filters
                if should_skip_file(file_path, scan_hidden):
                    continue

                # Include / exclude patterns (e.g. *.jpg;*.png)
                if include_patterns:
                    if not any(fnmatch.fnmatch(name, pat) for pat in include_patterns):
                        continue

                if exclude_patterns:
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude_patterns):
                        continue

                try:
                    meta = FileMetadata.from_path(file_path)
                    if not meta:
                        continue

                    # Empty-file handling
                    if not include_empty and meta.size == 0:
                        continue

                    # Size range filtering
                    if meta.size < min_size:
                        continue
                    if max_size > 0 and meta.size > max_size:
                        continue

                    results.append(meta)

                except Exception as e:
                    # Reuse your central error handler if present
                    try:
                        self._handle_error("scan_directory", e, {"path": str(file_path)})
                    except Exception:
                        # Last-resort: do not crash scanning on a single bad file
                        print(f"[FileScanner.scan_directory] Error on {file_path}: {e}")

        # -----------------------------
        # 4. Basic stats for compatibility
        # -----------------------------
        self.stats["files_found"] += len(results)
        self.stats["total_size"] += sum(f.size for f in results)

        return results

    # -----------------------------------------------------------------
    # SETUP
    # -----------------------------------------------------------------

    def scan(
        self,
        paths: List[Union[str, Path]],
        progress_callback: Optional[Callable[[ScanProgress], None]] = None,
        file_callback: Optional[Callable[[FileMetadata], None]] = None,
        error_callback: Optional[Callable[[str, Exception, Dict], None]] = None,
    *,
    cancel_event: Optional[Any] = None
    ) -> Generator[FileMetadata, None, None]:
        """
        Scan directories with the configured strategy.
        """

        if self.is_scanning:
            raise RuntimeError("Scanner is already running")

        try:
            # Prepare scan environment
            self._setup_scan(paths, progress_callback, file_callback, error_callback, cancel_event)

            # Execute based on strategy
            if self.config.strategy == ScanStrategy.PARALLEL:
                yield from self._execute_parallel_scan()

            elif self.config.strategy == ScanStrategy.INCREMENTAL:
                yield from self._execute_incremental_scan()

            elif self.config.strategy == ScanStrategy.PRIORITIZED:
                yield from self._execute_prioritized_scan()

            else:
                yield from self._execute_strategy_based_scan()

            # Finalise scan
            self._finalize_scan()

        except Exception as e:
            self._handle_error("scan_main", e, {"paths": paths})
            raise

        finally:
            self._cleanup()

    def _setup_scan(
        self,
        paths: List[Union[str, Path]],
        progress_callback: Optional[Callable[[ScanProgress], None]],
        file_callback: Optional[Callable[[FileMetadata], None]],
        error_callback: Optional[Callable[[str, Exception, Dict], None]],
        cancel_event: Optional[Any],
    ):
        """Prepare everything for a new scan."""

        self.is_scanning = True
        self.is_stopping = False
        self.start_time = time.time()
        self._external_cancel = cancel_event

        # Reset statistics
        self._reset_stats()

        # Register callbacks
        if progress_callback:
            self.progress_callbacks.append(progress_callback)

        if file_callback:
            self.file_callbacks.append(file_callback)

        if error_callback:
            self.error_callbacks.append(error_callback)

        # Validate paths
        self.scan_paths = self._validate_paths(paths)
        if not self.scan_paths:
            raise ValueError("No valid scan paths provided")

        # Estimate workload
        self.estimated_files = self._estimate_workload()

        # Initialise thread pool
        self.thread_pool = ThreadPoolExecutor(
            max_workers=self.config.max_workers,
            thread_name_prefix=f"Scanner_{self.scan_id[:8]}"
        )

    # -----------------------------------------------------------------

    def _validate_paths(self, paths: List[Union[str, Path]]) -> List[Path]:
        """Validate and normalize paths."""
        valid = []

        for p in paths:
            try:
                p_obj = Path(p) if isinstance(p, str) else p
                if p_obj.exists():
                    valid.append(p_obj.resolve())
            except Exception:
                pass

        return valid

    # -----------------------------------------------------------------

    def _estimate_workload(self) -> int:
        """Estimate total number of files (rough)."""
        return 10000
    # -----------------------------------------------------------------
    # PARALLEL STRATEGY
    # -----------------------------------------------------------------

    def _execute_parallel_scan(self) -> Generator[FileMetadata, None, None]:
        """Execute parallel scan strategy."""
        # Seed directory queue
        for path in self.scan_paths:
            self.directory_queue.put((path, 0))

        # Start worker threads
        workers: List[threading.Thread] = []

        for i in range(self.config.max_workers):
            worker = threading.Thread(
                target=self._parallel_worker,
                name=f"ParallelWorker-{i}",
                daemon=True,
            )
            worker.start()
            workers.append(worker)

        # Consume files
        while not self.is_stopping and not self._should_cancel():
            try:
                file_meta = self.file_queue.get(timeout=0.1)
                if file_meta is None:
                    break

                yield file_meta

                # Progress
                if self.stats['files_scanned'] % self.config.file_callback_batch == 0:
                    self._update_progress()

            except queue.Empty:
                # If all workers are done and no dirs remain, signal end
                if self.directory_queue.empty() and all(
                    not w.is_alive() for w in workers
                ):
                    for _ in range(self.config.max_workers):
                        self.file_queue.put(None)
                    break

        # Join workers
        for worker in workers:
            worker.join(timeout=1.0)

    def _parallel_worker(self):
        """Worker thread for parallel scanning."""
        while not self.is_stopping and not self._should_cancel():
            try:
                directory, depth = self.directory_queue.get(timeout=0.5)

                # Depth limit
                if (
                    self.config.max_depth is not None
                    and depth > self.config.max_depth
                ):
                    continue

                self._scan_directory_parallel(directory, depth)
                self.directory_queue.task_done()

            except queue.Empty:
                break
            except Exception as e:
                self._handle_error("parallel_worker", e, {"depth": depth})

    def _scan_directory_parallel(self, directory: Path, depth: int):
        """Scan a directory in parallel mode."""
        try:
            # Skip if needed
            if should_skip_directory(directory, self.config.scan_hidden):
                with self.lock:
                    self.stats['directories_scanned'] += 1
                return

            for entry in directory.iterdir():
                if self.is_stopping or self._should_cancel():
                    return

                try:
                    if entry.is_symlink():
                        self._handle_symlink(entry, depth)

                    elif entry.is_dir():
                        # Enqueue subdirectory
                        self.directory_queue.put((entry, depth + 1))

                    elif entry.is_file():
                        file_meta = self._process_file(entry)
                        if file_meta:
                            self.file_queue.put(file_meta)

                except PermissionError:
                    with self.lock:
                        self.stats['permission_errors'] += 1

                except Exception as e:
                    self._handle_error(
                        "parallel_entry",
                        e,
                        {"entry": str(entry)},
                    )

            with self.lock:
                self.stats['directories_scanned'] += 1

        except PermissionError:
            with self.lock:
                self.stats['permission_errors'] += 1

        except Exception as e:
            self._handle_error(
                "parallel_directory",
                e,
                {"directory": str(directory)},
            )
    # -----------------------------------------------------------------
    # STRATEGY ROUTER
    # -----------------------------------------------------------------

    def _execute_strategy_based_scan(self) -> Generator[FileMetadata, None, None]:
        """Execute scan based on selected strategy."""
        for path in self.scan_paths:
            if self.is_stopping or self._should_cancel():
                break

            if self.config.strategy == ScanStrategy.QUICK:
                yield from self._scan_quick(path, 0)
            else:
                yield from self._scan_recursive(path, 0)

    # -----------------------------------------------------------------
    # RECURSIVE SCAN STRATEGY
    # -----------------------------------------------------------------

    def _scan_recursive(self, directory: Path, depth: int) -> Generator[FileMetadata, None, None]:
        """Recursive directory scanning."""
        if self.is_stopping or self._should_cancel():
            return

        # Depth limit
        if self.config.max_depth is not None and depth > self.config.max_depth:
            return

        # Skip directory
        if should_skip_directory(directory, self.config.scan_hidden):
            with self.lock:
                self.stats['directories_scanned'] += 1
            return

        try:
            for entry in directory.iterdir():
                if self.is_stopping or self._should_cancel():
                    return

                try:
                    if entry.is_symlink():
                        self._handle_symlink(entry, depth)

                    elif entry.is_dir():
                        yield from self._scan_recursive(entry, depth + 1)

                    elif entry.is_file():
                        file_meta = self._process_file(entry)
                        if file_meta:
                            yield file_meta

                            if self.stats['files_scanned'] % self.config.file_callback_batch == 0:
                                self._update_progress()

                except PermissionError:
                    with self.lock:
                        self.stats['permission_errors'] += 1

                except Exception as e:
                    self._handle_error(
                        "recursive_entry",
                        e,
                        {"entry": str(entry)},
                    )

            with self.lock:
                self.stats['directories_scanned'] += 1
            self._update_progress()

        except PermissionError:
            with self.lock:
                self.stats['permission_errors'] += 1

        except Exception as e:
            self._handle_error(
                "recursive_directory",
                e,
                {"directory": str(directory)},
            )

    # -----------------------------------------------------------------
    # QUICK SCAN MODE (aggressive filtering)
    # -----------------------------------------------------------------

    def _scan_quick(self, directory: Path, depth: int) -> Generator[FileMetadata, None, None]:
        """Quick scan with aggressive filtering."""
        if depth > 2:
            return

        try:
            for entry in directory.iterdir():
                if self.is_stopping or self._should_cancel():
                    return

                try:
                    if entry.is_dir():
                        if not self._should_skip_directory_quick(entry):
                            yield from self._scan_quick(entry, depth + 1)

                    elif entry.is_file():
                        if not self._should_skip_file_quick(entry):
                            file_meta = self._quick_process_file(entry)
                            if file_meta:
                                yield file_meta

                                if self.stats['files_scanned'] % 100 == 0:
                                    self._update_progress()

                except PermissionError:
                    pass

                except Exception:
                    pass

        except PermissionError:
            pass

        except Exception as e:
            self._handle_error("quick_directory", e, {"directory": str(directory)})

    def _should_skip_directory_quick(self, directory: Path) -> bool:
        """Directories aggressively skipped in quick mode."""
        name = directory.name.lower()
        quick_skip = {
            'node_modules', '.git', '.svn', '.hg',
            '__pycache__', '.pytest_cache', '.mypy_cache',
            'vendor', 'packages', 'build', 'dist', 'target',
            'bin', 'obj', 'out', 'output', 'logs',
            '.idea', '.vscode', '.vs', '.settings',
            'venv', '.venv', 'env', '.env',
        }
        return name in quick_skip

    def _should_skip_file_quick(self, file_path: Path) -> bool:
        """Aggressive file-type skipping for quick mode."""
        common = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff',
            '.pdf', '.doc', '.docx', '.txt',
            '.mp4', '.avi', '.mkv', '.mov',
            '.mp3', '.wav', '.flac',
        }
        return file_path.suffix.lower() not in common

    # -----------------------------------------------------------------
    # SYMLINK HANDLING
    # -----------------------------------------------------------------

    def _handle_symlink(self, symlink_path: Path, depth: int):
        """Handle symbolic links safely."""
        if not self.config.follow_symlinks:
            with self.lock:
                self.stats['symlinks_skipped'] += 1
            return

        try:
            target = symlink_path.resolve()
            if target.exists():

                if target.is_dir():
                    self.directory_queue.put((target, depth + 1))

                elif target.is_file():
                    file_meta = self._process_file(target)
                    if file_meta:
                        self.file_queue.put(file_meta)

        except Exception:
            with self.lock:
                self.stats['symlinks_skipped'] += 1

    # -----------------------------------------------------------------
    # FILE PROCESSING (full mode)
    # -----------------------------------------------------------------

    def _process_file(self, file_path: Path) -> Optional[FileMetadata]:
        """Process a file and extract metadata."""
        with self.lock:
            self.stats['files_scanned'] += 1

        # Skip rule
        if should_skip_file(file_path, self.config.scan_hidden):
            with self.lock:
                self.stats['files_skipped'] += 1
            return None

        try:
            # Stat
            try:
                stat = file_path.stat()
            except (OSError, PermissionError):
                with self.lock:
                    self.stats['permission_errors'] += 1
                return None

            size = stat.st_size

            # Size filters
            if size < self.config.min_file_size:
                with self.lock:
                    self.stats['files_skipped'] += 1
                return None

            if self.config.max_file_size > 0 and size > self.config.max_file_size:
                with self.lock:
                    self.stats['files_skipped'] += 1
                return None

            # Create metadata
            meta = FileMetadata(
                path=file_path,
                filename=file_path.name,
                size=size,
                modified_time=stat.st_mtime,
                created_time=stat.st_ctime,
                extension=file_path.suffix.lower(),
            )

            # Quick hash
            if self.config.calculate_quick_hash:
                meta.hash_quick = calculate_file_hash(
                    file_path,
                    self.config.hash_algorithm,
                    partial=True,
                    sample_size=self.config.quick_hash_size,
                )
                with self.lock:
                    self.stats['hash_calculations'] += 1

            # Full hash
            if self.config.calculate_full_hash:
                meta.hash_full = calculate_file_hash(
                    file_path,
                    self.config.hash_algorithm,
                )
                with self.lock:
                    self.stats['hash_calculations'] += 1

            # Update statistics
            with self.lock:
                self.stats['files_found'] += 1
                self.stats['total_size'] += size

            # Callbacks
            for cb in self.file_callbacks:
                try:
                    cb(meta)
                except Exception as e:
                    self._handle_error("file_callback", e, {"file": str(file_path)})

            return meta

        except Exception as e:
            self._handle_error("file_processing", e, {"file": str(file_path)})
            return None

    # -----------------------------------------------------------------
    # QUICK FILE PROCESSING
    # -----------------------------------------------------------------

    def _quick_process_file(self, file_path: Path) -> Optional[FileMetadata]:
        """Minimal metadata for quick scanning."""
        try:
            stat = file_path.stat()
            size = stat.st_size

            if size < self.config.min_file_size:
                return None

            meta = FileMetadata(
                path=file_path,
                filename=file_path.name,
                size=size,
                modified_time=stat.st_mtime,
                extension=file_path.suffix.lower(),
            )

            with self.lock:
                self.stats['files_found'] += 1
                self.stats['total_size'] += size

            return meta

        except Exception:
            return None
    # -----------------------------------------------------------------
    # ERROR HANDLING
    # -----------------------------------------------------------------

    def _handle_error(self, context: str, error: Exception, extra_data: Dict = None):
        """Handle an error produced by workers or scan logic."""
        info = {
            'context': context,
            'error': str(error),
            'timestamp': time.time(),
        }

        if extra_data:
            info.update(extra_data)

        for cb in self.error_callbacks:
            try:
                cb(context, error, info)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # PROGRESS UPDATES
    # -----------------------------------------------------------------

    def _update_progress(self):
        """Emit a progress update event."""
        elapsed = time.time() - self.start_time
        fps = self.stats['files_scanned'] / elapsed if elapsed > 0 else 0

        progress = ScanProgress(
            files_scanned=self.stats['files_scanned'],
            directories_scanned=self.stats['directories_scanned'],
            total_files_estimated=self.estimated_files,
            percentage=(
                (self.stats['files_scanned'] / self.estimated_files) * 100
                if self.estimated_files > 0 else 0
            ),
            elapsed_seconds=elapsed,
            files_per_second=fps,
            stage=self.config.strategy.name.lower(),
        )

        for cb in self.progress_callbacks:
            try:
                cb(progress)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # FINALIZATION + CLEANUP
    # -----------------------------------------------------------------

    def _finalize_scan(self):
        """Finalize the scan (placeholder for extended logic)."""
        pass

    def _cleanup(self):
        """Cleanup resources after a scan finishes or crashes."""
        self.is_scanning = False

        if self.thread_pool:
            self.thread_pool.shutdown(wait=False)

    # -----------------------------------------------------------------
    # CHECKPOINT (TODO)
    # -----------------------------------------------------------------

    def _load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Load a saved checkpoint (not implemented)."""
        return None

    def _resume_from_checkpoint(self, checkpoint: Dict[str, Any]) -> Generator[FileMetadata, None, None]:
        """Resume scan from checkpoint (not implemented)."""
        yield from self._execute_strategy_based_scan()

    # -----------------------------------------------------------------
    # STOP / PAUSE / RESUME CONTROL
    # -----------------------------------------------------------------

    def stop(self):
        """Request immediate scan termination."""
        self.is_stopping = True

    def pause(self):
        """Pause scanning."""
        self.is_paused = True
        self.pause_event.clear()

    def resume(self):
        """Resume scanning."""
        self.is_paused = False
        self.pause_event.set()


def _should_cancel(self) -> bool:
    ev = getattr(self, "_external_cancel", None)
    if ev is None:
        return False
    try:
        return bool(ev.is_set())
    except Exception:
        return False
    # -----------------------------------------------------------------
    # UTILITIES
    # -----------------------------------------------------------------

    def _reset_stats(self):
        """Reset runtime statistics."""
        self.stats = {
            'files_scanned': 0,
            'files_found': 0,
            'files_skipped': 0,
            'directories_scanned': 0,
            'permission_errors': 0,
            'symlinks_skipped': 0,
            'system_files_skipped': 0,
            'temp_files_skipped': 0,
            'backup_files_skipped': 0,
            'hash_calculations': 0,
            'total_size': 0,
        }

    def _generate_scan_id(self) -> str:
        """Generate an 8-char short UUID."""
        import uuid
        return str(uuid.uuid4())[:8]

    def _initialize_strategy(self):
        """Set strategy-specific parameters."""
        if self.config.strategy == ScanStrategy.BASIC:
            self.config.max_workers = 1
            self.config.batch_size = 50

        elif self.config.strategy == ScanStrategy.QUICK:
            self.config.max_depth = self.config.max_depth or 3
            self.config.batch_size = 200

        elif self.config.strategy == ScanStrategy.DEEP:
            self.config.calculate_full_hash = True
            self.config.sample_content = True
