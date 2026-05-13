"""Async chunked population for large Flet list/grid hosts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, TypeVar

import flet as ft

from cerebro.v2.ui.flet_app.components.common.safe_controls import safe_update as _safe_update_control

T = TypeVar("T")

MAX_RENDERED_GROUPS = 1_000

RESULTS_LIST_CHUNK_CONFIG = "results_list"
RESULTS_GRID_CHUNK_CONFIG = "results_grid"
REVIEW_GROUPS_CHUNK_CONFIG = "review_groups"
REVIEW_GRID_FILES_CHUNK_CONFIG = "review_grid_files"

_PRESETS: dict[str, "ChunkedViewConfig"] = {}


@dataclass(frozen=True)
class ChunkedViewConfig:
    async_threshold: int = 72
    first_sync_count: int = 4
    batch_size: int = 16
    max_items: int | None = MAX_RENDERED_GROUPS


def _register_presets() -> None:
    if _PRESETS:
        return
    _PRESETS[RESULTS_LIST_CHUNK_CONFIG] = ChunkedViewConfig(
        async_threshold=72,
        first_sync_count=4,
        batch_size=16,
        max_items=MAX_RENDERED_GROUPS,
    )
    _PRESETS[RESULTS_GRID_CHUNK_CONFIG] = ChunkedViewConfig(
        async_threshold=36,
        first_sync_count=4,
        batch_size=8,
        max_items=MAX_RENDERED_GROUPS,
    )
    _PRESETS[REVIEW_GROUPS_CHUNK_CONFIG] = ChunkedViewConfig(
        async_threshold=40,
        first_sync_count=40,
        batch_size=40,
        max_items=None,
    )
    _PRESETS[REVIEW_GRID_FILES_CHUNK_CONFIG] = ChunkedViewConfig(
        async_threshold=220,
        first_sync_count=20,
        batch_size=30,
        max_items=None,
    )


_register_presets()

RESULTS_LIST_CHUNK = _PRESETS[RESULTS_LIST_CHUNK_CONFIG]
RESULTS_GRID_CHUNK = _PRESETS[RESULTS_GRID_CHUNK_CONFIG]
REVIEW_GROUPS_CHUNK = _PRESETS[REVIEW_GROUPS_CHUNK_CONFIG]
REVIEW_GRID_FILES_CHUNK = _PRESETS[REVIEW_GRID_FILES_CHUNK_CONFIG]


class ChunkedViewBuilder(Generic[T]):
    """Build list/grid controls in sync and async chunks with generation guards."""

    def __init__(self, page: ft.Page, config: ChunkedViewConfig | str | None = None) -> None:
        self._page = page
        if isinstance(config, str):
            self._default_config = _PRESETS[config]
        else:
            self._default_config = config or ChunkedViewConfig()
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def bump_generation(self) -> int:
        self._generation += 1
        return self._generation

    def cap_items(
        self,
        items: Iterable[T],
        config: ChunkedViewConfig | str | None = None,
    ) -> tuple[list[T], int]:
        if isinstance(config, str):
            cfg = _PRESETS[config]
        else:
            cfg = config or self._default_config
        return self._cap_with(cfg, items)

    def render(
        self,
        host: ft.Control,
        items: Iterable[T],
        *,
        card_builder: Callable[[T, int], ft.Control],
        config: ChunkedViewConfig | str | None = None,
        trailing_builder: Callable[[int], ft.Control | None] | None = None,
        after_chunk: Callable[[], None] | None = None,
        on_complete: Callable[[], None] | None = None,
        on_abort: Callable[[], None] | None = None,
        force_sync: bool = False,
    ) -> int:
        """Populate *host.controls*; returns the active build generation."""
        if isinstance(config, str):
            cfg = _PRESETS[config]
        else:
            cfg = config or self._default_config

        gen = self.bump_generation()
        display, overflow = self._cap_with(cfg, items)
        n = len(display)

        if force_sync or n <= cfg.async_threshold:
            controls = [card_builder(item, i) for i, item in enumerate(display)]
            if overflow > 0 and trailing_builder is not None:
                banner = trailing_builder(overflow)
                if banner is not None:
                    controls.append(banner)
            host.controls = controls
            if after_chunk is not None:
                after_chunk()
            self._safe_update(host)
            if on_complete is not None:
                on_complete()
            return gen

        head_n = min(cfg.first_sync_count, n)
        head, tail = display[:head_n], display[head_n:]
        host.controls = [card_builder(item, i) for i, item in enumerate(head)]
        if after_chunk is not None:
            after_chunk()
        self._safe_update(host)

        if not tail:
            if overflow > 0 and trailing_builder is not None:
                banner = trailing_builder(overflow)
                if banner is not None:
                    host.controls.append(banner)
            if on_complete is not None:
                on_complete()
            return gen

        if hasattr(self._page, "run_task"):
            self._page.run_task(
                self._append_async,
                host,
                tail,
                gen,
                head_n,
                cfg,
                card_builder,
                trailing_builder,
                overflow,
                after_chunk,
                on_complete,
                on_abort,
            )
        else:
            self._append_sync(
                host,
                tail,
                head_n,
                card_builder,
                trailing_builder,
                overflow,
                after_chunk,
                on_complete,
            )
        return gen

    def _cap_with(self, cfg: ChunkedViewConfig, items: Iterable[T]) -> tuple[list[T], int]:
        materialized = list(items)
        max_items = cfg.max_items
        if max_items is None or len(materialized) <= max_items:
            return materialized, 0
        return materialized[:max_items], len(materialized) - max_items

    @staticmethod
    def _safe_update(ctrl: ft.Control | None) -> None:
        _safe_update_control(ctrl)

    def _append_sync(
        self,
        host: ft.Control,
        tail: list[T],
        start_idx: int,
        card_builder: Callable[[T, int], ft.Control],
        trailing_builder: Callable[[int], ft.Control | None] | None,
        overflow: int,
        after_chunk: Callable[[], None] | None,
        on_complete: Callable[[], None] | None,
    ) -> None:
        for i, item in enumerate(tail):
            host.controls.append(card_builder(item, start_idx + i))
        if overflow > 0 and trailing_builder is not None:
            banner = trailing_builder(overflow)
            if banner is not None:
                host.controls.append(banner)
        if after_chunk is not None:
            after_chunk()
        self._safe_update(host)
        if on_complete is not None:
            on_complete()

    async def _append_async(
        self,
        host: ft.Control,
        tail: list[T],
        gen: int,
        start_idx: int,
        cfg: ChunkedViewConfig,
        card_builder: Callable[[T, int], ft.Control],
        trailing_builder: Callable[[int], ft.Control | None] | None,
        overflow: int,
        after_chunk: Callable[[], None] | None,
        on_complete: Callable[[], None] | None,
        on_abort: Callable[[], None] | None,
    ) -> None:
        for i in range(0, len(tail), cfg.batch_size):
            if gen != self._generation:
                if on_abort is not None:
                    on_abort()
                return
            chunk = tail[i : i + cfg.batch_size]
            offset = start_idx + i
            host.controls.extend(
                [card_builder(item, offset + j) for j, item in enumerate(chunk)]
            )
            if after_chunk is not None:
                after_chunk()
            self._safe_update(host)
            await asyncio.sleep(0)

        if gen != self._generation:
            if on_abort is not None:
                on_abort()
            return

        if overflow > 0 and trailing_builder is not None:
            banner = trailing_builder(overflow)
            if banner is not None:
                host.controls.append(banner)
        if on_complete is not None:
            on_complete()
