"""Smart rule picker and apply/clear actions shared by Results and Review."""

from __future__ import annotations

from typing import Callable, Literal

import flet as ft

from cerebro.v2.ui.flet_app.pages.review.smart_rules import RULE_LABELS
from cerebro.v2.ui.flet_app.pill_button_styles import pill_text_button_style
from cerebro.v2.ui.flet_app.theme import ThemeTokens


class SmartSelectionRow(ft.Row):
  """Rule segmented control with apply/clear actions."""

  def __init__(
      self,
      t: ThemeTokens,
      *,
      variant: Literal["results", "review"] = "review",
      on_rule_change: Callable[[ft.ControlEvent], None],
      on_apply: Callable[[ft.ControlEvent | None], None],
      on_clear: Callable[[ft.ControlEvent | None], None],
      extra_controls: list[ft.Control] | None = None,
      visible: bool = False,
  ) -> None:
      self._t = t
      self._variant = variant
      self._rule_label: ft.Text | None = None

      label_size = 11 if variant == "results" else 12
      label_weight = ft.FontWeight.W_600 if variant == "review" else None
      self._smart_seg = ft.SegmentedButton(
          selected=["keep_largest"],
          allow_multiple_selection=False,
          on_change=on_rule_change,
          segments=[
              ft.Segment(
                  value=val,
                  label=ft.Text(
                      label,
                      size=label_size,
                      weight=label_weight,
                  ),
              )
              for val, label in RULE_LABELS
          ],
      )

      controls: list[ft.Control] = []
      if variant == "results":
          self._rule_label = ft.Text(
              "Active rule: Keep Largest",
              size=t.typography.size_sm,
              color=t.colors.fg_muted,
              weight=ft.FontWeight.W_500,
          )
          controls.append(ft.Container(content=self._rule_label, margin=ft.margin.only(right=t.spacing.sm)))
          controls.append(self._smart_seg)
          controls.append(
              ft.OutlinedButton(
                  "Auto Mark",
                  icon=ft.icons.Icons.AUTO_FIX_HIGH,
                  on_click=on_apply,
                  style=ft.ButtonStyle(
                      color="#22D3EE",
                      side=ft.BorderSide(1, "#22D3EE"),
                      shape=ft.RoundedRectangleBorder(radius=8),
                      text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_700),
                  ),
              )
          )
          controls.append(
              ft.OutlinedButton(
                  "Unmark All",
                  icon=ft.icons.Icons.DESELECT,
                  on_click=on_clear,
                  style=ft.ButtonStyle(
                      color=t.colors.fg_muted,
                      side=ft.BorderSide(1, t.colors.border),
                      shape=ft.RoundedRectangleBorder(radius=8),
                  ),
              )
          )
      else:
          controls.append(self._smart_seg)
          controls.append(
              ft.TextButton(
                  "Select All per Rule",
                  icon=ft.icons.Icons.CHECK_BOX_OUTLINED,
                  on_click=on_apply,
                  style=pill_text_button_style(t, variant="muted"),
                  tooltip="Apply the active smart rule to mark files across all groups.",
              )
          )
          controls.append(
              ft.TextButton(
                  "Clear Selection",
                  icon=ft.icons.Icons.CHECK_BOX_OUTLINE_BLANK,
                  on_click=on_clear,
                  style=pill_text_button_style(t, variant="muted"),
                  tooltip="Remove all file selections.",
              )
          )
          if extra_controls:
              controls.extend(extra_controls)

      super().__init__(
          controls=controls,
          spacing=t.spacing.sm,
          visible=visible,
          wrap=variant == "review",
          vertical_alignment=ft.CrossAxisAlignment.CENTER,
      )

  @property
  def smart_seg(self) -> ft.SegmentedButton:
      return self._smart_seg

  @property
  def rule_label(self) -> ft.Text | None:
      return self._rule_label

  def sync_theme(self, t: ThemeTokens) -> None:
      self._t = t
      if self._rule_label is not None:
          self._rule_label.color = t.colors.fg_muted
          SmartSelectionRow._safe_update(self._rule_label)

  @staticmethod
  def _safe_update(ctrl: ft.Control | None) -> None:
      if ctrl is None:
          return
      try:
          if ctrl.page is not None:
              ctrl.update()
      except RuntimeError:
          pass
