# path: cerebro/core/fast_pipeline.py
"""
cerebro/core/fast_pipeline.py — ULTRA-FAST duplicate scan pipeline for 500K+ files

Key goals:
- Non-blocking UI: call from a worker thread (PySide6 worker)
- Frequent progress updates
- High throughput: scandir recursion, size grouping, batched parallel hashing
- Robust: permission errors, locked files, cancellation
- Speed on re-runs: persistent SQLite cache (via cerebro/services/hash_cache.py)

Output format:
{
  "ok": True,
  "groups": [ {"hash":..., "size":..., "paths":[...], "count":...}, ... ],
  "stats": {...}
}
"""

from __future__ import annotations

import os
import time
import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from cerebro.services.hash_cache import HashCache, StatSignature
from cerebro.services.logger import get_logger

ProgressCB = Callable[[int, str, Dict[str, Any]], None]

MAX_WORKERS_LIMIT = 32

logger = get_logger(__name__)


def _diagnose_pair(path_a: str, path_b: str, size: int) -> None:
    """Log if two same-size paths resolve to the same canonical file (inode or realpath)."""
    try:
        a_real = unicodedata.normalize("NFC", os.path.normcase(os.path.realpath(path_a))).strip()
        b_real = unicodedata.normalize("NFC", os.path.normcase(os.path.realpath(path_b))).strip()
        if a_real == b_real:
            logger.info(
                "[DIAG:PAIR] canonical-path-collision size=%d path_a=%.80s path_b=%.80s",
                size, path_a, path_b,
            )
            return
    except (OSError, ValueError):
        pass
    try:
        a_st = os.stat(path_a)
        b_st = os.stat(path_b)
        if a_st.st_ino != 0 and a_st.st_ino == b_st.st_ino and a_st.st_dev == b_st.st_dev:
            logger.info(
                "[DIAG:PAIR] inode-collision size=%d ino=%d dev=%d path_a=%.80s path_b=%.80s",
                size, a_st.st_ino, a_st.st_dev, path_a, path_b,
            )
    except (OSError, ValueError):
        pass


class _HashCache:
    """
    Backward-compatible adapter for the old fast cache interface.

    Old interface used:
      get(path, size, mtime_seconds) -> quick_hash str | None
      set_many([(path, size, mtime_seconds, quick_hash), ...])

    Internally it uses HashCache (mtime in ns + dev/inode).
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._cache = HashCache(self.db_path)

    def open(self) -> None:
        self._cache.open()

    def close(self) -> None:
        self._cache.close()

    def get(self, path: str, size: int, mtime: float) -> Optional[str]:
        try:
            sig = StatSignature(size=int(size), mtime_ns=int(float(mtime) * 1_000_000_000), dev=0, inode=0)
            return self._cache.get_quick(path, sig)
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return None

    def set_many(self, rows: List[Tuple[str, int, float, str]]) -> None:
        try:
            for p, size, mtime, qh in rows:
                sig = StatSignature(size=int(size), mtime_ns=int(float(mtime) * 1_000_000_000), dev=0, inode=0)
                self._cache.set_quick(p, sig, str(qh), algo="md5")
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return


@dataclass(frozen=True, slots=True)
class FastFileInfo:
    path: str
    size: int
    mtime: float
    ext: str = ""


class FastDiscovery:
    """Very fast iterative directory scan using os.scandir (no recursion stack explosion)."""

    def scan(
        self,
        root: Path,
        *,
        include_hidden: bool,
        follow_symlinks: bool,
        allowed_exts: Optional[List[str]],
        exclude_dirs: Optional[List[str]],
        min_size: int,
        cancel_check: Callable[[], bool],
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> List[FastFileInfo]:
        out: List[FastFileInfo] = []
        stack: List[Path] = [Path(root)]
        last_report = 0
        report_interval = 5000

        while stack:
            if cancel_check():
                break

            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        if cancel_check():
                            break

                        name = entry.name
                        if not include_hidden and name.startswith("."):
                            continue

                        try:
                            if entry.is_dir(follow_symlinks=follow_symlinks):
                                if exclude_dirs and name in exclude_dirs:
                                    continue
                                stack.append(Path(entry.path))
                                continue

                            if not entry.is_file(follow_symlinks=follow_symlinks):
                                continue

                            st = entry.stat(follow_symlinks=follow_symlinks)
                            size = int(st.st_size)
                            if size < int(min_size):
                                continue

                            ext = os.path.splitext(name)[1].lower()
                            if allowed_exts and ext not in allowed_exts:
                                continue

                            out.append(
                                FastFileInfo(
                                    path=entry.path,
                                    size=size,
                                    mtime=float(st.st_mtime),
                                    ext=ext,
                                )
                            )
                            if progress_callback and len(out) - last_report >= report_interval:
                                progress_callback(len(out))
                                last_report = len(out)
                        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                            continue
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                continue

        if progress_callback and len(out) != last_report:
            progress_callback(len(out))
        return out


class FastPipeline:
    """Main ultra-fast pipeline. Engine 'simple' = balanced; 'advanced' = more workers + fuller hash."""

    def __init__(
        self,
        max_workers: int = 0,
        cache_path: Optional[Path] = None,
        engine: str = "simple",
    ):
        import multiprocessing

        cpu = multiprocessing.cpu_count()
        base_workers = max(4, cpu * 2) if max_workers <= 0 else int(max_workers)
        self.engine = (engine or "simple").lower()
        if self.engine == "advanced":
            self.max_workers = min(MAX_WORKERS_LIMIT, base_workers * 2)
        else:
            self.max_workers = base_workers
        self.discovery = FastDiscovery()
        self._cancelled = False
        self.cache_path = cache_path

    def cancel(self) -> None:
        self._cancelled = True

    def run_fast_scan(
        self,
        root: Path,
        *,
        min_size: int = 1024,
        include_hidden: bool = False,
        follow_symlinks: bool = False,
        allowed_extensions: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None,
        progress_cb: Optional[ProgressCB] = None,
    ) -> Dict[str, Any]:
        start = time.time()
        self._cancelled = False

        def cancelled() -> bool:
            return bool(self._cancelled)

        def emit(pct: int, msg: str, meta: Dict[str, Any]):
            if progress_cb:
                progress_cb(int(max(0, min(100, pct))), msg, meta)

        emit(0, "FAST MODE: Discovering files…", {"phase": "discovering"})

        def discovery_progress(count: int) -> None:
            if progress_cb and not cancelled():
                pct = min(18, int(18 * min(1.0, count / max(1, 100_000))))
                progress_cb(
                    pct,
                    f"Discovering… {count:,} files",
                    {"phase": "discovering", "files_scanned": count},
                )

        files = self.discovery.scan(
            Path(root),
            include_hidden=include_hidden,
            follow_symlinks=follow_symlinks,
            allowed_exts=[e.lower() for e in (allowed_extensions or [])] or None,
            exclude_dirs=exclude_dirs,
            min_size=min_size,
            cancel_check=cancelled,
            progress_callback=discovery_progress,
        )

        if cancelled():
            return {"cancelled": True, "ok": False, "stats": {"files_scanned": len(files)}}

        logger.info(
            "[DIAG:DISCOVERY] root=%s discovered=%d min_size=%d",
            root, len(files), min_size,
        )

        emit(20, f"Grouping by size ({len(files):,} files)…", {"phase": "grouping", "files_scanned": len(files)})
        size_map: Dict[int, List[FastFileInfo]] = {}
        for f in files:
            size_map.setdefault(f.size, []).append(f)

        candidates: List[FastFileInfo] = []
        for _fp_sz, _fp_arr in size_map.items():
            if len(_fp_arr) > 1:
                candidates.extend(_fp_arr)
                _fp_cap = min(len(_fp_arr), 8)
                for _fp_i in range(_fp_cap):
                    for _fp_j in range(_fp_i + 1, _fp_cap):
                        _diagnose_pair(_fp_arr[_fp_i].path, _fp_arr[_fp_j].path, _fp_sz)

        logger.info(
            "[DIAG:REDUCE] after_size_group size_groups=%d candidates=%d",
            sum(1 for arr in size_map.values() if len(arr) > 1), len(candidates),
        )

        if cancelled():
            return {"cancelled": True, "ok": False, "stats": {"files_scanned": len(files)}}

        emit(25, f"Hashing {len(candidates):,} candidates…", {"phase": "hashing", "files_scanned": len(files)})

        cache = None
        if self.cache_path:
            try:
                cache = _HashCache(self.cache_path)
                cache.open()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                cache = None

        try:
            t0 = time.time()
            total = len(candidates)
            done = 0
            hash_groups: Dict[str, List[str]] = {}
            to_hash: List[FastFileInfo] = []
            cache_writes: List[Tuple[str, int, float, str]] = []

            _diag_cache_hits = 0
            _diag_cache_misses = 0
            if cache:
                for f in candidates:
                    qh = cache.get(f.path, f.size, f.mtime)
                    if qh:
                        hash_groups.setdefault(qh, []).append(f.path)
                        _diag_cache_hits += 1
                    else:
                        to_hash.append(f)
                        _diag_cache_misses += 1
            else:
                to_hash = candidates

            def emit_progress(done_count: int, stage_msg: str, current_path: str = ""):
                if not progress_cb:
                    return
                pct = 25 + int(65 * (done_count / max(1, total)))
                elapsed = max(0.001, time.time() - t0)
                rate = done_count / elapsed
                progress_cb(pct, stage_msg, {
                    "phase": "hashing",
                    "hashed": done_count,
                    "total": total,
                    "rate_fps": rate,
                    "files_scanned": len(files),
                    "current_path": current_path,
                    "current_file": current_path,
                    "elapsed_seconds": elapsed,
                })

            if progress_cb:
                emit_progress(0, f"Hashing {total:,} candidates…", "")

            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                for f, qh in ex.map(self._quick_hash_with_meta, to_hash, chunksize=64):
                    if cancelled():
                        break
                    done += 1
                    if qh:
                        hash_groups.setdefault(qh, []).append(f.path)
                        cache_writes.append((f.path, f.size, f.mtime, qh))
                    if progress_cb and (done % 256 == 0 or done == total):
                        emit_progress(done, f"Hashing… {done:,}/{total:,}", getattr(f, "path", "") or "")

            if cache and cache_writes:
                cache.set_many(cache_writes)

        finally:
            try:
                if cache:
                    cache.close()
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                pass

        if cancelled():
            return {"cancelled": True, "ok": False, "stats": {"files_scanned": len(files)}}

        _diag_hash_groups = sum(1 for paths in hash_groups.values() if len(paths) >= 2)
        _diag_hash_candidates = sum(len(paths) for paths in hash_groups.values() if len(paths) >= 2)
        logger.info(
            "[DIAG:REDUCE] after_quick_hash groups=%d candidates=%d",
            _diag_hash_groups, _diag_hash_candidates,
        )

        emit(92, "Finalizing results…", {"phase": "finalizing", "files_scanned": len(files)})

        groups = []
        for h, paths in hash_groups.items():
            if len(paths) < 2:
                continue
            groups.append({"hash": h, "size": None, "paths": paths, "count": len(paths)})

        elapsed = time.time() - start
        _diag_total_cache = _diag_cache_hits + _diag_cache_misses
        _diag_hit_pct = (_diag_cache_hits / _diag_total_cache * 100) if _diag_total_cache else 0.0
        logger.info(
            "[DIAG:SUMMARY] scan=fast_pipeline discovered=%d size_candidates=%d"
            " final_groups=%d elapsed=%.2fs cache_hits=%d cache_misses=%d cache_hit_pct=%.1f%%",
            len(files), len(candidates), len(groups), elapsed,
            _diag_cache_hits, _diag_cache_misses, _diag_hit_pct,
        )
        emit(100, f"FAST MODE done: {len(groups)} duplicate groups", {
            "phase": "completed",
            "elapsed": elapsed,
            "elapsed_seconds": elapsed,
            "groups": len(groups),
            "groups_found": len(groups),
            "files_scanned": len(files),
        })

        return {
            "ok": True,
            "groups": groups,
            "stats": {
                "files_scanned": len(files),
                "candidates": len(candidates),
                "duplicate_groups": len(groups),
                "time_seconds": elapsed,
                "max_workers": self.max_workers,
            },
        }

    def _quick_hash_with_meta(self, f: FastFileInfo) -> Tuple[FastFileInfo, Optional[str]]:
        path = f.path
        try:
            size = f.size
            sample = 1 * 1024 * 1024

            if size <= 3 * sample:
                h = hashlib.md5()
                with open(path, "rb", buffering=0) as fp:
                    while True:
                        b = fp.read(1024 * 1024)
                        if not b:
                            break
                        h.update(b)
                return f, h.hexdigest()

            h = hashlib.md5()
            with open(path, "rb", buffering=0) as fp:
                h.update(fp.read(sample))
                mid = size // 2
                fp.seek(max(0, mid - sample // 2))
                h.update(fp.read(sample))
                fp.seek(max(0, size - sample))
                h.update(fp.read(sample))
            return f, h.hexdigest()
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
            return f, None


__all__ = ["FastPipeline", "FastFileInfo"]
