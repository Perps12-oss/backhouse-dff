from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReviewMode = Literal["empty", "loading", "groups", "grid", "compare"]


@dataclass(frozen=True)
class ReviewColors:
    side_a:       str = "#22D3EE"
    side_b:       str = "#A78BFA"
    danger:       str = "#EF4444"
    success:      str = "#4ADE80"
    info:         str = "#93C5FD"
    muted_text:   str = "#9FB0D0"
    tile_bg:      str = "#0A0E14"
    group_stripe: tuple = ("#22D3EE", "#A78BFA", "#F472B6", "#34D399", "#FBBF24")


RC = ReviewColors()
