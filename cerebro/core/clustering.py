"""
core/clustering.py — CEREBRO Duplicate Group Clustering

Responsibilities:
- Convert hash buckets into DuplicateGroup domain objects
- Assign stable group IDs
- No decisions (no survivor selection)
- Validation-safe deterministic ordering

This is the boundary where raw data becomes domain meaning.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from cerebro.core.pipeline import PipelineRequest


# ---------------------------------------------------------------------
# 00. DOMAIN MODEL
# ---------------------------------------------------------------------

@dataclass
class DuplicateItem:
    path: Path
    size_bytes: int
    hash: str


@dataclass
class DuplicateGroup:
    """
    Domain object consumed by ReviewPage and decision engine.
    """
    group_id: str
    items: List[DuplicateItem] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)


# ---------------------------------------------------------------------
# 01. CLUSTERING IMPLEMENTATION
# ---------------------------------------------------------------------

class HashClustering:
    """
    Concrete implementation of ClusteringPort.
    """

    def to_groups(
        self,
        hash_groups: Dict[str, List[Path]],
        request: PipelineRequest,
        cancel: CancelToken,
    ) -> List[DuplicateGroup]:
        groups: List[DuplicateGroup] = []

        # Deterministic ordering
        items_iter = hash_groups.items()
        if request.validation_mode:
            items_iter = sorted(items_iter, key=lambda kv: kv[0])

        for digest, paths in items_iter:
            if cancel.is_cancelled():
                return []

            # Defensive: skip invalid buckets
            if len(paths) < 2:
                continue

            group_id = self._make_group_id(digest, paths)

            items: List[DuplicateItem] = []
            for p in paths:
                try:
                    size = p.stat().st_size
                except Exception:
                    size = 0

                items.append(
                    DuplicateItem(
                        path=p,
                        size_bytes=size,
                        hash=digest,
                    )
                )

            # Stable ordering inside group
            if request.validation_mode:
                items.sort(key=lambda it: str(it.path))

            groups.append(DuplicateGroup(group_id=group_id, items=items))

        return groups

    # -----------------------------------------------------------------
    # 02. GROUP ID
    # -----------------------------------------------------------------

    def _make_group_id(self, digest: str, paths: List[Path]) -> str:
        """
        Generates a stable, human-debuggable group ID.
        """
        h = hashlib.sha1()
        h.update(digest.encode("utf-8"))
        for p in paths[:3]:  # sample a few paths for entropy
            h.update(str(p).encode("utf-8"))
        return h.hexdigest()[:12]
