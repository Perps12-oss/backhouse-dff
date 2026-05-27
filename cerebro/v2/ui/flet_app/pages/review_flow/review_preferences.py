"""Review UX preferences (simple vs detailed) persisted in app settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from cerebro.v2.ui.flet_app.pages.review_flow.smart_rules import normalized_rule

REVIEW_MODE_SIMPLE = "simple"
REVIEW_MODE_DETAILED = "detailed"
DEFAULT_KEEPER_RULE = "keep_newest"


@dataclass(frozen=True)
class ReviewPreferences:
    review_mode: str
    default_keeper_rule: str
    auto_apply_on_open: bool
    simple_helper_dismissed: bool
    upgrade_banner_dismissed: bool


def _review_section(settings: Dict[str, Any]) -> Dict[str, Any]:
    review = settings.get("review")
    if isinstance(review, dict):
        return review
    return {}


def resolve_review_mode(settings: Dict[str, Any]) -> str:
    """New installs default simple; existing settings files without review_mode → detailed."""
    review = _review_section(settings)
    mode = str(review.get("review_mode", "")).strip().lower()
    if mode in (REVIEW_MODE_SIMPLE, REVIEW_MODE_DETAILED):
        return mode
    if settings and any(k in settings for k in ("general", "appearance", "deletion", "performance")):
        return REVIEW_MODE_DETAILED
    return REVIEW_MODE_SIMPLE


def load_review_preferences(settings: Dict[str, Any]) -> ReviewPreferences:
    review = _review_section(settings)
    mode = resolve_review_mode(settings)
    rule = normalized_rule(str(review.get("default_keeper_rule", DEFAULT_KEEPER_RULE)))
    auto = bool(review.get("auto_apply_on_open", True))
    if mode == REVIEW_MODE_DETAILED:
        auto = bool(review.get("auto_apply_on_open", False))
    return ReviewPreferences(
        review_mode=mode,
        default_keeper_rule=rule,
        auto_apply_on_open=auto,
        simple_helper_dismissed=bool(review.get("simple_helper_dismissed", False)),
        upgrade_banner_dismissed=bool(review.get("upgrade_banner_dismissed", False)),
    )


def save_review_preferences(settings: Dict[str, Any], prefs: ReviewPreferences) -> Dict[str, Any]:
    settings = dict(settings or {})
    settings["review"] = {
        "review_mode": prefs.review_mode,
        "default_keeper_rule": normalized_rule(prefs.default_keeper_rule),
        "auto_apply_on_open": bool(prefs.auto_apply_on_open),
        "simple_helper_dismissed": bool(prefs.simple_helper_dismissed),
        "upgrade_banner_dismissed": bool(prefs.upgrade_banner_dismissed),
    }
    return settings


def is_simple_review_mode(settings: Dict[str, Any]) -> bool:
    return resolve_review_mode(settings) == REVIEW_MODE_SIMPLE
