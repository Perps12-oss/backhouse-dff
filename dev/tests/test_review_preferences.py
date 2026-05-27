"""Phase 1 — review mode preferences and migration defaults."""

from __future__ import annotations

from cerebro.v2.ui.flet_app.pages.review_flow.review_preferences import (
    REVIEW_MODE_DETAILED,
    REVIEW_MODE_SIMPLE,
    load_review_preferences,
    resolve_review_mode,
    save_review_preferences,
    ReviewPreferences,
)


def test_new_install_defaults_simple() -> None:
    assert resolve_review_mode({}) == REVIEW_MODE_SIMPLE
    prefs = load_review_preferences({})
    assert prefs.review_mode == REVIEW_MODE_SIMPLE
    assert prefs.auto_apply_on_open is True
    assert prefs.default_keeper_rule == "keep_newest"


def test_existing_settings_default_detailed() -> None:
    settings = {"general": {"remember_folders": True}, "appearance": {"font_size": 13}}
    assert resolve_review_mode(settings) == REVIEW_MODE_DETAILED
    prefs = load_review_preferences(settings)
    assert prefs.review_mode == REVIEW_MODE_DETAILED
    assert prefs.auto_apply_on_open is False


def test_explicit_simple_mode_persisted() -> None:
    settings = save_review_preferences(
        {"general": {}},
        ReviewPreferences(
            review_mode=REVIEW_MODE_SIMPLE,
            default_keeper_rule="keep_largest",
            auto_apply_on_open=False,
            simple_helper_dismissed=True,
            upgrade_banner_dismissed=True,
        ),
    )
    prefs = load_review_preferences(settings)
    assert prefs.review_mode == REVIEW_MODE_SIMPLE
    assert prefs.default_keeper_rule == "keep_largest"
    assert prefs.auto_apply_on_open is False
    assert prefs.simple_helper_dismissed is True
