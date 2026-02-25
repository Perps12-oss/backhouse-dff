"""
core/grouping.py — CEREBRO Size Grouping Stage

Purpose:
- Bucket candidate files by size
- Eliminate singletons (cannot be duplicates)
- Deterministic ordering in validation mode
- Cancellation-aware

This stage should be cheap and aggressive: the goal is to shrink workload
before hashing begins.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

from cerebro.core.pipeline import CancelToken, PipelineRequest


class SizeGrouping:
    """
    Concrete implementation of GroupingPort.

    Contract:
      group_by_size(files) -> {size_bytes: [paths...]} only for sizes with >= 2 members.
    """

    def group_by_size(
        self,
        files: Iterable[Path],
        request: PipelineRequest,
        cancel: CancelToken,
    ) -> Dict[int, List[Path]]:
        buckets: Dict[int, List[Path]] = defaultdict(list)

        for p in files:
            if cancel.is_cancelled():
                return {}

            try:
                size = p.stat().st_size
            except Exception:
                continue

            # request.min_size_bytes handled in discovery already, but re-check is harmless
            if size < request.min_size_bytes:
                continue

            buckets[int(size)].append(p)

        # Remove singletons
        buckets = {sz: lst for sz, lst in buckets.items() if len(lst) >= 2}

        # Deterministic ordering for validation mode
        if request.validation_mode:
            # stable ordering: by string path, within each bucket
            for sz in list(buckets.keys()):
                buckets[sz] = sorted(buckets[sz], key=lambda x: str(x))
            # also stable ordering of keys (not required for dict, but helpful for debugging)
            buckets = dict(sorted(buckets.items(), key=lambda kv: kv[0]))

        return buckets
