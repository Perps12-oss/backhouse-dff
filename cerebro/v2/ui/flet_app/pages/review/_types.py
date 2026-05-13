from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal

from cerebro.v2.ui.flet_app.components.filters.filter_bar import FILTER_TAB_ACCENTS

ReviewMode = Literal["empty", "loading", "groups", "grid", "compare"]


@dataclass(frozen=True)
class ReviewColors:
    side_a: str = "#22D3EE"
    side_b: str = "#A78BFA"
    danger: str = "#EF4444"
    success: str = "#4ADE80"
    info: str = "#93C5FD"
    muted_text: str = "#9FB0D0"
    tile_bg: str = "#0A0E14"
    group_stripe: tuple = ("#22D3EE", "#A78BFA", "#F472B6", "#34D399", "#FBBF24")
    marked_label_soft: str = "#FCA5A5"
    marked_bar_bg: str = "#1A0C0C"
    meta_date_blue: str = "#BFD5FF"
    meta_dims_purple: str = "#C084FC"
    grid_badge_text: str = "#9FDDF7"
    grid_badge_bg: str = "#09111D"
    tile_name_on_thumb: str = "#FFFFFF"
    stats_chip_files: str = "#7DD3FC"
    stats_chip_reviewed: str = "#FBBF24"
    stats_chip_remaining: str = "#F87171"
    group_title_reviewed: str = "#A7F3D0"
    filter_all: str = "#C7D2FE"
    filter_pictures: str = "#C084FC"
    filter_music: str = "#34D399"
    filter_videos: str = "#F472B6"
    filter_documents: str = "#FB923C"
    filter_archives: str = "#FBBF24"


RC = ReviewColors()
