# Cerebro v2 — Tightening Pass

> **Stack:** Flet `0.84.0` · Project root `cerebro/v2/ui/flet_app/`
>
> **Scope contract (unchanged):** Engine, scan logic, hashing, persistence — all untouched. This pass corrects UI regressions and polish gaps from Phases 0–5 and prepares the surface for Phase 6.
>
> **Status:** Phases 0–5 shipped structurally but several detail-level deliverables didn't fully land. This document is the corrective sweep before Phase 6.

---

## 🎯 What This Pass Fixes

| # | Issue | Severity | Original Phase |
|---|-------|----------|----------------|
| 1 | Severe text contrast — KPI numbers, settings labels, filter pills, Save button all near-invisible | 🔴 Critical | Phase 0 |
| 2 | Home page overcrowded — 9 sections competing for attention | 🟠 High | Phase 2 |
| 3 | Recent Scans duplicates History on Home | 🟠 High | Phase 2 |
| 4 | Filter tabs missing category counts + sizes (`Images · 1,204 · 3.2 GB`) | 🟠 High | Phase 3 |
| 5 | Results/Review slow load — `page.update()` thrash + non-virtualized rows | 🟠 High | Phase 3/4 |
| 6 | Smart Select still uses dropdown + Apply (should be segmented control) | 🟡 Medium | Phase 3 |
| 7 | Title bar still a navy slab — never unified with body | 🟡 Medium | Phase 1 |
| 8 | Filter pills illegible (dark-on-dark) on Results page | 🟡 Medium | Phase 3 |
| 9 | OS-level drag-and-drop not implemented | 🟢 Optional | New |

---

## 1. Contrast Audit & Fix — `ColorScheme` Sync *(Critical)*

### Root cause

The screenshots show text disappearing on dark surfaces. With the project now on Flet, this is almost certainly because `theme.py` is producing `Theme` objects whose `ColorScheme` isn't fully populated, and per-control `bgcolor=` overrides are landing on surfaces that Material is computing `onSurface` text colors against the *default* dark scheme — not your custom one.

Symptoms confirming this:
- **Settings tab labels** (`General`, `Appearance`, `Performance`) ghosted out → `TextButton` / `Tabs` use `onSurface` from `ColorScheme`, which isn't aligned with your custom surface.
- **KPI numbers nearly invisible** → `Text` controls inside custom `Container`s inheriting wrong contrast color.
- **Save Settings button text unreadable** → `FilledButton` text uses `onPrimary`; if `ColorScheme.primary` was set but `on_primary` wasn't, Flutter falls back to a contrast-incorrect default.
- **Filter pills dark-on-dark** → same pattern, `onSurfaceVariant` not set.

### Fix — three steps, surgical

**Step 1: Make `theme.py` produce a complete `ColorScheme`**

Every theme must populate the Material 3 contract, not just the brand colors:

```python
# cerebro/v2/ui/flet_app/theme.py
def theme_for_mode(palette, mode: str) -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=None,  # IMPORTANT: do NOT use seed — it overrides explicit values
        color_scheme=ft.ColorScheme(
            # Brand
            primary=palette.accent,
            on_primary=palette.on_accent,           # MUST be set — controls button text
            primary_container=palette.accent_soft,
            on_primary_container=palette.text_primary,

            # Surfaces — the four levels
            surface=palette.bg_base,                # default container bg
            on_surface=palette.text_primary,        # MUST be set — controls body text
            surface_variant=palette.bg_elevated,    # cards, chips
            on_surface_variant=palette.text_secondary,  # MUST be set — controls labels

            # Outlines
            outline=palette.border_subtle,
            outline_variant=palette.border_strong,

            # State colors
            error=palette.danger,
            on_error=palette.on_danger,

            # Background (legacy but still used by some controls)
            background=palette.bg_base,
            on_background=palette.text_primary,
        ),
        # Density helps with the "everything looks cramped" feel from screenshots
        visual_density=ft.VisualDensity.COMFORTABLE,
    )
```

**Step 2: Stop overriding `bgcolor=` on `Container` without also setting child text colors**

Audit pattern: anywhere you have `Container(bgcolor=something_custom, content=Text("..."))` without an explicit `Text(color=...)`, the text inherits the global `onSurface` and may not contrast. Either:

- Use **only** Material 3 surface tokens (`ft.Colors.SURFACE`, `ft.Colors.SURFACE_CONTAINER_HIGH`, etc.) and let Flet handle contrast, **or**
- When using custom hex `bgcolor`, **always** specify `Text(color=palette.text_primary)` explicitly.

The current codebase appears to mix these, which causes the inconsistent contrast you're seeing.

**Step 3: WCAG audit**

Add a one-time dev-mode check in `palette_themes.py`:

```python
def _contrast_ratio(fg: str, bg: str) -> float:
    # Standard WCAG luminance calc
    ...

def validate_palette(palette) -> list[str]:
    """Returns list of contrast violations. Run in tests."""
    issues = []
    pairs = [
        ("text_primary on bg_base", palette.text_primary, palette.bg_base, 4.5),
        ("text_secondary on bg_base", palette.text_secondary, palette.bg_base, 4.5),
        ("text_primary on bg_elevated", palette.text_primary, palette.bg_elevated, 4.5),
        ("on_accent on accent", palette.on_accent, palette.accent, 4.5),
        ("text_secondary on bg_elevated", palette.text_secondary, palette.bg_elevated, 3.0),
    ]
    for name, fg, bg, minimum in pairs:
        ratio = _contrast_ratio(fg, bg)
        if ratio < minimum:
            issues.append(f"{name}: {ratio:.2f}:1 (need {minimum}:1)")
    return issues
```

Run this against all 35 palettes in CI. Any palette failing WCAG AA gets adjusted.

**Effort:** ~1 day. **Risk:** Low — pure additive corrections to existing theme code.

---

## 2. Home Page Declutter *(High)*

### Current Home shows 9 sections; target is 2.

### Cuts

- ❌ **Remove the 5 filter pills** (`Files / Folders / Compare / Music / Unique`). These are scan modes — they belong inside the scan flow or in Settings, not on the landing surface. The default scan mode already exists in Settings; that's enough.
- ❌ **Remove the standalone "Selected folders" section header** when no folders are picked. The empty state should be inside the scan card, not a labeled empty zone.
- ❌ **Remove the redundant hint text** "Select folders and start a scan to find duplicates." `Start Scan` button copy already says this.
- ❌ **Move Recent Scans entirely off Home** (see §3).
- ❌ **Collapse welcome strip + 3 KPI cards into a single one-line stat strip** at the top.

### Final Home — 2 zones

```
┌─────────────────────────────────────────────────────────┐
│  ✨ Welcome back, Steve                                 │
│     18 scans · 68,679 duplicates · 1.6 GB reclaimed    │  ← Zone 1: greeting + lifetime stats
├─────────────────────────────────────────────────────────┤
│                                                         │
│                                                         │
│            ┌───────────────────────────────────┐        │
│            │  📁 Choose folders to scan        │        │
│            │                                   │        │
│            │  [Downloads ×]  [Documents ×]     │        │
│            │                                   │        │
│            │  Quick add:  Documents · Videos   │        │
│            │              Music · Desktop ...  │        │  ← Zone 2: scan card
│            │                                   │        │     (centered, generous padding)
│            │  ┌──────┐ ┌─────────────┐ ┌─────┐ │        │
│            │  │Browse│ │▶ Start Scan │ │ Last │ │        │
│            │  └──────┘ └─────────────┘ └─────┘ │        │
│            └───────────────────────────────────┘        │
│                                                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Flet implementation notes

- Use `ft.Container(padding=ft.padding.symmetric(vertical=48, horizontal=64))` to create the breathing room.
- Wrap the scan card in `ft.Container(border_radius=20, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, padding=32, border=ft.border.all(1, ft.Colors.OUTLINE_VARIANT))` to visually contain the workflow.
- Center it with `alignment=ft.alignment.center` on the parent and a `width=640` cap so it doesn't span full width on wide monitors.
- Use `ft.ResponsiveRow` if you want the card to gracefully shrink on narrow windows.

**Effort:** ~0.5 day. **Risk:** Trivial — pure layout subtraction.

---

## 3. Move Recent Scans → History *(High)*

### Why

Recent Scans on Home is a duplicate of History. Two screens showing the same data is split attention.

### Steps

1. **Delete the Recent Scans section** from `home_page.py`.
2. **Restructure `history_page.py`** with two stacked sections:
   - **"Recent" group** at the top — last 10 scans in compact row form (matches what was on Home).
   - **"All scans" timeline** below — the existing date-grouped view.
3. **Add an "Open Last Session" ghost button** to Home's scan card next to `Browse` and `Start Scan` — this preserves the most-common Recent-Scans intent ("re-open what I was just looking at") without requiring a History trip.
4. **Wire Home's stat strip** ("18 scans · 68,679 duplicates · 1.6 GB") to be **clickable** → navigates to History. Discoverability for users who used to find scans via the Home list.

### Flet implementation notes

- `state_bridge` already has scan-list state — both pages can subscribe; History becomes the only consumer.
- Use `ft.GestureDetector(on_tap=...)` or a `ft.TextButton` styled as plain text for the clickable stat strip.

**Effort:** ~0.5 day. **Risk:** Trivial.

---

## 4. Category Metrics on Filter Tabs *(High)*

### Current

`Images · Music · Videos · Docs · Archives · Other` — flat tabs with no info.

### Target

```
┌──────────────────────────────────────────────────────────────┐
│  All       Images        Music       Videos      Docs   ...  │
│  381       87            12          4           23          │
│  323 MB    76.4 MB       8.1 MB      240 MB      14 MB       │
└──────────────────────────────────────────────────────────────┘
```

Two-line tab content: count on top, size below in muted text. Active tab fills with `accent`, inactive uses `surface_variant`.

### Flet implementation

Use `ft.SegmentedButton` (Material 3, available in Flet 0.84):

```python
ft.SegmentedButton(
    selected={"all"},
    allow_multiple_selection=False,
    on_change=on_filter_change,
    segments=[
        ft.Segment(
            value="all",
            label=ft.Column(
                [ft.Text("All", weight=ft.FontWeight.W_500),
                 ft.Text(f"{total_count}", size=11),
                 ft.Text(f"{format_size(total_bytes)}", size=10,
                         color=ft.Colors.ON_SURFACE_VARIANT)],
                spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ),
        ft.Segment(value="images", label=...),
        # etc.
    ],
)
```

### Where to compute the metrics

These come from the existing scan results in memory — no new engine signal required. Pre-compute once when Results loads:

```python
# In results_page.py, after results arrive
metrics = {
    "all": (len(all_files), sum(f.size for f in all_files)),
    "images": (img_count, img_bytes),
    "music": (music_count, music_bytes),
    # ...
}
```

Same metrics fuel the Recent Scans rows in History — show a 5-segment colored bar per scan showing file-type breakdown.

**Effort:** ~1 day (computation + segmented button + size formatting helper). **Risk:** Low.

---

## 5. Results / Review Performance Regression *(High)*

### Most likely root cause in Flet

Two specific Flet pitfalls explain the slowness you're describing:

**Pitfall A: `page.update()` thrash.** If results stream in and code is calling `page.update()` per row, each call walks the entire control tree and diffs against the JSON state sent to the renderer. With 381 result rows that's 381 full tree updates instead of 1.

**Pitfall B: Non-lazy `ListView`.** `ListView(controls=[...])` with all controls upfront builds every row even when off-screen. Flet supports lazy item building but it's not the default.

### Fix

**For Pitfall A — batch updates:**

```python
# WRONG (current pattern, probably)
for group in result_groups:
    list_view.controls.append(build_row(group))
    page.update()  # ← thrashes

# RIGHT
list_view.controls = [build_row(g) for g in result_groups]
page.update()  # ← single update
```

**For Pitfall B — use `ListView` with `controls` populated lazily, or `GridView` with `lazy=True`:**

For the Review grid:
```python
ft.GridView(
    runs_count=6,
    max_extent=180,
    spacing=12,
    run_spacing=12,
    controls=thumbnail_cards,  # build all upfront BUT...
    # Flet's GridView is virtualized internally — the heavy lift is in
    # the per-card content. Make cards lightweight:
)
```

For Results:
```python
ft.ListView(
    spacing=8,
    padding=20,
    controls=[build_group_row(g) for g in groups],
    # ListView is virtualized in Flet — but each control still needs
    # to be cheap to construct.
)
```

**For Pitfall B (real fix) — make rows cheap:**

The real issue is probably that `build_row()` creates a deep nested `Container > Row > Column > Container > Text + Image + Buttons` tree per row. Flatten where possible:

- Use `ft.ListTile` for simple rows instead of hand-rolling nested containers
- Lazy-load thumbnails: don't read the actual image bytes until the row is on-screen. Use a placeholder `Container(bgcolor=skeleton_color)` and swap the `Image` in via an `on_visible` handler or a viewport observer.
- Avoid `ft.GraphicsView` / blur effects on per-row backgrounds — these are expensive in Flet's web-render path.

### Profiling step before optimizing

Before applying fixes blindly:

```python
import time
t0 = time.perf_counter()
# build results page
print(f"Results build: {(time.perf_counter()-t0)*1000:.0f}ms")
```

This tells you whether the slowness is build time, update time, or thumbnail-load time. Different fixes for each.

**Effort:** ~1.5 days (profile + fix + verify). **Risk:** Medium — touch a hot UI path. No engine changes.

---

## 6. Smart Select → Segmented Control *(Medium)*

### Current

`[Keep Largest ▼]  [Apply]` — two clicks for one decision.

### Target

```
┌──────────────────────────────────────────────────┐
│  Smart Select                                    │
│  [Largest] [Smallest] [Newest] [Oldest] [Manual] │
└──────────────────────────────────────────────────┘
```

One tap = applied. No dropdown, no separate Apply button.

### Flet implementation

Same `ft.SegmentedButton` as §4. On `on_change`, immediately invoke the existing selection logic. Add a subtle 200ms fade animation on the selection state of result rows so the user sees the action take effect.

Keep a `Manual` option for users who want to deselect everything and pick by hand.

**Effort:** ~0.5 day. **Risk:** Trivial.

---

## 7. Title Bar Unification *(Medium)*

### Current

Hard navy slab at the top of every screenshot, clashing with the dark body.

### Fix

```python
# In main app entrypoint
page.window.title_bar_hidden = True
page.window.title_bar_buttons_hidden = True
page.window.frameless = False  # keep OS window management

# Build custom title bar
title_bar = ft.WindowDragArea(
    content=ft.Container(
        height=40,
        bgcolor=ft.Colors.SURFACE,  # same as body — no slab
        padding=ft.padding.symmetric(horizontal=12),
        content=ft.Row([
            ft.Image(src="assets/cerebro_icon.svg", width=20, height=20),
            ft.Text("Cerebro", weight=ft.FontWeight.W_500, size=13),
            ft.Container(expand=True),  # spacer
            # current section breadcrumb
            ft.Text(current_section, size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Container(expand=True),  # spacer
            # window controls
            _min_button(), _max_button(), _close_button(),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
    ),
)
```

The window controls need OS-appropriate styling. On Windows, Flet exposes `page.window.minimize()`, `page.window.maximize()`, `page.window.close()` for the click handlers.

**Effort:** ~1 day (drag area + window controls + per-OS testing). **Risk:** Medium — frameless windows always have edge cases (snap, multi-monitor, DPI). Test on Windows specifically since that's the target.

---

## 8. Filter Pill Legibility *(Medium)*

Resolves automatically once §1 (ColorScheme fix) and §4 (SegmentedButton) ship — those filters become Material 3 segmented buttons with proper `onSurface` text colors derived from the corrected `ColorScheme`. No separate work.

---

## 9. Drag-and-Drop *(Optional — defer)*

### Recommendation: defer

You confirmed Browse + Quick Add is acceptable. OS-level DnD in Flet 0.84 requires either:

- A custom Flutter extension (Dart code, distribution complexity)
- A workaround using `pywebview` / system tray hacks (fragile)
- Waiting for native Flet DnD support (the Flet team has discussed this; not landed as of 0.84)

Given Phase 6 is the priority and OS-DnD isn't a hard requirement, this gets cut from the tightening pass. **Re-evaluate after Flet's next major release** — if OS-DnD lands natively, it's a 1-day add. Until then, the cost-benefit is wrong.

**What we add instead** to compensate for the missing affordance:

- Make the **scan card itself a click target** for `Browse` (clicking anywhere in the empty card area opens the folder picker). Larger hit zone, same effect, zero extra cost.
- Surface **keyboard shortcut**: `Ctrl+O` → Browse Folders. Add to the `?` overlay in Phase 6.

**Effort:** ~0.25 day for the clickable card + keyboard shortcut. **Risk:** None.

---

## 📋 Execution Order

Total estimated effort: **~5 days**.

| Order | Task | Days | Why this order |
|-------|------|------|----------------|
| 1 | §1 ColorScheme contrast fix | 1.0 | Unblocks visual judgment of everything else |
| 2 | §5 Results/Review perf | 1.5 | Slowness affects daily use; do early |
| 3 | §2 Home declutter | 0.5 | Quick win, big perceived improvement |
| 4 | §3 Recent Scans → History | 0.5 | Pairs naturally with Home declutter |
| 5 | §4 Category metrics | 1.0 | Now that ColorScheme is fixed, segmented button looks right |
| 6 | §6 Smart Select segmented | 0.5 | Reuses §4 segmented button work |
| 7 | §7 Title bar unification | 1.0 | Visible but lower-traffic; safe to do late |
| 8 | §9 Clickable card + Ctrl+O | 0.25 | Tiny add, ships with anything |
| 9 | §8 Filter pills | — | Falls out of §1 + §4 |

### After this pass

The app should:
- Have legible text everywhere across all 35 themes
- Feel snappy on Results / Review
- Show category counts and sizes everywhere they're useful
- Have a focused, two-zone Home that takes 2 seconds to understand
- Have a unified visual shell with no slab title bar
- Be ready for Phase 6 polish (toasts, command palette, keyboard shortcuts, skeletons, celebrations)

---

## 🚫 What This Pass Does NOT Touch

- `TurboFileEngine` or any scan logic
- Database schema or scan persistence
- File deletion / trash logic
- Thread pool / concurrency model
- Any data layer module

Same engine contract as the original plan. Every fix above is presentational or computed-from-existing-data.

---

*Tightening pass v1.0 · Generated for Cerebro v2 (Flet 0.84.0) · Pre-Phase-6 corrective sweep*
