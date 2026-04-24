# CEREBRO Redesign Blueprint – Architecture‑Driven Version

**Version:** 2.0  
**Date:** 2026-04-23

---

## 0. Core Architectural Model (NON‑NEGOTIABLE)

### 0.1 State Model

All application behaviour is driven by a **single state object**:

```python
AppState:
    mode: ["idle", "scanning", "results", "review"]
    groups: list              # duplicate groups
    selected_group: optional
    filters: dict             # type, size, date, etc.
    scan_progress: dict       # files scanned, current folder, ETA
    ui: dict                  # e.g., expanded rows, preview visibility
0.2 State Flow
text
User Action → Dispatch → State Update → UI Render
No direct UI mutation. No page‑to‑page data passing.

0.3 Separation of Concerns
Layer	Responsibility
Engine	Scanning, hashing, grouping (no UI imports)
State	Single source of truth
UI	Rendering only – derives everything from state
Coordinator	Side effects (file I/O, background tasks)
0.4 Platform Compatibility
The architecture must support:

Desktop UI (current – Python/Tkinter/CustomTkinter)

Future Web UI (API + frontend, e.g., React/Vue)

No UI‑specific logic in engine. The engine must be callable from both desktop and web via a service layer.

1. Executive Summary
CEREBRO has a strong scanning engine (handles 900k+ files, 98.9% cache hit rate, perceptual image/video dedup). However, the UI architecture is fragile: direct mutations, callback sprawl, and no central state. This redesign:

Fixes usability (search, sort, pagination, previews)

Introduces safety (recycle bin, dry‑run, filter‑aware Smart Select)

Enforces a state‑driven UI (dispatch → update → render)

Prepares for a future web frontend via API

All existing feature requests (image similarity, symlink mode, CLI, treemap, etc.) are retained but re‑framed to fit the new architecture.

2. Priority Matrix (Refined Intent)
Priorities remain P0/P1/P2, but every feature must:

Integrate with the central AppState

Avoid direct UI mutation

Be render‑safe (no redundant redraws)

Work with both desktop and future web targets

Priority	UI + Coordinator Tasks	Engine Tasks
P0 (Sprint 1-2)	Implement AppState, dispatch/reducer, render cycle; remove all direct mutations; add progress indicators; kill brown header; interactive states	Fix 0s bug, hash cache path, log rotation, min file size filter, standardise engine names
P1 (Sprint 3-4)	Unified data grid (search/sort/filter/pagination) for History & Duplicates; Duplicates subsystem (group model, selection, preview); Smart Select toolbar; recycle bin UI; dry‑run mode UI; filter‑aware Smart Select	Recycle bin engine (send2trash); dry‑run simulation; Smart Select rules (newest/oldest/largest/by‑path); symlink/hardlink mode; bundle mutagen; image similarity (pHash)
P2 (Sprint 5-6)	Visual treemap; space reclaimed dashboard; onboarding/empty states; full WCAG accessibility; micro‑interactions	Audio fingerprinting; document dedup; similar folder detection; scan inside archives; scan scheduling; network/NAS support; CLI; incremental scanning; burst mode
3. Sprint Roadmap (Adjusted for Architecture)
Sprint 1 – Foundation + Architecture Lock (Weeks 1-2)
New mandatory tasks (in addition to original P0 items):

Define AppState schema (dataclass or TypedDict)

Implement dispatch(action) → reducer → new state

Create render() function that subscribes to state changes and updates UI

Remove all direct UI mutations (e.g., treeview.insert() outside of render)

Introduce coordinator for side effects (scanning, file operations)

Existing P0 tasks from previous blueprint:

Log rotation fix, 0s bug, hash cache path, min file size filter, progress indicators, kill brown header, interactive states.

Deliverable: A working, state‑driven skeleton. No feature regressions.

Sprint 2 – Unified Data Grid System (Weeks 3-4)
Replace “add search/filter/pagination to History and Duplicates” with:

Build a reusable DataGrid component that:

Takes a list of items (from state) and column definitions

Handles sorting, filtering, pagination internally, but still driven by state actions

Emits dispatch(SORT_CHANGED), dispatch(FILTER_CHANGED), etc.

Apply this grid to:

History page

Duplicates page (group list view)

Also: Build the new Dashboard, navigation restructure, export UI, and bundle mutagen.

Deliverable: Both History and Duplicates pages use the same grid component; filtering/sorting/pagination work without manual UI management.

Sprint 3 – Duplicates Subsystem (Core Feature) (Weeks 5-6)
Treat duplicates as a subsystem with clear data model:

DuplicateGroup: hash, size, file count, recoverable space, list of files

FileMetadata: path, size, modified date, file type, preview data

Implement:

Expandable rows in grid

Per‑group selection (state holds selected groups/files)

Smart Select rules as state transitions

Preview panel (image, text, audio metadata) – async loading, updates state

Filter‑aware Smart Select (only groups fully visible under current filter)

Recycle bin integration and pre‑deletion confirmation

Dry‑run mode (state flag + simulated deletion)

Symlink/hardlink mode

Deliverable: Duplicates page fully functional, safe, and driven by state.

Sprint 4 – Detection Enhancements & CLI (Weeks 7-8)
Image similarity (pHash) – engine returns similarity scores, UI groups near‑duplicates

Burst mode detection – engine returns burst groups, UI shows “Pick Best”

Audio fingerprinting (Chromaprint)

Command‑line interface – calls the same engine and coordinator, no UI

Background scanning with I/O throttle – coordinator manages background thread, updates state via dispatch

Incremental scanning – engine caches timestamps, coordinator decides skip

Deliverable: CEREBRO becomes scriptable and handles photo/music libraries intelligently.

Sprint 5 – Advanced Features & Polish (Weeks 9-10)
Document deduplication (MinHash)

Similar folder detection

Scan inside archives (ZIP, RAR, 7z)

Scan scheduling (cron‑like)

Network/NAS support

Visual treemap of disk usage (state → UI canvas)

Space reclaimed dashboard (gamified trends)

Deliverable: Enterprise‑grade features that beat competitors.

Sprint 6 – Web Transition Prep, Accessibility & Launch (Weeks 11-12)
New: Refactor engine into a service layer with clear API boundaries (no UI imports).

Define REST‑like actions (scan, get results, delete)

Ensure state can be serialised to JSON

Add API stubs (FastAPI or similar) – not yet exposed, but engine is ready.

Existing tasks:

Full WCAG 2.1 AA audit

Micro‑interactions & animations

Empty states & onboarding

Error states & edge cases

End‑to‑end testing with 1M+ files

Documentation & in‑app help

Deliverable: Engine is web‑ready; desktop UI polished and accessible.

4. Critical Features (Reframed for Architecture)
Feature	Architectural Implementation
Dry‑run mode	State flag dry_run: bool; coordinator simulates deletion, updates state with preview results; no actual file system changes
Filter‑aware Smart Select	Operates purely on state: when filter active, compute which duplicate groups have all members visible, then dispatch auto‑selection action on those groups only
Log rotation fix	Engine‑level fix (proper file handler release) – no UI involvement
Recycle bin / restore	Coordinator calls send2trash; restore from rescue folder is a separate coordinator action
Unified data grid	Component that uses state.groups (or state.history) and dispatches sort/filter actions – no duplicated logic
5. Performance Constraints
UI must not block during scan (background thread + state updates every 100ms)

100k+ rows must render via pagination or virtual scrolling

Image loading must be async (use threading or concurrent.futures)

One render per state change – no redundant redraws

6. Web Transition Path (Phased)
Phase	Work
Phase 1 (Sprint 6)	Refactor engine to service layer; no UI dependencies; define API actions
Phase 2 (Future – Week 13+)	Expose HTTP API (FastAPI) with endpoints: POST /scan, GET /results, POST /delete
Phase 3 (Future)	Build web frontend (React/Vue) that calls the API and manages its own state (could reuse same state schema)
Phase 4 (Future)	Deprecate desktop UI once web frontend reaches feature parity
During this redesign: Do not break the desktop UI. The service layer must work for both.

7. Acceptance Criteria (Expanded)
UI reflects state with no manual sync – a single render() call after each dispatch

No duplicated data sources (e.g., no separate self.tree_data variable)

Async operations never block UI thread

No cross‑component direct communication – everything goes through state and coordinator

All P0 bugs fixed (log rotation, 0s, hash cache, min file size)

Dry‑run mode works (preview without changes)

Filter‑aware Smart Select never selects incomplete groups

History and Duplicates pages support search/sort/filter/pagination

Deleted files go to Recycle Bin (or Rescue folder) and are restorable

WCAG 2.1 AA passes

Engine can be imported and used without UI (proven by CLI)

8. Failure Conditions
The redesign is considered failed if after completion:

UI requires manual syncing between pages (e.g., after deletion, the results page must be manually refreshed)

State is duplicated (e.g., same data stored in two different objects that can drift)

Rendering causes flicker or blocking (main thread blocked for >100ms)

Logic exists outside state transitions (e.g., a button click directly modifies a treeview instead of dispatching an action)

9. Final Principle
The UI does not control the system.
The system state defines the UI.

End of blueprint