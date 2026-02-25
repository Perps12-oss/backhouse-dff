"""
core/hashing.py — CEREBRO Hashing Engine

Responsibilities:
- Convert size buckets → hash buckets
- Partial hash first (cheap pruning)
- Optional full hash (authoritative)
- Cancellation-aware
- Deterministic ordering in validation mode

Non-goals:
- No grouping decisions
- No survivor logic
- No filesystem mutation
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List

from cerebro.core.pipeline import CancelToken, PipelineRequest


# ---------------------------------------------------------------------
# 00. HASH UTILITIES
# ---------------------------------------------------------------------

def _hash_file_segment(path: Path, *, bytes_to_read: int | None = None) -> str:
    """
    Hashes either:
      - first N bytes (partial hash)
      - entire file (full hash)
    """
    h = hashlib.sha256()

    with path.open("rb") as f:
        if bytes_to_read is None:
            # full file
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        else:
            data = f.read(bytes_to_read)
            h.update(data)

    return h.hexdigest()


# ---------------------------------------------------------------------
# 01. HASHING IMPLEMENTATION
# ---------------------------------------------------------------------

class FileHashing:
    """
    Concrete implementation of HashingPort.
    """

    # -----------------------------
    # PARTIAL HASH
    # -----------------------------

    def partial_hash(
        self,
        size_groups: Dict[int, List[Path]],
        request: PipelineRequest,
        cancel: CancelToken,
    ) -> Dict[str, List[Path]]:
        """
        Buckets files by partial hash.
        Only buckets with >= 2 files survive.
        """
        return self._hash_groups(
            size_groups=size_groups,
            request=request,
            cancel=cancel,
            bytes_to_read=request.partial_hash_bytes,
            stage="partial",
        )

    # -----------------------------
    # FULL HASH
    # -----------------------------

    def full_hash(
        self,
        partial_groups: Dict[str, List[Path]],
        request: PipelineRequest,
        cancel: CancelToken,
    ) -> Dict[str, List[Path]]:
        """
        Buckets files by full hash.
        Only buckets with >= 2 files survive.
        """
        # Re-shape input: hash -> paths  → fake size groups
        fake_size_groups = {
            idx: paths for idx, paths in enumerate(partial_groups.values())
        }

        return self._hash_groups(
            size_groups=fake_size_groups,
            request=request,
            cancel=cancel,
            bytes_to_read=None,
            stage="full",
        )

    # -----------------------------------------------------------------
    # 02. CORE HASH ROUTINE
    # -----------------------------------------------------------------

    def _hash_groups(
        self,
        *,
        size_groups: Dict[int, List[Path]],
        request: PipelineRequest,
        cancel: CancelToken,
        bytes_to_read: int | None,
        stage: str,
    ) -> Dict[str, List[Path]]:
        """
        Shared hashing logic.
        """

        max_workers = request.max_workers or min(32, (os.cpu_count() or 4))
        hash_buckets: Dict[str, List[Path]] = {}

        # Deterministic ordering for validation
        groups_iter = size_groups.values()
        if request.validation_mode:
            groups_iter = [
                sorted(group, key=lambda p: str(p))
                for group in groups_iter
            ]

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []

            for group in groups_iter:
                if cancel.is_cancelled():
                    return {}

                # Skip groups already singleton (defensive)
                if len(group) < 2:
                    continue

                for path in group:
                    futures.append(
                        executor.submit(
                            self._safe_hash,
                            path,
                            bytes_to_read,
                        )
                    )

            for future in as_completed(futures):
                if cancel.is_cancelled():
                    return {}

                result = future.result()
                if result is None:
                    continue

                path, digest = result
                hash_buckets.setdefault(digest, []).append(path)

        # Eliminate singletons
        hash_buckets = {
            h: paths for h, paths in hash_buckets.items()
            if len(paths) >= 2
        }

        # Deterministic ordering
        if request.validation_mode:
            for h in list(hash_buckets.keys()):
                hash_buckets[h] = sorted(hash_buckets[h], key=lambda p: str(p))
            hash_buckets = dict(sorted(hash_buckets.items(), key=lambda kv: kv[0]))

        return hash_buckets

    # -----------------------------------------------------------------
    # 03. SAFE HASH WRAPPER
    # -----------------------------------------------------------------

    def _safe_hash(
        self,
        path: Path,
        bytes_to_read: int | None,
    ) -> tuple[Path, str] | None:
        try:
            digest = _hash_file_segment(path, bytes_to_read=bytes_to_read)
            return path, digest
        except Exception:
            # Corrupt / unreadable file — silently drop
            return None
