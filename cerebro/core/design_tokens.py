"""Compatibility shim for legacy core design-token imports.

Canonical token definitions now live in `cerebro.v2.core.design_tokens`.
"""

from __future__ import annotations

from dataclasses import dataclass

from cerebro.v2.core.design_tokens import (
    Colors,
    Dimensions,
    Duration,
    Shadows,
    Spacing,
    Tokens,
    Typography,
    ZIndex,
)


@dataclass(frozen=True)
class DesignTokens:
    """Legacy token shape mapped onto v2 canonical token values."""

    bg_primary: str = Colors.CTK_BG_PRIMARY
    bg_secondary: str = Colors.CTK_BG_SECONDARY
    bg_tertiary: str = Colors.CTK_BG_TERTIARY
    bg_input: str = Colors.CTK_BG_SECONDARY
    accent: str = Colors.CTK_ACCENT
    accent_hover: str = Colors.CTK_ACCENT_HOVER
    danger: str = Colors.CTK_DANGER
    success: str = Colors.CTK_SUCCESS
    warning: str = Colors.CTK_WARNING
    info: str = Colors.INFO.hex
    text_primary: str = Colors.CTK_TEXT_PRIMARY
    text_secondary: str = Colors.CTK_TEXT_SECONDARY
    text_on_accent: str = "#FFFFFF"
    text_disabled: str = Colors.TEXT_DISABLED.hex
    border: str = Colors.BORDER.hex
    border_subtle: str = Colors.BORDER_DIM.hex


tokens = DesignTokens()


def get_color(name: str, theme: str = "dark") -> str:
    _ = theme  # legacy argument kept for compatibility
    return getattr(tokens, name, tokens.bg_primary)


def set_theme(name: str) -> None:
    _ = name  # retained for compatibility
