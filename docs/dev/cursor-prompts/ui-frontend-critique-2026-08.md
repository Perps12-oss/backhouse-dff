# CEREBRO Flet UI — Frontend Critique & Cursor Prompt

_Date: 2026-08-14 · Scope: `cerebro/v2/ui/flet_app/**` (the live Flet desktop shell). Superseded/archival docs (`docs/UI_OVERHAUL_AUDIT.md`, the root-level `review,results and dashboad page refactor` note) describe an older Tk/CTk or pre-mixin-refactor state and are only used here for delta comparison._

Verified against the current tree, not just prior docs — every claim below has a file/line pointer you can re-check.

---

## 1. Fit for purpose

Cerebro is a duplicate-file triage tool: scan → review groups → decide keep/delete → confirm. The Flet shell mostly serves that loop well (dashboard → review → history), but two structural choices work against "fit for purpose":

- **Two competing implementations of the most important screen are both shipped and reachable.** `main.py:205-219` picks between `ReviewFlowHost` (new, `pages/review_flow/`) and the legacy `ReviewPage` (`pages/review_page.py` + 7 mixins in `pages/review/`) based on a settings flag `general.review_flow_v2` — **default `True`**, and **not exposed anywhere in `settings_page.py`** (`grep` for `review_flow_v2` in that file returns nothing). That means the legacy review stack — `review_mixins.py` (775 lines), `grid_view.py` (525), `inspector_panel.py` (458), `workstation_sidebar.py`, `stats_header.py` — is dead weight in every real install: it can never be reached by a user, only by hand-editing a JSON settings file. It still has to be read, tested, and reasoned about by anyone touching Review. Pick one implementation and delete the other.
- **`"duplicates"` is a second, undocumented alias for the Review tab.** It's wired into `builders` in `main.py:274`, handled specially in `layout.py:292`, and referenced in `_on_state_change` (`main.py:699`), but it isn't in `ROUTES` (`routes.py`) and has no nav entry. It's a leftover from an older "Results" page that has since merged into Review. It adds a second code path to reason about for zero user-facing benefit.
- **Navigation rail mixes a workflow step with a settings sub-page as peers.** `routes.py:23-28` gives Home, Review, History, Exclude, Settings equal top-level weight. "Exclude" is pure configuration (an exclude-list editor) with the same visual prominence as the primary Home→Review workflow. This dilutes the rail and adds an extra decision for users scanning the nav for "what do I do next." It reads more naturally as a Settings sub-page/tab.

**Recommendation:** commit to `ReviewFlowHost` as the one Review implementation, delete `ReviewPage` + its mixins (or the reverse, if `ReviewFlowHost` is actually less mature — verify via a quick manual smoke test before deleting either), remove the `"duplicates"` alias, and fold Exclude into Settings.

---

## 2. Usability / ease of use

- **Accessibility is a self-acknowledged gap, and the evidence backs it up.** `docs/HOME_REDESIGN_CHECKLIST.md` explicitly lists "Full WCAG audit" as `❌ Explicitly excluded`. Consistent with that: `semantics_label` appears **0 times** anywhere in `cerebro/v2/ui/flet_app`, and `tooltip=` appears only **25 times** across the whole app. The window title-bar buttons (minimize/maximize/close, `main.py:308-310`) are icon-only with no `semantics_label`, so a screen-reader user gets nothing. Icon-only affordances elsewhere (nav rail, filter chips, sort/view toggles) rely entirely on visual recognition.
- **No true virtualization for large result sets — still a hard cap, not a fix.** `components/common/chunked_view.py:17` defines `MAX_RENDERED_GROUPS = 1_000` and every chunk config caps at it. For scans that legitimately return >1000 duplicate groups, the extra groups are silently unrenderable rather than paginated/virtualized — a "results are missing and nothing tells you why" trap. This was flagged in the historical audit and is still true today.
- **Onboarding and command palette are solid but not discoverable from the same surface.** `main.py`'s `_show_onboarding_if needed`/`_show_command_palette`/`_show_shortcuts_overlay` are well built (progressive 3-step onboarding, searchable palette, shortcuts sheet) but are only reachable via keyboard shortcuts (`Ctrl+K`, `Shift+?`) or the command palette itself — there's no visible "?" affordance in the chrome for a first-time mouse-only user to find them.

---

## 3. Visual hierarchy & design-system consistency

The app has a real design-system layer (`theme.py`, `design_system/tokens.py`, `design_system/glass.py`, `palette_themes.py`) whose own docstring says the quiet part loud: _"All page/component modules should consume colors from this module rather than hard-coding hex values"_ (`theme.py:3-5`). In practice that rule is broken constantly:

- **539 raw `"#RRGGBB"` string literals** across the Flet app (outside the theme files themselves), concentrated in: `pages/review/_types.py` (29), `main.py` (21), `history_page.py` (20), `design_system/tokens.py` (18 — some legitimate as source-of-truth, but re-exported as loose constants like `NEON_BORDER_SUBTLE` rather than structured tokens), `components/filters/filter_bar.py` (13), `components/dashboard/stats_presence.py` (11).
- **The shared glass-container helper (`adaptive_glass`) is used in only 5 files.** Given how much of the UI is glassmorphic (cards, panels, dialogs), most glass surfaces are being hand-built per file instead of through the shared, theme-aware primitive — so blur/opacity/border treatment will drift between screens and between the 24 built-in theme presets.
- **24 built-in theme presets** (`cerebro/themes/builtin/*.json`: arctic, blossom, catppuccin_mocha, dracula, high_contrast, monokai_pro, nord, tokyo_night, synthwave, …) is a lot of visual surface to keep consistent. Combined with the two points above, this isn't a benefit to users so much as 24x the chance that some screen's hardcoded hex clashes with contrast/hierarchy on a given preset (most visibly a risk for `high_contrast`, which exists specifically for accessibility and is the preset most likely to be broken by a stray hardcoded color).

**Net effect on visual hierarchy:** the *intent* (tokens → typography scale → spacing scale, all defined in `tokens.py`) is sound, but enforcement is missing, so hierarchy consistency across pages/themes can't be guaranteed just by reading the design system — it has to be verified screen-by-screen.

---

## 4. Functionality & reliability risk (UX-adjacent)

- **`dashboard_page.py` (1,767 lines) and `scan_hud.py` (1,730 lines) are both larger than `review_page.py` was before the dedicated refactor effort documented in `docs/plans/REVIEW_PAGE_REFACTOR_PLAN.md` (2,411 → target <400, now 281 lines as a coordinator shell — that refactor did land).** The review-page decomposition worked; it just wasn't applied to the other two biggest files, and the *replacement* review implementation (`review_flow/host.py`, 1,309 lines) has already regrown into the same shape the refactor was meant to eliminate. Every one of these files is a place where a UI bug fix or copy change risks unrelated regressions, and it's where new contributors will spend the most time getting oriented before they can safely ship a small visual change.
- **What's already fixed, for calibration — don't re-litigate these:** the old audit's "3x duplicated `_safe_update`/`_get_glass_style`" complaint is resolved for `safe_update` (single shared `components/common/safe_controls.py`, imported in 7 files); motion/reduce-motion is centralized in `utils/motion.py` with `should_animate`/`animate_if` used consistently; the scan-cancel flow (`scan_hud.py`) is now a single button with clear state text, not the "confusing panel with a disabled button" the old audit described.

---

## 5. Priority ranking

| Pri | Issue | Why it matters | Where |
|---|---|---|---|
| P0 | Two live Review implementations, one unreachable from Settings UI | Doubles maintenance surface on the app's core screen for zero user value | `main.py:205-219`, `pages/review_page.py`, `pages/review_flow/` |
| P0 | `MAX_RENDERED_GROUPS = 1_000` silently drops results | Silent data loss for power users with large scans | `components/common/chunked_view.py:17` |
| P1 | 539 hardcoded hex colors bypassing the token system | Breaks theme consistency, especially `high_contrast` | repo-wide, worst offenders listed above |
| P1 | Zero `semantics_label`, sparse `tooltip=` | Accessibility gap the team already flagged as out-of-scope but never revisited | repo-wide, `main.py:308-310` |
| P2 | "Exclude" as a top-level nav peer to Home/Review/History/Settings | IA clutter, extra decision cost in primary nav | `routes.py:23-28` |
| P2 | Dead `"duplicates"` tab alias | Confusing indirection for contributors | `main.py:274`, `layout.py:292` |
| P2 | `dashboard_page.py`, `scan_hud.py`, `review_flow/host.py` all >1,300 lines | Slows every future UI change on the busiest screens | see file list above |

---

## Ready-to-paste Cursor prompt

Copy everything below the line into Cursor to work through the findings in priority order. It's written to be run as a sequence of small, reviewable PRs, not one giant diff.

---

```
You're working in the Cerebro Flet desktop UI (`cerebro/v2/ui/flet_app/`). This is a
duplicate-file finder app. I've had a frontend critique done and want to work through
the findings as separate, reviewable changes — do NOT combine them into one commit.
Confirm your understanding of each task before writing code, and stop after each item
so I can review before you move to the next.

Context you need first:
- `cerebro/v2/ui/flet_app/main.py` picks between two Review implementations based on
  `general.review_flow_v2` in settings (default True): `pages/review_flow/ReviewFlowHost`
  (new) vs `pages/review_page.py::ReviewPage` (legacy, 7 mixins in `pages/review/`).
  The flag is not exposed in `pages/settings_page.py`, so only ReviewFlowHost is ever
  reachable by real users.
- `components/common/chunked_view.py` defines `MAX_RENDERED_GROUPS = 1_000` — result
  groups beyond that count are never rendered, with no user-visible indication.
- Theme tokens live in `theme.py`, `design_system/tokens.py`, `design_system/glass.py`,
  `palette_themes.py`. `theme.py`'s own docstring says all colors should come from
  there, but hundreds of raw `"#RRGGBB"` literals exist outside those files.
- `routes.py` defines the nav rail: Home, Review, History, Exclude, Settings as five
  equal-weight top-level tabs.

Work through these tasks IN ORDER. Each is its own change:

1. **Confirm which Review implementation is actually maintained**, by diffing feature
   coverage between `pages/review_flow/` and `pages/review_page.py` + `pages/review/`
   (grid view, compare/inspect view, smart-select rules, filters, deletion flow).
   Report back what each has that the other lacks before deleting anything.

2. **Once confirmed, delete the losing implementation entirely** — its page file, its
   private component modules under `pages/review/` or `pages/review_flow/`, the
   `review_flow_v2` branch in `main.py`, and any now-unused imports/registrations
   (`bridge.register_action_control(...)` calls referencing the removed page's
   controls). Also remove the dead `"duplicates"` builder key in `main.py` and the
   `key == "duplicates"` branch in `layout.py` — Review is reached only via the
   `"review"` key.

3. **Replace the hard `MAX_RENDERED_GROUPS` cap with either true virtualization or a
   visible truncation notice.** Minimum acceptable fix: when `len(groups) >
   MAX_RENDERED_GROUPS`, show a persistent banner/label stating how many groups are
   hidden and why, instead of silently dropping them. Preferred fix: only build
   controls for the currently-visible viewport (windowed rendering) so the cap can be
   removed. Locate all call sites in `pages/review/grid_view.py` (or the equivalent in
   whichever implementation survives step 2) that use `REVIEW_GROUPS_CHUNK_CONFIG`.

4. **Sweep hardcoded hex colors in the surviving Review implementation and in
   `main.py`, `history_page.py`, `components/filters/filter_bar.py`,
   `components/dashboard/stats_presence.py`.** For each raw `"#RRGGBB"` or
   `ft.Colors.with_opacity(x, "#RRGGBB")` literal, replace it with the matching token
   from `theme_for_mode(...)` (already imported in most of these files as `self._t` or
   similar) or add a missing token to `design_system/tokens.py` if no equivalent
   exists yet. Do this file-by-file, smallest first, and after each file manually
   sanity-check it renders correctly in both a dark preset and `high_contrast`.

5. **Add `tooltip=` (and `semantics_label=` where Flet supports it) to every icon-only
   IconButton in `main.py`'s custom title bar** (minimize/maximize/close,
   `main.py:308-310`) and to icon-only controls in the nav rail (`layout.py`) and
   Review's view/sort toggle buttons. Keep labels short and action-oriented
   ("Minimize window", "Close Cerebro", "Switch to grid view").

6. **Move "Exclude" from a top-level nav rail entry to a tab/section inside
   Settings.** Update `routes.py` to drop the `exclude` RouteInfo from the primary
   nav, and add an "Exclude list" section within `pages/settings_page.py` that reuses
   the existing `ExcludeListPage` content (don't rewrite its logic — just change where
   it's mounted). Update `main.py`'s `builders` dict and any nav-rail wiring in
   `layout.py` accordingly. Keep the `Ctrl+`-style shortcut working if one currently
   targets Exclude directly.

After each task, run any existing tests (`pytest tests/` if present) and do a manual
`python -m cerebro.v2` smoke pass on the pages you touched before considering the task
done.
```
