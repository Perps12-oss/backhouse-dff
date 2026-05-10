"""Narrow delegate for ``ReviewCompareView`` — no direct ``ReviewPage`` private reach-ins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Protocol, Set

import flet as ft

from cerebro.engines.base_engine import DuplicateFile, DuplicateGroup

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.pages.review_page import ReviewPage


class ReviewCompareDelegate(Protocol):
    """Callbacks and read-only state used by compare UI."""

    def get_glass_style(self, opacity: float = 0.06) -> dict: ...

    def delete_marked_files(self, e: ft.ControlEvent | None = None) -> None: ...
    def to_grid(self, e: ft.ControlEvent | None = None) -> None: ...
    def prev_group(self, e: ft.ControlEvent | None = None) -> None: ...
    def next_group(self, e: ft.ControlEvent | None = None) -> None: ...
    def enter_compare(self, gid: int) -> None: ...
    def toggle_mark_file(self, file: DuplicateFile) -> None: ...

    @property
    def groups(self) -> List[DuplicateGroup]: ...

    @property
    def compare_gid(self) -> Optional[int]: ...

    @property
    def group_files(self) -> Dict[int, List[DuplicateFile]]: ...

    @property
    def compare_a(self) -> Optional[DuplicateFile]: ...

    @property
    def compare_b(self) -> Optional[DuplicateFile]: ...

    @property
    def reviewed_group_ids(self) -> Set[int]: ...

    @property
    def marked_bytes(self) -> int: ...

    @property
    def marked_paths(self) -> Set[str]: ...

    @property
    def mode(self) -> str: ...


class ReviewCompareDelegateAdapter:
    """Thin adapter from ``ReviewPage`` to ``ReviewCompareDelegate``."""

    __slots__ = ("_page",)

    def __init__(self, page: ReviewPage) -> None:
        self._page = page

    def get_glass_style(self, opacity: float = 0.06) -> dict:
        return self._page._get_glass_style(opacity)

    def delete_marked_files(self, e: ft.ControlEvent | None = None) -> None:
        self._page._delete_marked_files(e)

    def to_grid(self, e: ft.ControlEvent | None = None) -> None:
        self._page._to_grid(e)

    def prev_group(self, e: ft.ControlEvent | None = None) -> None:
        self._page._prev_group(e)

    def next_group(self, e: ft.ControlEvent | None = None) -> None:
        self._page._next_group(e)

    def enter_compare(self, gid: int) -> None:
        self._page._enter_compare(gid)

    def toggle_mark_file(self, file: DuplicateFile) -> None:
        self._page._toggle_mark_file(file)

    @property
    def groups(self) -> List[DuplicateGroup]:
        return self._page._groups

    @property
    def compare_gid(self) -> Optional[int]:
        return self._page._compare_gid

    @property
    def group_files(self) -> Dict[int, List[DuplicateFile]]:
        return self._page._group_files

    @property
    def compare_a(self) -> Optional[DuplicateFile]:
        return self._page._compare_a

    @property
    def compare_b(self) -> Optional[DuplicateFile]:
        return self._page._compare_b

    @property
    def reviewed_group_ids(self) -> Set[int]:
        return self._page._reviewed_group_ids

    @property
    def marked_bytes(self) -> int:
        return self._page._marked_bytes

    @property
    def marked_paths(self) -> Set[str]:
        return self._page._marked_paths

    @property
    def mode(self) -> str:
        return self._page._mode
