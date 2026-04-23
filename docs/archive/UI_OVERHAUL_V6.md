# UI Overhaul v6 — Branch rules, architecture, and plan

**Branch:** `ui/overhaul-v6` (from stable `main`)

---

## 0) Branch setup (done)

```bash
git checkout main
git pull
git checkout -b ui/overhaul-v6
git push -u origin ui/overhaul-v6
```

### Rules for this branch

- **Core scanning stays untouched** (unless absolutely required).
- **UI changes can be large.**
- **App must stay runnable at every checkpoint** (compiles + opens).

---

## 1) Target architecture (hard separation)

| Layer | Responsibility |
|-------|-----------------|
| **UI** (Qt only) | Layout, visuals, navigation, animation, widgets. Reads state via controller snapshot/bus. **No filesystem/scanning logic inside UI.** |
| **Application** (controllers) | LiveScanController, state snapshot, bus publishing. Orchestration only. |
| **Domain / core** | Pipeline, scanners, models, history. |

**Goal:** UI can be replaced without touching core.

---

## 2) New folder layout (UI-only)

```
cerebro/ui/
  shell/           → AppShell chrome, topbar/sidebar, routing host
    nav/
    chrome/
  theme/           → ThemeEngine, tokens, palette, stylesheets
  components/      → Reusable UI kit (cards, buttons, panels)
    layout/
    cards/
    inputs/
    feedback/
  pages/           → Mission / Scan / Review / History / Settings / Themes (thin)
  controllers/     → (already exists; keep)
  assets/           → Icons, images
```

---

## 3) Overhaul plan (phased, always runnable)

### Phase A — New Shell (routing + chrome)

**Deliverables:** AppShell (or AppShellV2) with:

- Sidebar navigation
- Top toolbar
- Content stack (QStackedWidget)
- Status / toast area

**Checkpoint A:** App opens, navigation works, old pages still render in new shell.

---

### Phase B — Rebuild pages as “thin screens”

Each page: UI layout + bind to controller snapshot/bus; no heavy logic.

**Order:** StartPage → ScanPage → ReviewPage → History / Settings / Themes.

**Checkpoint B:** Start → Scan → Review navigation is solid.

---

### Phase C — Real UI kit

Extract: Card, StatCard, SectionHeader, PrimaryButton, DangerButton, GlassPanel, SidebarNav, Toast. Unified spacing + typography.

**Checkpoint C:** UI consistency “snaps” into place.

---

### Phase D — Animation + polish

Subtle transitions, progress pulse/shimmer, hover glows, loading skeletons.

**Checkpoint D:** “Gemini feel,” still fast.

---

## 4) Guard rails (non‑negotiables)

- **No page imports core directly** (`cerebro.core.*`). Pages talk only to controllers or bus.
- **Only one publisher to bus:** controllers.
- **Never block UI thread:** any I/O/scan stays in workers.

### Before each commit

```bash
python -m py_compile cerebro/ui/former monolithic UI module (deleted)
python -m py_compile cerebro/ui/pages/scan_page.py
python -m py_compile cerebro/ui/controllers/live_scan_controller.py
python main.py
```

---

## 5) Cursor prompt (senior architect — paste into Cursor)

```
CEREBRO UI Overhaul (UI-only rewrite, keep engine stable)

Goal:
Replace the entire UI shell with a clean modern navigation-first design, while preserving the existing controller/bus/worker architecture.

Constraints:
- Do not change core scanning, history, or worker logic unless required for wiring.
- Controller remains the sole publisher to the bus.
- Pages must be thin (layout + binding only).
- App must remain runnable after each commit.

Tasks:
1) Create a new UI shell:
- AppShell hosts: SidebarNav + TopToolbar + QStackedWidget content + Status/Toast area.
- Provide navigate_to(station_id) API.
- Route station ids: mission, scan, review, history, themes, settings.

2) Refactor pages to match shell:
- Each page exposes station_id and emits navigate_requested(str).
- Each page binds to controller.snapshot_updated and bus events as needed.
- No direct core imports from pages.

3) Build minimal UI kit:
- Card / StatCard
- PrimaryButton / DangerButton
- SectionHeader
- GlassPanel (optional)

Deliver:
- Minimal number of files changed per step
- Provide unified diffs
- Ensure python -m py_compile passes for changed files
```

---

## PROJECT GOAL (Gemini 2 clone)

Refactor the project into a **premium Windows-only duplicate finder** that looks, feels, and behaves like **MacPaw Gemini 2 Duplicate Finder** (Red Dot design: same colors, spacing, animations, drag-drop hero, sidebar, results cards).

### CRITICAL RULE — DO NOT LOSE ANY FUNCTIONALITY

Preserve **100%** of every feature. Do not remove, simplify, hide, or comment out anything. Keep every scanner engine, controller, signal, and backend class. Only reorganize files and enhance the UI to surface every feature visibly and elegantly.

### FEATURES TO PRESERVE AND DISPLAY

- Turbo / Ultra / Quantum scanner modes (visible scanner selector in toolbar or scan page)
- Live Scan Controller: real-time file list, speed, ETA, files scanned
- Progress visualization (animated progress bar + stats cards)
- Smart Select (prominent button + tooltip)
- Deletion Gate + safe-to-delete badges on duplicate groups
- Full Preview Pane (image/video/pdf/text, zoom, side-by-side)
- History: export, timeline, search
- Audit Log: deletion records, undo
- Hub: dashboard, stats, quick actions, recent scans
- Settings: theme toggle, scan options, performance, exclusions, cache
- Drag & drop on every page with visual feedback
- Advanced scan options (file types, size, similarity, hash depth)
- Clustering/grouping with expand/collapse
- Thumbnail caching + fast image grid
- Bottom action bar (Select All Safe, Delete Selected, Export List)
- All signals, state bus, session store, logger

### STEP-BY-STEP (order)

1. **Reorganize package structure** (before other changes):
   - Ensure: `cerebro/core/`, `cerebro/ui/pages/`, `cerebro/ui/widgets/`, `cerebro/config/`, `cerebro/data/`
   - Add `__init__.py` to every folder
   - Backend → `cerebro/core/`; UI pages → `cerebro/ui/pages/`; widgets → `cerebro/ui/widgets/`; app_shell + theme_engine → `cerebro/ui/`
   - Keep `main.py` at root

2. **Replace main.py** with Windows-only entry point (platform guard).

3. **Theme:** Windows-tuned Gemini theme (e.g. Segoe UI, #00C4B4 accent).

4. **Heavy UI refactor:**
   - Start: drag-drop hero, sidebar “Locations”, “+ Add Folder”, scanner mode selector
   - Scan: header, progress bar, live stats, live file panel, scanner switcher, Cancel
   - Review: grouped cards, thumbnails, Smart Select, safe-delete badges, preview pane, bottom action bar
   - History / Audit / Hub / Settings: full functionality, Gemini-style panels
   - Global toolbar: Scanner Mode, New Scan, History, Audit, Settings, Theme, Help
   - Smart Select and Deletion Gate prominent; subtle Windows 11 animations

5. **After moves:** Fix all imports (`cerebro.` prefix); ensure `python main.py` launches on Windows.

6. **Polish:** Thumbnail caching, tooltips, responsive panels; keep backend/threads untouched.

### VERIFICATION

- Every original feature present and visible
- Look and flow aligned with Gemini 2
- No functionality lost
- Windows-only
- Scanners, Smart Select, Deletion Gate, History, etc. work as before

**Output:** “✅ All features preserved and exposed. Changed files: [list]”
