"""Batched thumbnail decode and slot updates for grid/list hosts."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Callable, Iterable

import flet as ft

from cerebro.v2.ui.flet_app.components.common.safe_controls import safe_update as _safe_update_control
from cerebro.v2.ui.flet_app.services.thumbnail_cache import get_thumbnail_cache


class ThumbnailSlotLoader:
    """Stream decoded thumbnails into Flet slot containers in bounded UI batches."""

    def __init__(self, *, safe_update: Callable[[ft.Control | None], None] | None = None) -> None:
        self._safe_update = safe_update or _safe_update_control

    async def load_into_slots(
        self,
        *,
        slot_for_path: Callable[[Path], ft.Container | None],
        paths: Iterable[Path],
        image_for_b64: Callable[[str], ft.Control],
        is_current: Callable[[], bool],
        batch_size: int = 8,
        hosts: Iterable[ft.Control] = (),
        max_edge: int | None = None,
        log_slow: Callable[[str, float], None] | None = None,
        slow_label: str = "thumbnail_batch_apply",
        slow_ms: float = 80.0,
    ) -> None:
        pending: list[tuple[ft.Container, str]] = []

        async def _on_ready(path: Path, b64: str | None) -> None:
            if not is_current():
                return
            if not b64:
                return
            slot = slot_for_path(path)
            if slot is None:
                return
            pending.append((slot, b64))
            if len(pending) >= batch_size:
                await self._flush(
                    pending,
                    image_for_b64=image_for_b64,
                    is_current=is_current,
                    hosts=hosts,
                    log_slow=log_slow,
                    slow_label=slow_label,
                    slow_ms=slow_ms,
                )

        path_list = list(paths)
        if max_edge is None:
            await get_thumbnail_cache().load_batch_async(path_list, _on_ready)
        else:
            await get_thumbnail_cache().load_batch_async(path_list, _on_ready, max_edge=max_edge)

        if is_current() and pending:
            await self._flush(
                pending,
                image_for_b64=image_for_b64,
                is_current=is_current,
                hosts=hosts,
                log_slow=log_slow,
                slow_label=slow_label,
                slow_ms=slow_ms,
            )

    async def _flush(
        self,
        pending: list[tuple[ft.Container, str]],
        *,
        image_for_b64: Callable[[str], ft.Control],
        is_current: Callable[[], bool],
        hosts: Iterable[ft.Control],
        log_slow: Callable[[str, float], None] | None,
        slow_label: str,
        slow_ms: float,
    ) -> None:
        if not is_current():
            pending.clear()
            return
        started = time.perf_counter()
        for slot, b64 in pending:
            slot.content = image_for_b64(b64)
        pending.clear()
        for host in hosts:
            self._safe_update(host)
        if log_slow is not None:
            log_slow(slow_label, started)
        await asyncio.sleep(0)
