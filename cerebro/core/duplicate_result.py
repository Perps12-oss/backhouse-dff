"""UI-agnostic duplicate result model used by integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DuplicateResult:
    group_id: int
    files: list[dict[str, Any]] = field(default_factory=list)
    total_size: int = 0
    reclaimable: int = 0

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def checked_count(self) -> int:
        return sum(1 for f in self.files if bool(f.get("checked")))

    @property
    def reclaimable_human(self) -> str:
        value = float(self.reclaimable)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"
