"""Horizontal filmstrip for multi-file duplicate groups."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateFile
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class GroupFilmstrip(ft.Container):
    """Compact file chips for compare and group navigation."""

    def __init__(
        self,
        t: ThemeTokens,
        *,
        on_select: Callable[[DuplicateFile], None],
    ) -> None:
        self._t = t
        self._on_select = on_select
        self._row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, tight=True)
        super().__init__(
            content=self._row,
            padding=ft.Padding.symmetric(horizontal=4, vertical=4),
            visible=False,
        )

    def refresh(self, files: Iterable[DuplicateFile], *, active: Optional[DuplicateFile] = None) -> None:
        file_list: List[DuplicateFile] = list(files)
        self.visible = len(file_list) > 2
        self._row.controls.clear()
        active_path = str(active.path) if active is not None else ""
        for f in file_list:
            p = Path(str(f.path))
            selected = str(f.path) == active_path
            self._row.controls.append(
                ft.Container(
                    content=ft.Text(
                        p.name,
                        size=10,
                        color=self._t.colors.fg if selected else self._t.colors.fg_muted,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                    ),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border_radius=6,
                    bgcolor=ft.Colors.with_opacity(0.14 if selected else 0.06, self._t.colors.accent),
                    on_click=lambda _e, file=f: self._on_select(file),
                    ink=True,
                )
            )
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass
