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

import os
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

from cerebro.core.pipeline import CancelToken, PipelineRequest
from cerebro.services.logger import get_logger

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
            except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError, ImportError):
                continue

            # request.min_size_bytes handled in discovery already, but re-check is harmless
            if size < request.min_size_bytes:
                continue

            buckets[int(size)].append(p)

        _diag_total_in = sum(len(v) for v in buckets.values())
        logger.info("[DIAG:DISCOVERY] grouping input files_in=%d", _diag_total_in)

        # Remove singletons
        buckets = {sz: lst for sz, lst in buckets.items() if len(lst) >= 2}

        _diag_candidates = sum(len(v) for v in buckets.values())
        logger.info(
            "[DIAG:REDUCE] after_size_group size_groups=%d candidates=%d",
            len(buckets), _diag_candidates,
        )
        for _diag_sz, _diag_grp in buckets.items():
            _diag_cap = min(len(_diag_grp), 8)
            for _diag_i in range(_diag_cap):
                for _diag_j in range(_diag_i + 1, _diag_cap):
                    _diagnose_pair(str(_diag_grp[_diag_i]), str(_diag_grp[_diag_j]), _diag_sz)

        # Deterministic ordering for validation mode
        if request.validation_mode:
            # stable ordering: by string path, within each bucket
            for sz in list(buckets.keys()):
                buckets[sz] = sorted(buckets[sz], key=lambda x: str(x))
            # also stable ordering of keys (not required for dict, but helpful for debugging)
            buckets = dict(sorted(buckets.items(), key=lambda kv: kv[0]))

        logger.info(
            "[DIAG:SUMMARY] scan=size_grouping files_in=%d size_groups=%d candidates=%d",
            _diag_total_in, len(buckets), _diag_candidates,
        )
        return buckets
