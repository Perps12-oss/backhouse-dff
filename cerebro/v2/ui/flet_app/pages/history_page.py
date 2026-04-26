"""History page — scan and deletion history with glass tabs and data table."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import flet as ft

from cerebro.v2.ui.flet_app.theme import fmt_size as _fmt, theme_for_mode

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class HistoryPage(ft.Column):
    """Scan and deletion history with tabbed interface."""

    def __init__(self, bridge: "StateBridge"):
        super().__init__(expand=True, scroll=ft.ScrollMode.AUTO)
        self._bridge = bridge
        self._t = theme_for_mode("dark")
        self._scan_rows: list = []
        self._deletion_rows: list = []
        self._active_tab = "scan"
        self._glass_cache: dict = {}
        
        # UI References
        self._header: ft.Container
        self._recent_strip: ft.Column
        self._recent_strip_container: ft.Container
        self._mode_switch: ft.SegmentedButton
        self._clear_btn: ft.OutlinedButton
        self._action_bar: ft.Row
        self._table: ft.DataTable
        self._empty_label: ft.Text
        self._empty_container: ft.Container
        self._data_container: ft.Column # Wrapper for table/empty
        
        self._build_ui()

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    # ------------------------------------------------------------------
    # Glass helper
    # ------------------------------------------------------------------
    def _get_glass_style(self, opacity: float = 0.06) -> dict:
        is_light = "light" in self._bridge.app_theme.lower() if hasattr(self._bridge, 'app_theme') else False
        cache_key = (opacity, is_light)
        if cache_key in self._glass_cache:
            return self._glass_cache[cache_key]
        bg_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        border_base = ft.Colors.BLACK if is_light else ft.Colors.WHITE
        bg = ft.Colors.with_opacity(opacity, bg_base)
        border_color = ft.Colors.with_opacity(0.12, border_base)
        result = dict(
            bgcolor=bg,
            border=ft.border.all(1, border_color),
            border_radius=ft.border_radius.all(12),
        )
        self._glass_cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # Build (Runs Once)
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        t = self._t

        # Header
        self._header = ft.Container(
            content=ft.Text("History", size=t.typography.size_xl, weight=ft.FontWeight.BOLD, color=t.colors.fg),
            padding=ft.padding.only(left=t.spacing.lg, top=t.spacing.lg),
        )

        # Recent scans strip
        self._recent_strip = ft.Column([], spacing=4, visible=False)
        self._recent_strip_container = ft.Container(
            content=ft.Column([
                ft.Text("Recent", size=t.typography.size_sm, weight=ft.FontWeight.W_600, color=t.colors.fg_muted),
                self._recent_strip,
            ], spacing=4),
            padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, bottom=t.spacing.sm),
            visible=False,
        )

        # Scan vs deletion (Flet 0.25+ uses TabBar+TabBarView inside Tabs; SegmentedButton fits one shared table)
        self._mode_switch = ft.SegmentedButton(
            segments=[
                ft.Segment(value="scan", label="Scan History"),
                ft.Segment(value="deletion", label="Deletion History"),
            ],
            selected=["scan"],
            show_selected_icon=False,
            on_change=self._on_mode_changed,
        )

        # Clear button
        self._clear_btn = ft.OutlinedButton(
            "Clear History",
            icon=ft.icons.Icons.DELETE_SWEEP,
            on_click=self._on_clear_clicked,
            style=ft.ButtonStyle(color=t.colors.danger),
        )
        self._action_bar = ft.Row([self._clear_btn], alignment=ft.MainAxisAlignment.END)

        # Data table
        self._table = ft.DataTable(
            columns=[],
            border=ft.border.all(1, t.colors.border),
            border_radius=8,
            expand=True,
            horizontal_lines=ft.border.BorderSide(1, t.colors.border3),
            column_spacing=10,
        )

        self._empty_label = ft.Text(
            "Run a scan to start building your history.", size=t.typography.size_base, color=t.colors.fg_muted, text_align=ft.TextAlign.CENTER
        )
        self._empty_container = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.icons.Icons.HISTORY, size=40, color="#22D3EE"),
                        bgcolor=ft.Colors.with_opacity(0.08, "#22D3EE"),
                        border_radius=14,
                        padding=18,
                    ),
                    ft.Text("No history yet", size=t.typography.size_lg, weight=ft.FontWeight.W_600, color=t.colors.fg),
                    self._empty_label,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=t.spacing.md,
            ),
            expand=True,
            alignment=ft.Alignment(0.5, 0.5),
            **self._get_glass_style(0.04),
        )
        
        # Container to hold the switching views
        self._data_container = ft.Column(
            [self._table, self._empty_container], 
            expand=True
        )
        # Set initial visibility
        self._table.visible = False
        self._empty_container.visible = True

        # Assemble
        self.controls = [
            self._header,
            self._recent_strip_container,
            ft.Container(content=self._mode_switch, padding=ft.padding.only(left=t.spacing.lg)),
            ft.Container(content=self._action_bar, padding=ft.padding.only(left=t.spacing.lg, right=t.spacing.lg, top=t.spacing.sm)),
            self._data_container,
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_history(self, rows: list) -> None:
        """Called externally to load scan history rows."""
        self._scan_rows = rows or []
        self._refresh_recent_strip(rows or [])
        if self._active_tab == "scan":
            self._refresh_view()

    def load_deletion_history(self, rows: list) -> None:
        """Called externally to load deletion history rows."""
        self._deletion_rows = rows or []
        if self._active_tab == "deletion":
            self._refresh_view()

    def on_show(self) -> None:
        self.load_history(self._bridge.get_scan_history_table_rows())
        self.load_deletion_history(self._bridge.get_deletion_history_table_rows())

    def _refresh_recent_strip(self, rows: list) -> None:
        t = self._t
        recent = rows[:10]
        if not recent:
            self._recent_strip_container.visible = False
            if self._is_mounted():
                self._recent_strip_container.update()
            return
        _mode_colors = {
            "files": "#22D3EE", "photos": "#A78BFA", "videos": "#F472B6",
            "music": "#34D399", "large_files": "#FBBF24", "empty_folders": "#FB923C",
        }
        from cerebro.v2.ui.flet_app.theme import fmt_size
        items = []
        for row in recent:
            mode = row.get("mode", "files")
            mc = _mode_colors.get(mode, "#22D3EE")
            items.append(ft.Container(
                content=ft.Row([
                    ft.Container(width=6, height=6, border_radius=3, bgcolor=mc),
                    ft.Text(row.get("date", ""), size=t.typography.size_xs, color=t.colors.fg2),
                    ft.Text(f"{row.get('groups_found', 0):,} groups", size=t.typography.size_xs, color=t.colors.fg_muted),
                    ft.Text(fmt_size(row.get("bytes_reclaimable", 0)), size=t.typography.size_xs, color="#34D399"),
                ], spacing=8),
                padding=ft.padding.symmetric(vertical=2),
            ))
        self._recent_strip.controls = items
        self._recent_strip_container.visible = True
        if self._is_mounted():
            self._recent_strip_container.update()

    # ------------------------------------------------------------------
    # Tab logic
    # ------------------------------------------------------------------
    def _on_mode_changed(self, e: ft.ControlEvent) -> None:
        data = getattr(e, "data", None)
        if isinstance(data, list) and data:
            self._active_tab = str(data[0])
        else:
            sel = getattr(e.control, "selected", None) or ["scan"]
            self._active_tab = str(sel[0]) if sel else "scan"
        if self._active_tab not in ("scan", "deletion"):
            self._active_tab = "scan"
        self._refresh_view()

    def _current_rows(self) -> list:
        return self._scan_rows if self._active_tab == "scan" else self._deletion_rows

    def _refresh_view(self) -> None:
        rows = self._current_rows()
        has_data = bool(rows)
        
        # Update Table Columns based on tab
        self._update_table_columns()
        
        # Update Table Rows
        self._table.rows = [self._build_row(r) for r in rows]

        # Toggle Visibility
        self._table.visible = has_data
        self._empty_container.visible = not has_data
        self._clear_btn.visible = has_data

        # Update UI
        if self._is_mounted():
            self._table.update()
            self._empty_container.update()
            self._clear_btn.update()

    def _update_table_columns(self) -> None:
        """Update table headers based on the active tab context."""
        t = self._t
        def _col(label: str, color: str = None) -> ft.DataColumn:
            return ft.DataColumn(ft.Text(label, size=t.typography.size_xs, weight=ft.FontWeight.W_600, color=color or t.colors.fg_muted))

        if self._active_tab == "scan":
            self._table.columns = [
                _col("Date/Time"),
                _col("Mode", "#22D3EE"),
                _col("Folders"),
                _col("Groups"),
                _col("Files"),
                _col("Reclaimable", "#34D399"),
                _col("Duration"),
            ]
        else:
            self._table.columns = [
                _col("Date/Time"),
                _col("Policy"),
                _col("Files Deleted"),
                _col("Space Freed", "#34D399"),
                _col("Status"),
            ]

    def _build_row(self, row: dict) -> ft.DataRow:
        t = self._t
        _mode_colors = {
            "files": "#22D3EE", "photos": "#A78BFA", "videos": "#F472B6",
            "music": "#34D399", "large_files": "#FBBF24", "empty_folders": "#FB923C",
        }
        _policy_colors = {"Trash": "#34D399", "Permanent": "#F87171", "Unknown": "#6E7681"}

        if self._active_tab == "scan":
            mode = str(row.get("mode", "files"))
            mode_color = _mode_colors.get(mode, "#22D3EE")
            size_text = _fmt(row.get("bytes_reclaimable", 0))
            return ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row.get("date", "")), size=t.typography.size_sm, color=t.colors.fg2)),
                    ft.DataCell(
                        ft.Container(
                            content=ft.Text(mode, size=9, color=mode_color, weight=ft.FontWeight.W_600),
                            bgcolor=ft.Colors.with_opacity(0.12, mode_color),
                            border_radius=4,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        )
                    ),
                    ft.DataCell(ft.Text(str(row.get("folder", "")), size=t.typography.size_sm, color=t.colors.fg2, overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Text(str(row.get("groups_found", 0)), size=t.typography.size_sm, color=t.colors.fg, weight=ft.FontWeight.W_600)),
                    ft.DataCell(ft.Text(str(row.get("files_scanned", 0)), size=t.typography.size_sm, color=t.colors.fg2)),
                    ft.DataCell(ft.Text(size_text, size=t.typography.size_sm, color="#34D399", weight=ft.FontWeight.W_600)),
                    ft.DataCell(ft.Text(str(row.get("duration", "")), size=t.typography.size_sm, color=t.colors.fg_muted)),
                ]
            )
        else:
            policy = str(row.get("policy", "Unknown"))
            policy_color = _policy_colors.get(policy, "#6E7681")
            return ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(row.get("date", "")), size=t.typography.size_sm, color=t.colors.fg2)),
                    ft.DataCell(
                        ft.Container(
                            content=ft.Text(policy, size=9, color=policy_color, weight=ft.FontWeight.W_600),
                            bgcolor=ft.Colors.with_opacity(0.12, policy_color),
                            border_radius=4,
                            padding=ft.padding.symmetric(horizontal=6, vertical=2),
                        )
                    ),
                    ft.DataCell(ft.Text(str(row.get("count", 0)), size=t.typography.size_sm, color=t.colors.fg, weight=ft.FontWeight.W_600)),
                    ft.DataCell(ft.Text(_fmt(row.get("bytes", 0)), size=t.typography.size_sm, color="#34D399", weight=ft.FontWeight.W_600)),
                    ft.DataCell(ft.Text(str(row.get("status", "")), size=t.typography.size_sm, color=t.colors.fg2)),
                ]
            )

    # ------------------------------------------------------------------
    # Clear history
    # ------------------------------------------------------------------
    def _on_clear_clicked(self, e) -> None:
        def _confirm_clear(e):
            self._bridge.dismiss_top_dialog()
            self._bridge.clear_history(self._active_tab)  # assume bridge method
            if self._active_tab == "scan":
                self._scan_rows.clear()
            else:
                self._deletion_rows.clear()
            self._refresh_view()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Clear History"),
            content=ft.Text(f"Are you sure you want to clear all {self._active_tab} history?"),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._bridge.dismiss_top_dialog()),
                ft.ElevatedButton("Clear", on_click=_confirm_clear,
                                  style=ft.ButtonStyle(bgcolor=self._t.colors.danger, color=self._t.colors.bg)),
            ],
        )
        self._bridge.show_modal_dialog(dialog)

    def apply_theme(self, mode: str) -> None:
        """Updates theme properties without destroying UI controls."""
        self._glass_cache = {}
        self._t = theme_for_mode(mode)
        
        # Update Glass Styles
        self._empty_container.bgcolor = self._get_glass_style(0.04).get('bgcolor')
        self._empty_container.border = self._get_glass_style(0.04).get('border')

        # Update Table Borders
        self._table.border = ft.border.all(1, self._t.colors.border)
        self._table.horizontal_lines = ft.border.BorderSide(1, self._t.colors.border3)

        # Re-render rows to apply new text colors
        self._refresh_view()

        if self._is_mounted():
            self.update()