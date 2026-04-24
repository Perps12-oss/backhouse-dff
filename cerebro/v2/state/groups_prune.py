"""Update in-memory duplicate groups when files are removed (delete / move)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Set

from cerebro.engines.base_engine import DuplicateGroup


def _path_set(paths: Iterable[str]) -> Set[str]:
    return {str(Path(p)) for p in paths}


def prune_paths_from_groups(
    groups: List[DuplicateGroup],
    paths: Iterable[str],
) -> List[DuplicateGroup]:
    """
    Remove each path from its group. Groups with fewer than two files are dropped
    (no longer duplicates). Rebuilds each retained :class:`DuplicateGroup` so
    ``total_size`` / ``reclaimable`` match ``__post_init__`` rules.
    """
    rset = _path_set(paths)
    if not rset:
        return list(groups)
    out: List[DuplicateGroup] = []
    for g in groups:
        new_files = [f for f in g.files if str(f.path) not in rset]
        if len(new_files) < 2:
            continue
        out.append(
            DuplicateGroup(
                group_id=g.group_id,
                files=new_files,
                similarity_type=g.similarity_type,
            )
        )
    return out
