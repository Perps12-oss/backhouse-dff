"""Accent theme presets, tokens, and derive_preset_from_base behavior."""

from __future__ import annotations

from cerebro.v2.ui.flet_app.multigradient_themes import (
    default_gradient,
    gradient_by_id,
    gradient_themes_for_picker,
)
from cerebro.v2.ui.flet_app.palette_themes import (
    DEFAULT_PRESET_ID,
    FLET_BASE_PRESET,
    derive_preset_from_base,
    resolve_preset_id,
)
from cerebro.v2.ui.flet_app.pill_button_styles import pill_filled_critical
from cerebro.v2.ui.flet_app.theme import ThemeTokens, _tokens_from_preset, set_active_preset


def test_default_preset_id_is_material_purple() -> None:
    assert DEFAULT_PRESET_ID == "material_purple"
    assert resolve_preset_id("") == "material_purple"
    assert resolve_preset_id("   ") == "material_purple"


def test_new_gradient_themes_exist_with_neutral_shell() -> None:
    purple = gradient_by_id("material_purple")
    teal = gradient_by_id("arctic_teal")
    classic = gradient_by_id("flet_base")
    assert purple is not None
    assert teal is not None
    assert classic is not None
    assert purple.accent == "#BB86FC"
    assert teal.accent == "#14B8A6"
    assert classic.accent == "#1DB954"
    assert purple.stops == classic.stops == ("#1a2228", "#121212")


def test_default_gradient_is_material_purple() -> None:
    assert default_gradient().id == "material_purple"


def test_picker_lists_preferred_themes_first() -> None:
    ids = [g.id for g in gradient_themes_for_picker()]
    assert ids[:3] == ["material_purple", "arctic_teal", "flet_base"]


def test_derive_preset_decouples_success_from_primary() -> None:
    derived = derive_preset_from_base(
        FLET_BASE_PRESET,
        preset_id="material_purple",
        name="Material Purple",
        primary="#BB86FC",
    )
    assert derived.primary == "#BB86FC"
    assert derived.success == FLET_BASE_PRESET.success
    assert derived.success != derived.primary


def test_tokens_from_preset_include_critical_and_fg_soft() -> None:
    derived = derive_preset_from_base(
        FLET_BASE_PRESET,
        preset_id="arctic_teal",
        name="Arctic Teal",
        primary="#14B8A6",
        fg_soft="#E0E0E0",
    )
    colors = _tokens_from_preset(derived)
    assert colors.action_critical == "#FF6F61"
    assert colors.fg_soft == "#E0E0E0"
    assert colors.success == "#34D399"
    assert colors.accent == "#14B8A6"


def test_pill_filled_critical_uses_action_critical_token() -> None:
    derived = derive_preset_from_base(
        FLET_BASE_PRESET,
        preset_id="material_purple",
        name="Material Purple",
        primary="#BB86FC",
    )
    set_active_preset(derived)
    t = ThemeTokens(colors=_tokens_from_preset(derived))
    style = pill_filled_critical(t)
    assert style.bgcolor == "#FF6F61"


def test_flet_base_preset_remains_valid_legacy_green() -> None:
    assert resolve_preset_id("flet_base") == "flet_base"
    g = gradient_by_id("flet_base")
    assert g is not None
    assert g.name == "Classic Green"
