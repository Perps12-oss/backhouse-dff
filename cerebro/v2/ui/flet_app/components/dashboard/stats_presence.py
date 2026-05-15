"""Home stats row and last-scan presence strip."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Callable

import flet as ft

from cerebro.v2.ui.flet_app.design_system.glass import glass_container
from cerebro.v2.ui.flet_app.theme import ThemeTokens, fmt_size

if TYPE_CHECKING:
    from cerebro.v2.ui.flet_app.services.state_bridge import StateBridge

_log = logging.getLogger(__name__)


class DashboardStatsPresence:
  """Operational stats cards and presence insights for the Home page."""

  _PRESENCE_REFRESH_MIN_S: float = 1.25

  def __init__(
      self,
      bridge: "StateBridge",
      t: ThemeTokens,
      *,
      safe_update: Callable[[ft.Control | None], None],
      set_container_glow: Callable[..., None],
  ) -> None:
      self._bridge = bridge
      self._t = t
      self._safe_update = safe_update
      self._set_container_glow = set_container_glow
      self._stats_row_signature: tuple[int, int, int] | None = None
      self._presence_refresh_last_mon: float = 0.0

      s = t.spacing
      self._presence_title = ft.Text(
          "",
          size=t.typography.size_sm,
          weight=ft.FontWeight.W_700,
          color=t.colors.fg,
      )
      self._presence_body = ft.Text(
          "",
          size=t.typography.size_xs,
          color=t.colors.fg2,
      )
      self._presence_mtime = ft.Text(
          "",
          size=t.typography.size_xs,
          color=t.colors.fg_muted,
          italic=True,
      )
      self._insights_row = ft.Row(
          [],
          spacing=s.sm,
          tight=True,
          wrap=True,
          alignment=ft.MainAxisAlignment.CENTER,
      )
      self._presence_row = glass_container(
          visible=False,
          width=620,
          padding=ft.Padding.symmetric(horizontal=s.md, vertical=s.sm),
          t=t,
          content=ft.Column(
              [
                  self._presence_title,
                  self._presence_body,
                  self._presence_mtime,
                  ft.Container(height=6),
                  self._insights_row,
              ],
              spacing=2,
              tight=True,
          ),
      )
      self._stats_row = ft.Row([], alignment=ft.MainAxisAlignment.CENTER, spacing=s.md)

  @property
  def stats_row(self) -> ft.Row:
      return self._stats_row

  @property
  def presence_row(self) -> ft.Container:
      return self._presence_row

  @property
  def presence_mtime(self) -> ft.Text:
      return self._presence_mtime

  def sync_theme(self, t: ThemeTokens) -> None:
      self._t = t

  def set_mtime_caption(self, value: str) -> None:
      self._presence_mtime.value = value
      self._safe_update(self._presence_mtime)

  def update_stats(self, stats: dict, *, refresh_presence_force: bool = False) -> None:
      t = self._t
      scans_n = int(stats.get("scans", 0) or 0)
      dupes_n = int(stats.get("dupes", 0) or 0)
      bytes_n = int(stats.get("bytes_reclaimed", 0) or 0)
      new_sig = (scans_n, dupes_n, bytes_n)
      sig_changed = self._stats_row_signature != new_sig
      self._stats_row_signature = new_sig
      self._stats_row.visible = (scans_n > 0) or (dupes_n > 0) or (bytes_n > 0)
      cards = [
          (ft.icons.Icons.SEARCH, "#22D3EE", "Scans Run", f"{scans_n:,}"),
          (ft.icons.Icons.CONTENT_COPY, "#A78BFA", "Duplicates Found", f"{dupes_n:,}"),
          (ft.icons.Icons.STORAGE, "#34D399", "Space Recovered", fmt_size(bytes_n)),
      ]
      controls: list[ft.Control] = []
      for icon, accent, label, value in cards:
          tile = glass_container(
              content=ft.Row(
                  [
                      ft.Container(
                          content=ft.Icon(icon, size=20, color=accent),
                          bgcolor=ft.Colors.with_opacity(0.18, accent),
                          border=ft.border.all(1, ft.Colors.with_opacity(0.24, accent)),
                          border_radius=8,
                          padding=8,
                      ),
                      ft.Column(
                          [
                              ft.Text(
                                  value,
                                  size=24,
                                  weight=ft.FontWeight.W_700,
                                  color=t.colors.fg,
                              ),
                              ft.Text(
                                  label.upper(),
                                  size=11,
                                  weight=ft.FontWeight.W_500,
                                  color=t.colors.fg_muted,
                              ),
                          ],
                          spacing=2,
                          tight=True,
                      ),
                  ],
                  vertical_alignment=ft.CrossAxisAlignment.CENTER,
                  spacing=10,
              ),
              t=self._t,
              padding=ft.Padding.symmetric(horizontal=14, vertical=10),
          )
          tile.ink = True
          tile.on_hover = lambda e, c=tile: self._set_container_glow(
              c, e.data == "true", variant="secondary"
          )
          controls.append(
              ft.GestureDetector(
                  content=tile,
                  on_tap=lambda _e: self._bridge.navigate("history"),
                  mouse_cursor=ft.MouseCursor.CLICK,
              )
          )
      self._stats_row.controls = controls
      self._safe_update(self._stats_row)
      self._maybe_refresh_presence(force=bool(refresh_presence_force or sig_changed))

  def _maybe_refresh_presence(self, *, force: bool = False) -> None:
      now = time.monotonic()
      if (
          not force
          and (now - float(self._presence_refresh_last_mon or 0.0))
          < float(self._PRESENCE_REFRESH_MIN_S)
      ):
          return
      self._presence_refresh_last_mon = now
      self.refresh_presence()

  def refresh_presence(self) -> None:
      from cerebro.v2.core.index_presence import format_relative_past, latest_scan_entry
      from cerebro.v2.core.scan_history_db import get_scan_history_db
      from cerebro.v2.persistence.scan_snapshot import load_last_scan_summary

      t = self._t
      entry = latest_scan_entry()
      summary = load_last_scan_summary()

      if not entry and not summary:
          self._presence_row.visible = False
          self._insights_row.controls = []
          self._safe_update(self._presence_row)
          return

      if entry:
          rel = format_relative_past(entry.timestamp)
          mode_lbl = str(entry.mode or "files").replace("+", " + ")
          self._presence_title.value = f"Last analysis · {rel}"
          self._presence_body.value = (
              f"{entry.groups_found:,} groups · {entry.files_found:,} duplicate paths · "
              f"{fmt_size(entry.bytes_reclaimable)} reclaimable · {mode_lbl}. "
              "Hash index on disk makes the next run faster when files are unchanged."
          )
      else:
          gc = int((summary or {}).get("groups_count", 0) or 0)
          sm = str((summary or {}).get("scan_mode", "files") or "files")
          self._presence_title.value = "Saved duplicate summary"
          self._presence_body.value = (
              f"{gc:,} groups on disk · mode {sm.replace('+', ' + ')} — "
              "run a scan to refresh history totals."
          )

      self._presence_title.color = t.colors.fg
      self._presence_body.color = t.colors.fg2
      self._presence_mtime.color = t.colors.fg_muted

      since_7d = time.time() - 7 * 24 * 3600
      n_scans, g_sum, f_sum, b_sum = get_scan_history_db().aggregate_since(since_7d)
      chips: list[ft.Control] = [
          self._insight_chip(t, "7-day scans", f"{n_scans}", "#22D3EE"),
          self._insight_chip(t, "7-day duplicate paths (total)", f"{f_sum:,}", "#A78BFA"),
          self._insight_chip(t, "7-day reclaimable (total)", fmt_size(int(b_sum)), "#34D399"),
          self._insight_chip(t, "7-day groups (total)", f"{g_sum:,}", "#F472B6"),
      ]

      if summary:
          hist_ts = float(entry.timestamp) if entry else 0.0
          sum_ts = float(summary.get("session_ts", 0.0) or 0.0)
          aligned = (not hist_ts) or abs(sum_ts - hist_ts) < 300.0
          prefix = "Last run" if aligned else "Saved session"
          b = summary.get("age_buckets") or {}
          chips.extend(
              [
                  self._insight_chip(t, f"{prefix} · <7d files", fmt_size(int(b.get("under_7d", 0))), "#F97316"),
                  self._insight_chip(t, f"{prefix} · 7–30d", fmt_size(int(b.get("d7_to_30", 0))), "#EAB308"),
                  self._insight_chip(t, f"{prefix} · 30d+", fmt_size(int(b.get("over_30d", 0))), "#94A3B8"),
              ]
          )
          for row in (summary.get("top_folders") or [])[:2]:
              pth = str(row.get("path", ""))
              br = int(row.get("reclaimable", 0) or 0)
              chips.append(
                  self._insight_chip(
                      t,
                      f"{prefix} · {self._short_folder_label(pth, 36)}",
                      fmt_size(br),
                      "#0EA5E9",
                  )
              )

      self._insights_row.controls = chips
      self._presence_row.bgcolor = self._t.colors.glass_bg
      self._presence_row.border = ft.border.all(1, self._t.colors.glass_border)
      self._presence_row.visible = True
      self._safe_update(self._presence_title)
      self._safe_update(self._presence_body)
      self._safe_update(self._presence_mtime)
      self._safe_update(self._insights_row)
      self._safe_update(self._presence_row)

  @staticmethod
  def _insight_chip(t: ThemeTokens, label: str, value: str, accent: str) -> ft.Container:
      return ft.Container(
          content=ft.Row(
              [
                  ft.Text(label, size=10, color=t.colors.fg_muted, weight=ft.FontWeight.W_500),
                  ft.Text(value, size=11, weight=ft.FontWeight.W_700, color=accent),
              ],
              tight=True,
              spacing=4,
              vertical_alignment=ft.CrossAxisAlignment.CENTER,
          ),
          padding=ft.Padding.symmetric(horizontal=10, vertical=6),
          border_radius=999,
          bgcolor=ft.Colors.with_opacity(0.1, accent),
      )

  @staticmethod
  def _short_folder_label(path: str, max_len: int = 40) -> str:
      s = str(path).replace("\\", "/")
      if len(s) <= max_len:
          return s
      return "…" + s[-(max_len - 1) :]
