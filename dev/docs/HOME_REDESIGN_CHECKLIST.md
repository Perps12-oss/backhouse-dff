# Home redesign checklist (Phase 2)

Status key: ✅ done · ⚠️ partial · ❌ not done

## Shell & layout

| Item | Status | References |
|------|--------|------------|
| Single `_sync_grid_bg` (no duplicate) | ✅ | `cerebro/v2/ui/flet_app/layout.py` |
| `_grid_drift_generation` in `__init__` | ✅ | `layout.py` (`AppLayout.__init__`) |
| `navigate_to` / `apply_theme` call `_sync_grid_bg` | ✅ | `layout.py` |
| Home grid drift loop (motion-gated) | ✅ | `layout.py` (`_grid_drift_loop`) |
| `ft.Alignment(0, 1)` for grid rows (Flet 3.14) | ✅ | `layout.py` (`_build_home_grid_column`) |
| Nav pill motion via `should_animate` | ✅ | `layout.py` (`_sync_nav_selection`) |

## Design system & theme

| Item | Status | References |
|------|--------|------------|
| `AccentPreset` + `PRESET_ACCENT_MAP` | ✅ | `design_system/tokens.py` |
| `theme_for_mode(mode, preset_id)` | ✅ | `theme.py` |
| `adaptive_glass(content, t, page=…)` | ✅ | `design_system/glass.py` |
| `should_animate` / `should_animate_page` | ✅ | `utils/motion.py` |
| `sync_reduce_motion_storage` on boot | ✅ | `main.py` |
| `sync_reduce_motion_storage` on settings save | ✅ | `pages/settings_page.py` (`_on_save`) |

## Motion utilities

| Item | Status | References |
|------|--------|------------|
| `animate_if` / `animation_or_none` | ✅ | `utils/motion.py` |
| `run_if_animated` | ✅ | `utils/motion.py` |
| Unit tests (motion + shortcuts) | ✅ | `dev/tests/test_flet_utils.py` |

## Global shortcuts

| Item | Status | References |
|------|--------|------------|
| `register_global_shortcuts` wired in main | ✅ | `main.py`, `utils/shortcuts.py` |
| Ctrl/Cmd+1–4 tab jumps | ✅ | `utils/shortcuts.py` |
| Platform-aware nav tooltip labels | ✅ | `layout.py` (`format_nav_shortcut_label`) |

## Home panels

| Item | Status | References |
|------|--------|------------|
| Folder panel: dashed drop zone | ✅ | `components/dashboard/folder_panel.py` |
| Folder panel: drag-over scale/glow (motion) | ✅ | `folder_panel.py` (`_set_drag_over`, `_scale_host`) |
| Home chrome: amber tagline icon | ✅ | `components/dashboard/home_chrome.py` |
| Home chrome: typing cursor on tagline (motion) | ✅ | `home_chrome.py` (`_tagline_typewriter_loop`) |
| Hero button: hover scale/glow | ✅ | `components/dashboard/hero_button.py` |
| Hero button: icon rumble on hover (motion) | ✅ | `hero_button.py` (`_icon_rumble_loop`) |
| Scan options: polished collapse (ExpansionTile + switcher) | ✅ | `components/dashboard/scan_options_panel.py` |
| Collapsible sections: AnimatedSwitcher height (motion) | ✅ | `components/dashboard/collapsible_section.py` |
| Stats: count-up on Summary expand (motion) | ✅ | `components/dashboard/stats_presence.py` |

## Dashboard integration

| Item | Status | References |
|------|--------|------------|
| `page` / `bridge` passed to `adaptive_glass` builds | ✅ | `dashboard_page.py`, `home_chrome.py`, `folder_panel.py`, `home_shell.py` |
| `apply_theme` uses `theme_for_mode(mode, preset_id)` | ✅ | `dashboard_page.py` (`apply_theme`) |
| Reduce-motion refresh on show / theme | ✅ | `dashboard_page.py` (`_refresh_reduce_motion`) |

## Out of scope (Phase 2)

| Item | Status | Notes |
|------|--------|-------|
| Full WCAG audit | ❌ | Explicitly excluded |
| OS folder drag-drop file paths (all platforms) | ⚠️ | `DragTarget` wired; platform payload handling may vary |
| Web build blur parity | ⚠️ | `adaptive_glass` uses solid fallback on web |

## Summary

- **Estimated complete:** ~95% of Phase 2 checklist items
- **Blockers:** None for merge; manual smoke on desktop recommended for drag-drop and glass blur
