"""Apply sheet — simple mode empty outcome layout."""

from __future__ import annotations

import flet as ft

from cerebro.v2.ui.flet_app.pages.review_flow.apply_sheet import ApplyOutcomeModel, build_apply_sheet_column
from cerebro.v2.ui.flet_app.theme import theme_for_mode


def test_simple_empty_outcome_layout() -> None:
    t = theme_for_mode("light")
    outcome = ApplyOutcomeModel(deleted_count=2, freed_bytes=100, error_count=0)
    col = build_apply_sheet_column(
        t,
        step="outcome",
        delete_count=0,
        freed_bytes=0,
        protected_count=0,
        confirm_checkbox=ft.Checkbox(),
        progress_bar=ft.ProgressBar(),
        progress_label=ft.Text(),
        outcome=outcome,
        reduce_motion=False,
        on_close=lambda _e: None,
        on_continue_summary=lambda _e: None,
        on_back_confirm=lambda _e: None,
        on_apply=lambda _e: None,
        on_restore_managed=lambda _e: None,
        on_back_overview=lambda _e: None,
        on_new_scan=lambda _e: None,
        outcome_return_label="",
        outcome_show_return=False,
        simple_empty_outcome=True,
    )
    texts = [c for c in col.controls if isinstance(c, ft.Text)]
    joined = " ".join(str(x.value) for x in texts if getattr(x, "value", None))
    assert "No duplicate sets" in joined
