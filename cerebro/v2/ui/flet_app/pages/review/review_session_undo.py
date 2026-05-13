"""In-memory undo stack for batch review mark/keep decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Set


@dataclass(frozen=True)
class ReviewUndoFrame:
    marked_paths: frozenset[str]
    reviewed_group_ids: frozenset[int]
    ignored_group_ids: frozenset[int]
    override_paths: frozenset[str]


class ReviewSessionUndo:
    def __init__(self) -> None:
        self._stack: list[ReviewUndoFrame] = []

    def clear(self) -> None:
        self._stack.clear()

    def record(
        self,
        *,
        marked_paths: Set[str],
        reviewed_group_ids: Set[int],
        ignored_group_ids: Set[int],
        override_paths: Set[str],
    ) -> None:
        self._stack.append(
            ReviewUndoFrame(
                marked_paths=frozenset(marked_paths),
                reviewed_group_ids=frozenset(reviewed_group_ids),
                ignored_group_ids=frozenset(ignored_group_ids),
                override_paths=frozenset(override_paths),
            )
        )

    def pop(self) -> ReviewUndoFrame | None:
        if not self._stack:
            return None
        return self._stack.pop()
