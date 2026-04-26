# Cerebro Duplicate File Finder — UI/UX Modernization Plan

> **Scope contract:** This plan touches **presentation only**. The `TurboFileEngine`, scan logic, hashing, and any backend/data flow stay completely untouched. Engine changes — if ever needed — are isolated to **Phase 7 (optional)** with explicit justification.

---

## 🚦 Completion Tracker

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 0** | Foundation: Design Token System & Theme Engine | ✅ Complete |
| **Phase 1** | The Shell: Title Bar, Sidebar, Window Chrome | ✅ Complete |
| **Phase 2** | Home Page Redesign | ✅ Complete |
| **Phase 3** | Results Page Redesign | ✅ Complete |
| **Phase 4** | Review Page (Visual Grid) Redesign | ✅ Complete |
| **Phase 5** | History & Settings Polish | ⬜ Pending |
| **Phase 6** | Motion, Micro-interactions & Polish Pass | ⬜ Pending |
| **Phase 7** | *(Optional)* Engine-Adjacent Performance UX | ⬜ Optional |

---

## 1. Honest Audit — What's Wrong Right Now

Looking at the current screenshots, the app's functionality is solid but the visual language reads as **late-2000s Tkinter / generic Qt default**, not 2026 desktop software. Specific problems:

### 1.1 Visual / Aesthetic Issues
- **Flat washed-out grey backgrounds** (`#f0f0f0`-ish) on every panel — no depth, no layering, no character.
- **Pill-shaped grey buttons with no hierarchy** — "Files / Folders / Compare / Music / Unique" all look identical and equally important. A user can't tell which is the active tab vs. which is a filter.
- **Inconsistent corner radii** — some elements 16px, some 4px, some sharp. No visual rhythm.
- **Title bar is a hard navy slab** that clashes with the light grey body. Looks like two apps glued together.
- **Sidebar icons are tiny and floating in whitespace** — no active-state indicator beyond a faint rounded background. No section dividers.
- **Empty hero area at the top of Home** wastes ~25% of vertical space showing nothing.
- **KPI cards (`Scans Run / Duplicates Found / Space Recovered`)** are flat boxes — no iconography, no color accent, no trend, just numbers floating.
- **Recent Scans rows are visually identical to each other** — no hover affordance, no grouping by date, no thumbnails.
- **Results page lists files with a generic blue-on-grey color** with checkboxes that look like Windows 95.
- **Review grid thumbnails sit in flat boxes** with no shadows, no hover zoom, no selection state.
- **Settings tabs are cramped pills** with no iconography; the saved/cancel buttons at the bottom right are sage green for no apparent reason.

### 1.2 UX / Interaction Issues
- **No clear primary action** anywhere — `Browse Folders`, `Start Scan`, `Open Last Session` all weigh the same.
- **`Start Scan` stays grey even when folders are added** — no "ready" state.
- **No live scan feedback** beyond a thin progress bar and "2,980 files scanned · 0.0s" — no current-folder indicator, no ETA, no rate.
- **Smart Select dropdown with `Apply` button is a 3-step interaction** for what should be one tap.
- **No empty states** — no folders selected just shows a disabled grey pill saying "No folders selected". Should be inviting.
- **No keyboard shortcuts surfaced** anywhere.
- **History table is raw spreadsheet** — no grouping by day, no visual size bar, no quick re-run action.

### 1.3 What's Already Good (preserve these)
- The **information architecture** is correct — Home / Results / Review / History / Settings is the right split.
- The **Smart Select preset system** is a great idea, just buried.
- The **35 custom themes** infrastructure exists — we just need to wire it into a proper design token system.
- **Navy + cyan** as a brand direction works; we just need to use it intentionally.

---

## 2. Design Direction — Where We're Going

A **modern, slightly-glassmorphic, dark-first desktop app** with a navy-to-deep-indigo gradient base, cyan/teal as the action color, and subtle neon accents on hover/focus — drawing on the same aesthetic family Steve already gravitates toward (Hyprland/NixOS-style desktops, glass UI, neon highlights). Crucially, this is **professional polish, not gamer chrome** — the goal is "looks like a 2026 native app from a small premium software studio," not "RGB everything."

**Inspiration north stars:**
- Linear's density and typography
- Raycast's command surfaces and keyboard-first feel
- Arc Browser's color theming
- macOS Sonoma's translucency
- Modern Files-app conventions (Files by Files, Directory Opus 13)

**Design pillars:**
1. **Depth through translucency**, not borders — frosted panels over a tinted gradient background.
2. **One primary color per screen** — the action you should take is unmissable.
3. **Information density with breathing room** — Linear-style: tight rows, generous padding around groups.
4. **Motion as feedback** — every state change has a 150–200ms easing transition.
5. **Theme-driven, not hardcoded** — every color goes through `design_tokens.py`.

---

## 3. Phased Plan

The work is split into **6 UI-only phases + 1 optional engine phase**. Each phase ships independently, each is reversible, and each delivers a visible improvement on its own.

---

### **Phase 0 — Foundation: Design Token System & Theme Engine** *(2–3 days)*

**Goal:** Make every subsequent phase fast and theme-safe. No visible UI change yet, but everything downstream depends on this.

**Why first:** You already have 35 themes and a `design_tokens.py` from the legacy CTk repo. The v2 PySide6 build needs a consolidated equivalent before we redesign anything, otherwise every Phase 1+ change has to be re-skinned 35 times.

**Tasks:**
- Create `cerebro/ui/theme/` package:
  - `tokens.py` — single source of truth for spacing (4/8/12/16/24/32), radii (6/10/14/20), shadows (sm/md/lg/xl), font scale, motion durations.
  - `palette.py` — semantic color roles: `bg.base`, `bg.elevated`, `bg.glass`, `surface.hover`, `border.subtle`, `border.strong`, `accent.primary`, `accent.hover`, `text.primary`, `text.secondary`, `text.muted`, `state.success`, `state.warning`, `state.danger`.
  - `themes/` directory with all 35 theme JSON/Python files mapping each theme's hex values to those semantic roles.
  - `theme_manager.py` — loads active theme, emits `themeChanged` signal, every widget subscribes.
- Refactor existing widgets to consume tokens (no visual redesign yet — just `QPushButton { background: #aaa }` → `QPushButton { background: {accent.primary} }`).
- Add a **dark mode by default** — current screens look like forced light mode.
- Wire `theme_manager` into `MainWindow` and propagate via signal so `BaseStation` and all pages respond (this directly fixes the known propagation bug in your memory).

**Deliverable:** Same-looking app, but every color/spacing value comes from tokens. Switching themes in Settings instantly repaints everything including BaseStation.

**Risk:** Low. Pure refactor.

---

### **Phase 1 — The Shell: Title Bar, Sidebar, Window Chrome** *(2–3 days)*

**Goal:** Replace the dated window frame with a custom modern shell. This is the highest-impact-per-hour change — users see it before anything else.

**Tasks:**
- **Custom frameless window** with a transparent rounded outer shape (12px radius), a subtle 1px border, and a drop shadow.
- **Custom title bar** — same color as the body (no more navy slab), 36px tall, with:
  - App icon + "Cerebro" wordmark on the left
  - Centered breadcrumb showing current section ("Home" / "Scan Results — 150 groups" / etc.)
  - Macos-style traffic-light buttons OR Windows-style controls, themed to match (your choice, but matched to the OS conventions)
- **Redesigned sidebar** (72–84px wide, expandable to 220px on hover):
  - Larger icons (24px), each with a 1–2 word label below
  - Active item: filled cyan/accent pill with a 3px left bar, glowing subtle shadow
  - Hover: surface lifts with a subtle scale + bg tint
  - Group dividers: "Workspace" (Home, Results, Review) and "Library" (History) and a bottom-pinned Settings
  - Add a "What's New" / version badge at the bottom
- **Apply a tinted gradient background** to the window body — e.g. `bg.base` deepening 6% toward the bottom-right. Subtle, not dramatic.
- **Add a faint noise/grain texture** overlay (3% opacity) to kill banding on the gradient — this single trick is what makes apps feel "premium" vs. "amateur."

**Deliverable:** App opens and immediately feels like a 2026 product before the user clicks anything.

**Risk:** Medium. Frameless windows on Windows need careful handling for snap, maximize, and DPI. Use `qframelesswindow` library or roll a tested implementation.

---

### **Phase 2 — Home Page Redesign** *(2 days)*

**Goal:** Turn the home page from a parking lot into a dashboard.

**Tasks:**
- **Kill the empty hero area.** Replace with a compact greeting + quick-stat strip:
  > "Welcome back, Steve — you've reclaimed **1.6 GB** across **11 scans**."
- **Redesign the 3 KPI cards:**
  - Glassmorphic surfaces with `backdrop-filter: blur` equivalent (PySide6: layered semi-transparent widgets + a `QGraphicsBlurEffect` on a snapshot, or just a high-opacity tinted surface).
  - Each card gets an icon (search, copy, hard-drive), the number large in the brand font, a sub-label, and a tiny sparkline showing the last 7 scans' trend.
  - Hover: card lifts 2px with shadow.
- **Redesign the action cluster:**
  - **Promote `Start Scan` to the primary CTA** — large, accent-filled, with a play icon. Disabled state is clearly differentiated (40% opacity + lock icon), enabled state has a subtle accent glow.
  - `Browse Folders` becomes a secondary outlined button.
  - `Open Last Session` becomes a tertiary text-button with a clock icon.
- **Folder chips redesign:**
  - When folders are selected, show them as elevated chips with a folder icon, the path (truncated middle: `C:\...\Documents\Rainmeter`), file count, and a small × button.
  - The `Quick Add` row becomes more visual: each preset is a small card with a folder icon in its theme color (Documents = blue, Music = purple, Videos = pink, etc.).
- **Recent Scans redesign:**
  - Group by day with date pills ("Today", "Yesterday", "Apr 25").
  - Each row: a small thumbnail icon (file-type breakdown donut), the timestamp, group/file counts as colored chips, recoverable size, and on hover: `Re-run` and `Open results` buttons slide in from the right.
  - Click anywhere on the row → opens those results.

**Deliverable:** Home page becomes the most-loved screen instead of the most-skipped one.

**Risk:** Low. Pure presentational rework.

---

### **Phase 3 — Results Page Redesign** *(3 days)*

**Goal:** This is where users spend the most time. Make it feel like Linear's issue list, not a 2002 file dialog.

**Tasks:**
- **New action bar:**
  - Sticky top bar with: selection summary ("**4,231 files selected · 1.2 GB**"), Smart Select dropdown (now a clean segmented control, not dropdown+Apply), and the destructive actions on the far right with proper hierarchy:
    - `Move to Trash` — secondary danger style (red outlined, not solid)
    - `Delete Permanently` — only red-filled when explicitly armed (click first → confirm-state with countdown)
- **Filter tabs** (`All / Images / Music / Videos / Docs / Archives / Other`):
  - Convert to a proper segmented control with file counts in muted text per tab: `Images · 87`
  - Active tab: filled accent background, white text, soft glow
- **Group rows redesign:**
  - Replace the flat blue "icon-icon" placeholder with a real **stacked-thumbnail preview** (for images: actual mini-thumb of the duplicate; for other files: type icon in a tinted square).
  - Path display: parent folder bolded, rest muted, with a subtle `→` to the path to make the hierarchy readable.
  - Right side: total recoverable size in accent color, expand chevron, a quick-preview eye icon.
  - Hover: surface lightens 4%, drop shadow appears.
  - Expanded state: each duplicate as an indented row with checkbox, filename, size, modified date, full path (collapsible), and a `Reveal in Explorer` action.
- **Add a master selector** at the top: "Select all in this category" with smart logic (select all but largest / oldest / etc.).
- **Add inline filters/sort:** size descending, date, name, group size — as a small icon row, not a hidden menu.
- **Animations:** Group expand/collapse with smooth 200ms ease, deletion with fade-out + height collapse.

**Deliverable:** The page where users spend 80% of their time finally feels worth it.

**Risk:** Low-Medium. Just be careful that virtualized list performance doesn't regress with the richer rows — keep using `QListView` with a custom delegate, not 1000 widgets.

---

### **Phase 4 — Review Page (Visual Grid) Redesign** *(2 days)*

**Goal:** The review grid should feel like Apple Photos, not a stale thumbnail browser.

**Tasks:**
- **Card-based grid** with consistent 1:1 aspect, 12px gap, rounded corners, subtle border, hover-lift effect.
- **Selection state:** selected cards get an accent border + a checkmark badge in the top-right corner with a soft glow.
- **Hover:** card scales 1.02, shadow deepens, a tiny info bar slides up from the bottom showing filename + size.
- **Larger thumbnails by default** (current ones are tiny). Add a zoom slider in the header (3 sizes: S / M / L).
- **Group dividers:** subtle horizontal rule between duplicate sets with a tiny "Set 1 of 87 · 4 files · 11.8 KB" label.
- **Lightbox preview on double-click** — full-screen image viewer with arrow-key navigation between duplicates and a side-by-side compare mode for 2-up viewing.
- **Smart Select bar** matches the new Results page styling.
- **Lazy-load thumbnails** with a shimmering skeleton placeholder, not blank squares.

**Deliverable:** Reviewing duplicates becomes pleasant instead of a chore.

**Risk:** Low. Pure presentation.

---

### **Phase 5 — History & Settings Polish** *(2 days)*

**Goal:** The lower-traffic pages shouldn't feel like an afterthought.

**Tasks:**

**History:**
- Convert the spreadsheet table into a **timeline view**:
  - Vertical timeline with date pills on the left, scan cards on the right.
  - Each card: mode badge (Files/Folders/Music), folders as chips, a horizontal bar showing relative size, duration as a small timer pill.
  - Hover: `Re-run with same folders` and `View results` actions appear.
- Add a **stats summary at the top:** total scans, total reclaimed, average duration, etc., in mini cards.
- Keep a `Table view` toggle for power users who want the spreadsheet.

**Settings:**
- **Tab redesign:** vertical tabs on the left (icons + labels), content on the right — current horizontal pills feel cramped.
- **Sectioned forms** with section headers, descriptions under each setting (not just labels).
- **Theme picker (Appearance tab):**
  - Each theme is a card showing a mini preview of the actual UI in that theme (3 colored circles + a tiny mock window), not just a colored rectangle.
  - Live preview: hover over a theme card → entire app previews it for 1 second; click to commit.
- **About tab:** add a proper "About" with version, GitHub link, credits, and a fun "thanks for using Cerebro" easter egg.
- **Save/Cancel buttons:** the sage green doesn't fit. Make Save the accent color (filled) and Cancel a ghost button. Sticky at the bottom of the panel.

**Risk:** Low.

---

### **Phase 6 — Motion, Micro-interactions, and Polish Pass** *(2 days)*

**Goal:** The 1% details that separate "redesigned" from "loved."

**Tasks:**
- **Toast notifications** for completed actions ("123 files moved to Trash · Undo"). Slide in from bottom-right, auto-dismiss in 5s, undo button.
- **Loading skeletons** instead of spinners while results stream in.
- **Confetti / subtle celebration** when a scan reclaims > 1 GB.
- **Keyboard shortcuts:** `Ctrl+,` for settings, `Ctrl+N` new scan, `Ctrl+R` re-run, `Space` to preview, arrows to navigate. Add a `?` overlay showing all shortcuts.
- **Command palette** (`Ctrl+K`) Raycast-style — search any folder, recent scan, or action.
- **Empty states with personality** — "No duplicates found 🎉 Your drive is squeaky clean."
- **Sound effects (opt-in, off by default)** — soft "ding" on scan complete, subtle click on actions.
- **First-run onboarding overlay** — 3-step coach mark sequence pointing out: select folders here, scan starts here, review results here.
- **Preferences for animation reduce** — respect OS-level "reduce motion" setting.
- **Window state persistence** — remember size, position, maximized state per session.

**Risk:** Low. Pure additive polish.

---

### **Phase 7 — OPTIONAL: Engine-Adjacent Performance UX** *(only if needed)*

> **This is the only phase that may touch the engine, and only via additive read-only signals — no scan logic changes.**

**Goal:** Make the scan progress feel as fast as it actually is.

**Tasks:**
- **Engine emits richer progress signals** (additive only, no behavior change):
  - `currentFolderChanged(path)` — show "Scanning: `C:\...\OneDrive\Documents`" inline
  - `scanRateChanged(files_per_sec)` — show "12,400 files/sec"
  - `etaChanged(seconds)` — show "~14s remaining"
  - `phaseChanged(phase)` — "Indexing → Hashing → Comparing → Done"
- UI consumes those signals and shows a richer scan dashboard with phase pills and a real progress curve.
- **No changes to hashing, comparison, or threading logic.**

**Risk:** Medium. This is the only phase where engine code is touched. Justify only if Phase 0–6 reveal that progress feedback is genuinely unsalvageable without it.

---

## 4. What Stays Untouched (Engine Contract)

To be unambiguous, the following are **off-limits** for Phases 0–6:

- `TurboFileEngine` and any file traversal / hashing logic
- Database schema, scan persistence format, history storage
- File deletion / trash logic
- Thread pool configuration and concurrency model
- Any non-UI module under the data/scan layer
- File comparison algorithms

The contract: **every page will look completely different, but every byte of engine output will be identical.**

---

## 5. Suggested Order of Execution

If shipping incrementally to dogfood:

1. **Phase 0** (foundation — invisible but enables everything)
2. **Phase 1** (shell — biggest "wow" per hour)
3. **Phase 2** (home — first impression locked in)
4. **Phase 3** (results — main workflow)
5. **Phase 4** (review — secondary workflow)
6. **Phase 5** (history + settings — completes the surface area)
7. **Phase 6** (polish pass — the 1% that ships the product)
8. **Phase 7** (only if Phase 6 review reveals progress UX is still weak)

**Total estimated time:** ~13–17 days of focused UI work for Phases 0–6. Each phase is independently shippable.

---

## 6. Tooling & Library Recommendations (PySide6)

- **`qframelesswindow`** — for the custom title bar in Phase 1
- **`QPropertyAnimation` + `QGraphicsOpacityEffect`** — for the animation work, no extra deps needed
- **`QSvgRenderer`** — render Lucide / Phosphor icons sharply at every DPI instead of bitmap PNGs
- **Custom `QStyledItemDelegate`s** for the rich list rows in Phases 3 & 4 (don't use widget-per-row)
- Add a `cerebro/ui/components/` library: `Card`, `Chip`, `IconButton`, `PrimaryButton`, `SecondaryButton`, `GhostButton`, `SegmentedControl`, `Toast`, `Skeleton`, `EmptyState`. Build once, reuse everywhere.

---

## 7. Success Criteria

The redesign is done when:

- A new user opens the app and **doesn't immediately think "this is built with Tkinter."**
- Every screen has **one obvious primary action.**
- All 35 themes work correctly across every page including BaseStation.
- The engine output is **bit-for-bit identical** to the current build.
- Steve actually enjoys opening the app.

---

*Plan version 1.0 · Generated for Cerebro v2 (Perps12-oss/silver-octo-pancake)*
