"""Simple review mode: summary-first overview (delete N files, rule, provenance)."""

from __future__ import annotations

from typing import Any, Callable, List, Optional

import flet as ft

from cerebro.engines.base_engine import DuplicateGroup
from cerebro.v2.ui.flet_app.pages.review_flow.selection_contract import (
    delete_preparation_allowed,
    format_scope_change_hint,
    provenance_label,
    selection_controls_frozen,
)
from cerebro.v2.ui.flet_app.pages.review_flow.smart_rules import RULE_LABELS, RULE_TOOLTIPS
from cerebro.v2.ui.flet_app.pages.review_flow.state import ReviewFlowState
from cerebro.v2.ui.flet_app.flet_compat import dropdown_handler_kwargs
from cerebro.v2.ui.flet_app.pill_button_styles import pill_filled_critical, pill_outlined_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size


def _metrics_from_groups(groups: List[DuplicateGroup]) -> dict[str, int]:
    file_count = sum(len(g.files) for g in groups)
    reclaimable = sum(int(getattr(g, "reclaimable", 0) or 0) for g in groups)
    return {"set_count": len(groups), "file_count": file_count, "reclaimable_bytes": reclaimable}


class SimpleSummaryView:
    """Mutable simple-review summary panel; call ``refresh`` after state changes."""

    def __init__(
        self,
        t: ThemeTokens,
        state: ReviewFlowState,
        *,
        default_rule: str,
        on_delete: Callable[[Any], None],
        on_review_details: Callable[[Any], None],
        on_apply_rule: Callable[[str], None],
        on_rule_changed: Callable[[str], None],
        on_dismiss_helper: Callable[[], None],
        show_helper: bool,
        scan_elapsed_seconds: Optional[float] = None,
    ) -> None:
        self._t = t
        self._state = state
        self._default_rule = default_rule
        self._on_delete = on_delete
        self._on_review_details = on_review_details
        self._on_apply_rule = on_apply_rule
        self._on_rule_changed = on_rule_changed
        self._on_dismiss_helper = on_dismiss_helper
        self._show_helper = show_helper
        self._scan_elapsed_seconds = scan_elapsed_seconds

        self._hero = ft.Text("", size=t.typography.size_xxl, weight=ft.FontWeight.W_700, color=t.colors.fg)
        self._sub = ft.Text("", size=t.typography.size_md, color=t.colors.fg_muted)
        self._stats = ft.Text("", size=t.typography.size_sm, color=t.colors.fg_muted)
        self._provenance = ft.Text("", size=t.typography.size_sm, color=t.colors.fg2, italic=True)
        self._invalid_hint = ft.Text("", size=t.typography.size_sm, color=t.colors.fg_muted)
        self._invalid_banner = ft.Container(visible=False, padding=16, border_radius=12)
        self._recompute_label = ft.Text("Updating selection…", size=t.typography.size_sm, color=t.colors.fg_muted)
        self._recompute_row = ft.Container(visible=False)
        self._rule_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(key=k, text=lbl) for k, lbl in RULE_LABELS],
            value=default_rule,
            width=220,
            **dropdown_handler_kwargs(self._on_rule_dropdown_change),
        )
        self._apply_rule_btn = ft.OutlinedButton(
            "Apply rule",
            style=pill_outlined_button_style(t),
            on_click=self._on_apply_rule_click,
        )
        self._delete_btn = ft.FilledButton(
            "Delete marked files",
            style=pill_filled_critical(t),
            on_click=on_delete,
        )
        self._details_btn = ft.OutlinedButton(
            "Review details",
            style=pill_outlined_button_style(t),
            on_click=on_review_details,
        )
        self._helper = self._build_helper()

        self.root = ft.Container(
            expand=True,
            alignment=ft.Alignment(0, -1),
            padding=ft.padding.symmetric(horizontal=24, vertical=32),
            content=ft.Column(
                [
                    self._invalid_banner,
                    ft.Icon(ft.icons.Icons.INVENTORY_2_OUTLINED, size=48, color=t.colors.accent),
                    self._hero,
                    self._sub,
                    self._stats,
                    ft.Container(height=8),
                    ft.Row(
                        [
                            ft.Text("Keeper rule", size=t.typography.size_sm, color=t.colors.fg_muted),
                            self._rule_dropdown,
                        ],
                        spacing=12,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    self._recompute_row,
                    self._provenance,
                    ft.Container(height=16),
                    self._delete_btn,
                    self._details_btn,
                    self._helper,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
        )
        self.refresh()

    def _build_helper(self) -> ft.Container:
        t = self._t
        return ft.Container(
            visible=self._show_helper,
            padding=12,
            border_radius=8,
            bgcolor=ft.Colors.with_opacity(0.06, t.colors.fg_muted),
            content=ft.Row(
                [
                    ft.Icon(ft.icons.Icons.INFO_OUTLINE, size=18, color=t.colors.fg_muted),
                    ft.Text(
                        "You can inspect every decision before deleting — open Review details.",
                        size=t.typography.size_sm,
                        color=t.colors.fg_muted,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.icons.Icons.CLOSE,
                        icon_size=16,
                        on_click=lambda _e: self._on_dismiss_helper(),
                    ),
                ],
                spacing=8,
            ),
        )

    def apply_theme(self, t: ThemeTokens) -> None:
        self._t = t
        self._hero.color = t.colors.fg
        self._sub.color = t.colors.fg_muted
        self._stats.color = t.colors.fg_muted
        self._provenance.color = t.colors.fg2
        self._delete_btn.style = pill_filled_critical(t)
        self._details_btn.style = pill_outlined_button_style(t)
        self._apply_rule_btn.style = pill_outlined_button_style(t)
        self.refresh()

    def set_scan_elapsed(self, seconds: Optional[float]) -> None:
        self._scan_elapsed_seconds = seconds

    def set_helper_visible(self, visible: bool) -> None:
        self._show_helper = visible
        self._helper.visible = visible

    def _on_rule_dropdown_change(self, e: ft.ControlEvent) -> None:
        self._on_rule_changed(str(e.control.value or self._default_rule))

    def _on_apply_rule_click(self, _e: ft.ControlEvent) -> None:
        self._on_apply_rule(str(self._rule_dropdown.value or self._default_rule))

    def refresh(self) -> None:
        t = self._t
        state = self._state
        groups = state.scan_results
        metrics = _metrics_from_groups(groups)
        n_del = state.displayed_cart_delete_count
        bytes_del = state.displayed_cart_delete_bytes
        frozen = selection_controls_frozen(state)
        invalidated = state.selection_validity == "invalidated_scope"
        recompute = state.selection_transaction_state == "recomputing"
        can_delete = delete_preparation_allowed(state) and not frozen

        self._helper.visible = self._show_helper and bool(groups)

        if not groups:
            self._hero.value = "No duplicate sets loaded"
            self._sub.value = "Run a scan from the dashboard, then open Review."
            self._stats.value = ""
            self._provenance.value = ""
            self._delete_btn.disabled = True
            self._details_btn.disabled = True
            self._rule_dropdown.disabled = True
            self._apply_rule_btn.disabled = True
            self._invalid_banner.visible = False
            self._recompute_row.visible = False
            return

        self._rule_dropdown.disabled = frozen
        self._apply_rule_btn.disabled = frozen or recompute
        self._details_btn.disabled = False

        if n_del > 0:
            self._hero.value = f"Remove {n_del:,} file{'s' if n_del != 1 else ''} ({fmt_size(int(bytes_del))})"
        else:
            self._hero.value = "No files marked for removal"
        self._sub.value = (
            f"{metrics['set_count']:,} duplicate set{'s' if metrics['set_count'] != 1 else ''} · "
            f"{fmt_size(int(metrics['reclaimable_bytes']))} recoverable"
        )
        stats_parts = [f"{metrics['file_count']:,} files in groups"]
        elapsed = self._scan_elapsed_seconds
        if elapsed is not None and elapsed > 0:
            stats_parts.append(f"scan {elapsed:.0f}s")
        self._stats.value = " · ".join(stats_parts)

        rule = str(state.selection_rule or self._rule_dropdown.value or self._default_rule)
        if rule in dict(RULE_LABELS):
            self._rule_dropdown.value = rule
        self._rule_dropdown.tooltip = RULE_TOOLTIPS.get(rule) or None
        self._provenance.value = provenance_label(state)

        if invalidated and state.mark_snapshot is not None:
            self._invalid_hint.value = (
                f"{format_scope_change_hint(state.mark_snapshot, state)}. "
                "Apply your keeper rule to refresh marks for the current scope."
            )
            self._invalid_banner.visible = True
            self._invalid_banner.bgcolor = ft.Colors.with_opacity(0.1, t.colors.warning)
            self._invalid_banner.border = ft.border.all(1, ft.Colors.with_opacity(0.35, t.colors.warning))
            self._invalid_banner.content = ft.Column(
                [
                    ft.Text("Selection needs updating", weight=ft.FontWeight.W_600, color=t.colors.fg),
                    self._invalid_hint,
                    ft.Row([self._apply_rule_btn], alignment=ft.MainAxisAlignment.CENTER),
                ],
                spacing=8,
                tight=True,
            )
        else:
            self._invalid_banner.visible = False

        if recompute:
            self._recompute_row.visible = True
            self._recompute_row.content = ft.Row(
                [ft.ProgressRing(width=18, height=18, stroke_width=2), self._recompute_label],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
            )
        elif not invalidated:
            self._recompute_row.visible = True
            self._recompute_row.content = ft.Row(
                [self._apply_rule_btn],
                alignment=ft.MainAxisAlignment.CENTER,
            )
        else:
            self._recompute_row.visible = False

        self._delete_btn.disabled = not can_delete
        self._delete_btn.text = (
            f"Delete {n_del:,} file{'s' if n_del != 1 else ''}" if n_del > 0 else "Delete marked files"
        )
