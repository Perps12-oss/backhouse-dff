# Project Cerebro: Flet Migration Blueprint (Historical)

Status: Migration delivered. The live UI is now under
`cerebro/v2/ui/flet_app/`.

Objective: Rebuild the UI with Flet (Flutter) for a modern, responsive,
glass-morphic aesthetic.
Constraint: Keep all existing logic, scanning engines, and state management
intact. Remove all Tkinter dependencies from the new UI layer.

Phase 0: The Great Divorce (Preparation)
Goal: Ensure the core logic is completely independent of the UI.

0.1 Verify Engine Isolation
Inspect cerebro/engines/.
Action: Search for import tkinter or import tk.
Requirement: If found in engine files, remove it. Engines should only return data structures (dictionaries/lists). They should not know about windows or widgets.
Checkpoint: You should be able to run a script that imports CerebroEngine, calls scan(), and prints results to the console without a GUI opening.
0.2 Verify State Management
Inspect cerebro/v2/state/.
Action: Ensure StateStore and AppState do not depend on UI classes.
Requirement: The state store should be a pure Python class managing data.
Checkpoint: You can manually dispatch an action to the store and verify the state changed via a print statement.
Phase 1: The Foundation (Flet Setup)
Goal: Set up the new project structure and get a blank modern window running.

1.1 Project Structure
Create a new directory structure to separate the old and new, or update the existing one:

text

cerebro/
├── engines/          # [KEEP] Existing engines
├── v2/
│   ├── state/        # [KEEP] Existing state logic
│   └── ui/
│       ├── old_tk/   # [ARCHIVE] Move old tkinter code here
│       └── flet_app/ # [NEW] The new UI lives here
│           ├── main.py
│           ├── pages/
│           ├── components/
│           └── theme.py
└── main.py           # Entry point
1.2 Dependencies
Create/Update requirements.txt.
Add flet.
Action: Run pip install -r requirements.txt.
1.3 The "Hello World" Modern Shell
Create cerebro/v2/ui/flet_app/main.py.
Action: Implement a basic ft.app with a modern theme setup.
Set page.theme_mode.
Set page.window_width, page.window_height, page.title.
Apply a ft.Theme(color_scheme_seed="blue").
Checkpoint: Run the app. You should see a blank, modern window.
Phase 2: The Bridge (Connecting Logic to UI)
Goal: Create a service layer that allows Flet to talk to your existing Engines and State Store.

2.1 The Backend Service
Create cerebro/v2/ui/flet_app/services/backend_service.py.
Action: Create a class BackendService:
Initialize your CerebroCoordinator or CerebroEngine.
Expose methods: start_scan(path), get_results(), delete_groups(ids), open_file(path).
Threading Logic:
Crucial: Scanning is blocking. Flet is async.
Implement start_scan to run in a separate thread using threading.Thread.
Use a callback or simple polling to update the UI when scanning finishes.
2.2 The State Bridge
Create cerebro/v2/ui/flet_app/services/state_bridge.py.
Action: Create a wrapper that listens to your existing StateStore.
Since Flet controls its own UI, we will use the State Store to hold the "Truth" and simply trigger a UI refresh function (page.update()) when the store changes.
Phase 3: The Skeleton (Navigation & Layout)
Goal: Build the main application frame that matches your current features (Results, Review, Settings).

3.1 Navigation Rail
Create cerebro/v2/ui/flet_app/components/nav_rail.py.
Action: Implement a ft.NavigationRail with destinations:
Scan/Results (Home Icon)
Review (Grid View Icon)
Settings (Settings Icon)
Checkpoint: Clicking icons changes the main content area of the app.
3.2 Route Management
In main.py, implement a simple routing system (e.g., route="/results" vs route="/review").
Action: Create functions view_results() and view_review() that clear the main container and load the respective view.
Phase 4: Functionality - Scan & Results (List View)
Goal: Replicate the old ResultsPage.

4.1 The Scan Interface
Create cerebro/v2/ui/flet_app/pages/scan_page.py.
Components:
ft.TextField for path input.
ft.ElevatedButton "Start Scan".
ft.ProgressBar (hidden initially).
Logic:
On button click -> Call BackendService.start_scan (in thread).
Update Progress Bar status (requires page.run_thread or periodic UI updates).
On finish -> Navigate to Results.
4.2 The Results List
Create cerebro/v2/ui/flet_app/pages/results_page.py.
Components:
ft.ListView or ft.DataTable.
Filter Bar (Tabs for: All, Images, Docs, etc.).
Mapping:
Map DuplicateGroup objects to ft.ListTile.
Display: Filename, Count, Size, Path.
Interactivity:
"Review Group" button -> Navigates to ReviewPage passing group_id.
"Delete" button -> Calls BackendService.delete_group.
Phase 5: Functionality - Visual Triage (Review Page)
Goal: Replicate the complex ReviewPage (Grid + Compare). This is the hardest part.

5.1 The Grid View (Virtualization)
Note: Tkinter used a custom VirtualThumbGrid. Flet has GridView which is performant, but we must handle images carefully.

Create cerebro/v2/ui/flet_app/pages/review_page.py.
Layout:
Top Bar: Back button, Breadcrumbs (Group ID), Summary.
Filter Bar: (Re-use the logic from old _FilterListBar but map to ft.SegmentedButton).
Main Body: ft.GridView.
The Tile Component:
Create components/file_tile.py.
Content: An ft.Image (thumbnail) + ft.Text (Filename) + ft.IconButton (Select/Compare).
Optimization: Thumbnails should be generated by the engine. If the engine doesn't have them, generate them in the background thread.
5.2 The Compare View (Side-by-Side)
Create components/compare_panel.py.
Layout: A ft.Row with two ft.Container panels (Left and Right).
Features:
Side A Image + Metadata.
Side B Image + Metadata.
Actions: "Keep A", "Keep B", "Delete Both".
Navigation:
Left/Right arrow buttons to load the next/previous pair.
Phase 6: Polish & Theming
Goal: Make it look like a high-end SaaS product.

6.1 Define Colors
Create theme.py.
Define your palette (_ACCENT, _NAVY_MID, _GLASS_BG).
Map these to Flet's ft.Colors or hex codes.
Glassmorphism:
Apply blur=10 and bgcolor=ft.colors.with_opacity(0.5, ...) to containers to achieve the glass look.
6.2 Dark Mode
Flet handles this natively via page.theme_mode.
Action: Ensure your color definitions in theme.py have light and dark variants.
6.3 Animations
Page Transitions: Wrap your route changes in a container that animates opacity/scale.
Hover Effects: Flet buttons have hover_color. Ensure these are set to on_primary or similar for a tactile feel.
Feature Checklist (Verification)
Use this list to ensure functionality parity with the old Tkinter app.

Feature
Status
Notes
Scanning	⬜	Recursive folder scan, progress reporting.
Grouping	⬜	Hash-based duplicate grouping.
Results List	⬜	Display all groups, filter by extension.
Visual Grid	⬜	Thumbnail view of all files in a group.
Comparison	⬜	Side-by-side view (A vs B).
Selection	⬜	Select individual files or whole groups.
Deletion	⬜	Move to Trash or Permanent Delete.
Open in Explorer	⬜	Cross-platform file explorer launching.
Theming	⬜	Light/Dark mode switcher.
Keyboard Nav	⬜	Arrow keys in Compare view.

Cursor Workflow Tips
Since you are using Cursor, here is the optimal way to execute this plan:

Create a Blueprint.md file in your root and paste this content.
Start with Phase 0. Highlight the text for "Phase 0: The Great Divorce" and ask Cursor: "Help me refactor the engine files to remove all tkinter imports."
Commit. "Phase 0 Complete: Engines decoupled."
Move to Phase 1. Highlight "Phase 1" text. Ask Cursor: "Generate the file structure for a Flet app and the main.py boilerplate."
Commit. "Phase 1 Complete: Flet shell running."
Iterate. Do not jump ahead. Build the Scan page before the Results page. Build the Results page before the Review page.

Review & Enhancement of Your Flet Migration Blueprint
Your plan is solid—clear phases, good separation of concerns, and a realistic focus on keeping the existing engine untouched. That’s exactly the right approach. Below are my observations and concrete enhancements to make the migration smoother and the final UI even more polished.

Strengths (keep doing these)
Phase 0 (The Great Divorce) is mandatory and correctly prioritized.

Threading awareness – you explicitly call out blocking scans and the need for async/threads.

Virtualization – you note that Flet’s GridView is performant, but careful handling of images is required. Good.

Feature parity checklist – excellent for tracking progress.

Gaps & Potential Pitfalls
Async ≠ Threads directly
Flet uses asyncio. Starting a blocking scan in a separate thread is fine, but communicating back to the UI requires page.run_thread or a queue + periodic page.update(). Your plan says “callback or simple polling” – be explicit: use asyncio.run_coroutine_threadsafe or a queue that the main loop checks every page.add_timeout(0.1).
Enhancement: In BackendService.start_scan, accept an on_progress coroutine and call it via asyncio.run_coroutine_threadsafe from the worker thread.

State Bridge Complexity
You already have a StateStore that is pure Python. Instead of rebuilding it inside Flet, keep it as the single source of truth and sync it one‑way to Flet’s UI components.
Enhancement: Make your state store observable (e.g., use blinker or a simple callback list). In Flet’s main.py, subscribe to state changes and call page.update(). Do not try to mirror the state into Flet’s own page.session – that leads to duplication.

Missing: Cancellation
The old UI had a “Stop Scan” button. Your plan mentions progress reporting but not cancellation.
Enhancement: Add BackendService.cancel_scan() that sets an Event flag. The scanning thread checks it periodically and raises CancelledError.

Thumbnail Generation & Caching
VirtualThumbGrid in Tkinter used lazy‑decoded, LRU‑cached thumbnails. Flet’s GridView loads images over the network by URL, but you’ll generate thumbnails locally.
Enhancement:

Create a ThumbnailCache service that generates thumbnails in a thread pool and writes them to a temporary directory.

Serve them via a local HTTP server (Flet’s page.get_upload_url is not for this; instead, use flet.WebSocket or simply convert images to base64 and send inline). Better: use ft.Image(src_base64=...).

Cache aggressively – 200k files will otherwise kill performance.

Delete “Ceremony” (Confirmation Dialogs)
The old code had a multi‑step delete process (e.g., “Move to Trash” vs “Permanent”). Your plan only mentions “Delete button calls delete_group”.
Enhancement:

In Flet, use ft.AlertDialog with two choices (“Move to Trash” / “Permanently Delete”).

Keep the same backend logic that deletes files and updates the state store.

Keyboard Navigation
You list it for Compare view – but also ensure that the Grid view supports arrow keys to move between tiles (focus management). Flet doesn’t have built‑in keyboard navigation for GridView.
Enhancement: Use ft.Container with on_keyboard_event on the page, and manually shift a “selected” tile index. Or wrap each tile in a Focusable control.

Testing & Incremental Migration
You plan to “build scan page before results page”. Good. But you also need to keep the old Tkinter app working until the Flet version is feature‑complete.
Enhancement:

Add a CLI flag (--ui flet) to choose the UI.

Keep the old entry point as default.

Run both side‑by‑side during development to compare behaviour.

Additional Enhancements (for a “2026” look)
Glassmorphism – Flet supports it natively via blur and bgcolor with opacity. Create a glass_container helper that applies border_radius=20, shadow=ft.BoxShadow, and bgcolor=ft.colors.with_opacity(0.3, ft.colors.WHITE).

Micro‑animations – Use ft.AnimatedContainer for page transitions. For tile hovers, use on_hover to change elevation or scale.

Responsive breakpoints – Flet is responsive out of the box. Use ResponsiveRow and Column with col values so that the layout adapts to window resizing (the old Tkinter app had fixed widths).

System theme detection – Flet can auto‑detect light/dark mode (page.theme_mode = ft.ThemeMode.SYSTEM). Respect that but also let the user override.

Revised Phase Breakdown (with new tasks)
Phase	Original Tasks	Added / Enhanced Tasks
0	Remove tkinter from engines	Also remove any tkinter.filedialog or messagebox calls. Replace with pure Python path selection (use Path).
1	Flet Hello World	Add flet to requirements.txt and test on Windows/macOS/Linux.
2	Backend service	Add cancellation support. Add thumbnail generator service. Add asyncio‑safe callbacks.
3	Navigation	Ensure deep linking (Flet supports URL routes via page.on_route_change).
4	Results list	Implement virtual scrolling for 100k+ groups. Use ft.ListView with auto_scroll=False and lazy loading.
5	Review page – Grid	Add infinite scroll (load next batch of tiles when bottom is reached). Use page.add_timeout for smooth thumb loading.
5	Review page – Compare	Add keyboard shortcuts (← →, D for delete, K for keep). Show a confirmation dialog before destructive actions.
6	Polish	Integrate page.go_async for smooth route transitions. Add a global loading overlay (semi‑transparent container) for long operations.
Final Checklist (enhanced)
Feature	Status	Notes
Scanning (with cancel)	⬜	Use threading.Event
Progress reporting (async)	⬜	Use asyncio queue
Grouping & hashing	⬜	Already in engine
Results list (virtual)	⬜	Flet ListView
Filter by extension	⬜	Use ft.SegmentedButton
Thumbnail grid (lazy, cached)	⬜	Base64 + LRU
Side‑by‑side compare	⬜	Two Container with Row
Delete confirmation & trash	⬜	ft.AlertDialog
Open in Explorer	⬜	Use subprocess (already exists)
Keyboard navigation (grid/compare)	⬜	page.on_keyboard_event
Light / Dark mode switch	⬜	page.theme_mode toggle
Responsive layout	⬜	ResponsiveRow
Glassmorphism styling	⬜	blur + semi‑transparent bg
Cursor Workflow Tip (updated)
For each phase, create a separate chat or use @files to focus Cursor on exactly the files that need to change. After Phase 0, commit and tag the commit as pre-flet. Then each phase can be reverted independently if something breaks.