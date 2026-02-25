# path: cerebro/core/visual_similarity.py
"""Visual similarity clustering for images (Similar Match).

- Computes a 64-bit perceptual hash (dHash or pHash)
- Generates candidates via 4x16-bit banding (LSH-ish)
- Confirms edges by Hamming distance <= threshold from matching_level
- Connected components => DuplicateGroup

This is the engine behind the Matching Level slider + Bitmap Size knob.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Protocol

from cerebro.core.models import DuplicateGroup, DuplicateItem, PipelineRequest
from cerebro.core.visual_hashing import VisualHashSettings, compute_visual_hash, hamming_distance, is_image_path


# Define CancelToken locally to avoid circular import
class CancelToken(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(slots=True)
class VisualSimilarityStats:
    images_seen: int = 0
    hashes_ok: int = 0
    groups_found: int = 0


class VisualSimilarityClustering:
    def cluster_similar(
        self,
        files: Sequence[Path],
        request: PipelineRequest,
        cancel: CancelToken,
    ) -> List[DuplicateGroup]:
        groups, _stats = self.cluster(files, request, cancel)
        return groups

    def cluster(
        self,
        files: Sequence[Path],
        request: PipelineRequest,
        cancel: CancelToken,
    ) -> Tuple[List[DuplicateGroup], VisualSimilarityStats]:
        settings = VisualHashSettings(
            bitmap_size=int(getattr(request, "bitmap_size", 64)),
            algorithm=str(getattr(request, "similarity_algorithm", "phash")),
            orientation_invariant=bool(getattr(request, "orientation_invariant", True)),
        )
        threshold = self._threshold_from_level(int(getattr(request, "matching_level", 60)))
        validation_mode = bool(getattr(request, "validation_mode", False))

        stats = VisualSimilarityStats()
        items: List[Tuple[Path, int, float, int]] = []

        for p in files:
            if cancel.is_cancelled():
                break
            if not is_image_path(p):
                continue
            stats.images_seen += 1

            try:
                st = p.stat()
            except Exception:
                continue

            hv = compute_visual_hash(p, settings)
            if hv is None:
                continue
            stats.hashes_ok += 1
            items.append((p, int(st.st_size), float(st.st_mtime), int(hv)))

        groups = self._cluster_hashes(
            items,
            algorithm=settings.algorithm,
            threshold=threshold,
            cancel=cancel,
            validation_mode=validation_mode,
        )
        stats.groups_found = len(groups)
        return groups, stats

    @staticmethod
    def _threshold_from_level(level: int) -> int:
        """0 loose .. 100 strict => [20..4] distance threshold (64-bit hashes)."""
        level = max(0, min(100, int(level)))
        loose, strict = 20, 4
        return int(round(loose - (level / 100.0) * (loose - strict)))

    def _cluster_hashes(
        self,
        items: List[Tuple[Path, int, float, int]],
        *,
        algorithm: str,
        threshold: int,
        cancel: CancelToken,
        validation_mode: bool,
    ) -> List[DuplicateGroup]:
        if len(items) < 2:
            return []

        if validation_mode:
            items = sorted(items, key=lambda t: str(t[0]))

        hashes = [hv for *_rest, hv in items]
        n = len(items)

        parent = list(range(n))
        rank = [0] * n

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            if rank[ra] < rank[rb]:
                parent[ra] = rb
            elif rank[ra] > rank[rb]:
                parent[rb] = ra
            else:
                parent[rb] = ra
                rank[ra] += 1

        # Candidate buckets: 4 bands of 16 bits from the 64-bit hash.
        buckets: Dict[Tuple[int, int], List[int]] = {}
        for i, hv in enumerate(hashes):
            for band in range(4):
                buckets.setdefault((band, (hv >> (band * 16)) & 0xFFFF), []).append(i)

        seen_pairs: set[Tuple[int, int]] = set()
        for idxs in buckets.values():
            if cancel.is_cancelled():
                break
            if len(idxs) < 2:
                continue
            for a_i in range(len(idxs)):
                for b_i in range(a_i + 1, len(idxs)):
                    a, b = idxs[a_i], idxs[b_i]
                    pair = (a, b) if a < b else (b, a)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    if hamming_distance(hashes[a], hashes[b]) <= threshold:
                        union(a, b)

        comps: Dict[int, List[int]] = {}
        for i in range(n):
            comps.setdefault(find(i), []).append(i)

        groups: List[DuplicateGroup] = []
        for members in comps.values():
            if len(members) < 2:
                continue
            members_sorted = sorted(members, key=lambda i: str(items[i][0]))
            gid = self._make_group_id([str(items[i][0]) for i in members_sorted], threshold=threshold, algorithm=algorithm)

            g = DuplicateGroup(group_id=gid)
            for i in members_sorted:
                p, size, mtime, hv = items[i]
                g.items.append(
                    DuplicateItem(
                        path=p,
                        size=size,
                        mtime=mtime,
                        extras={
                            "visual_hash": f"{hv:016x}",
                            "hash_alg": algorithm,
                            "threshold": threshold,
                        },
                    )
                )
            groups.append(g)

        if validation_mode:
            groups.sort(key=lambda gg: (str(gg.group_id), [str(i.path) for i in gg.items]))

        return groups

    @staticmethod
    def _make_group_id(paths: List[str], *, threshold: int, algorithm: str) -> str:
        blob = f"{algorithm}|{threshold}|" + "|".join(sorted(paths))
        h = hashlib.sha1(blob.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"sim_{h}"