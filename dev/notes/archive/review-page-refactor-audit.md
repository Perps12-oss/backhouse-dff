> **Superseded (2026-05):** V1 `ReviewPage`, `results_page.py`, and `pages/review/*` are retired. Live review UI is `cerebro/v2/ui/flet_app/pages/review_flow/` (`ReviewFlowHost`). See `dev/docs/UI_ARCHITECTURE.md`.

🔍 Deep Code Audit — What’s Holding You Back
1. Duplicate Logic Everywhere
_get_glass_style, _safe_update, _is_mounted are copy‑pasted across three files.

Filter bar (tabs, counts, sizes) is duplicated with slightly different labels.

Smart selection (rule picker, auto‑mark) exists in both review_page.py and results_page.py.

Inspector overlay, thumbnail loader, group cards are rewritten, not reused.

2. Error‑Prone Patterns
Inconsistent page access: self._page_is_set() and _safe_update() dance around Flet’s null page—a single base class would eliminate this.

Missing error handling in async tasks: if thumbnail loading fails, the UI silently falls apart.

Hardcoded “generations” (_list_build_generation, _rendering_generation) are fragile; a race condition can leave stale controls visible.

3. Performance Bottlenecks
1000‑group cap is a symptom of building too many controls at once. The _MAX_RENDERED_GROUPS hack hides the real problem: virtualisation is missing. Even with chunked async building, all 1000 cards stay in the list after being built, consuming memory and causing layout recalculations.

Canvas‑based chunk bar (_draw_bar) redraws every tick—fine for a progress bar but unnecessarily complex. A simple row of colored containers would be equally informative and lighter.

Scan HUD timer thread uses time.sleep(1) and then calls page.run_thread every second; busy‑waiting is wasteful. A single periodic callback using page.run_task with asyncio.sleep would be cleaner.

Thumbnail loading spawns a batch load that then processes all slots at once. For 200 slots, this can freeze the UI. The loader should stream results and update incrementally.

4. UX Rough Edges
Empty state: “No duplicates found” is plain text; a modern app would have an illustrated empty state with a clear call to action.

Scan cancellation flow: The user is presented with a confusing “What would you like to do next?” panel that includes a disabled button; the flow is not minimal.

Dashboard scan mode selector: checkboxes mixed with “Full Scan” disabled logic—confusing. A modern pill‑selector would be clearer.

No transition animations: switching between views feels abrupt. Fade‑in/out opacities would improve perceived performance.

5. Inconsistent Theming
_get_glass_style uses hardcoded ft.Colors.WHITE/BLACK regardless of actual theme—the glass effect must adapt to the current color scheme.

🎨 Modernisation Vision: Minimalistic, Professional, Feature‑Rich
We’ll build a unified design system:

Base components (glass containers, filters, inspectors) that automatically respect the global theme.

Smooth micro‑interactions: fade‑in on content load, subtle hover glows, animated progress rings, and skeleton placeholders while data loads.

Performant lists using Flet’s implicit virtualisation: only build views when they become visible (if possible) or at least reuse card objects with data binding.

Progressive disclosure: advanced options are collapsed by default; secondary actions are behind an “…” menu to keep the interface clean.

Dark‑first, fully theme‑aware: every color comes from the theme_for_mode tokens.

🧬 New Architecture — Components & Pages
text
cerebro/v2/ui/flet_app/
├── design_system/                  # Shared look & feel
│   ├── glass.py                    # GlassContainer, GlassButton
│   ├── typography.py               # Heading, Body, Caption widgets
│   └── animations.py               # FadeIn, ScaleIn transitions
├── components/
│   ├── filters/
│   │   ├── filter_bar.py           # Reusable filter bar
│   │   └── type_pills.py           # Scan mode selector
│   ├── files/
│   │   ├── file_tile.py            # Grid tile
│   │   ├── group_card.py           # List card
│   │   └── inspector.py            # FileInspector overlay
│   ├── scan/
│   │   ├── scan_hud.py             # Progress ring, bars, timer
│   │   ├── scan_options.py         # Advanced options panel
│   │   └── folder_picker.py        # Folder chip list
│   ├── smart_selection.py          # Rule select + apply buttons
│   └── common/
│       ├── chunked_view.py         # Async chunked list/grid builder
│       └── thumbnail_loader.py     # Batched thumbnail loader
├── pages/
│   ├── dashboard.py                # ~200 lines
│   ├── results.py                  # ~200 lines
│   └── review.py                   # ~250 lines
└── services/                       # unchanged
🔧 Top Improvements You Can Implement Now
✅ Base Glass Container (Replace _get_glass_style)
python
class GlassContainer(ft.Container):
    def __init__(self, content, opacity=0.06, blur_radius=20, **kwargs):
        super().__init__(content=content, **kwargs)
        self._opacity = opacity
        self._blur = blur_radius
        self._apply_style()
        # Re-apply on theme change if needed (subscribe to theme events)

    def _apply_style(self):
        t = theme_for_mode("dark")  # or inject dependency
        bg = ft.Colors.with_opacity(self._opacity, ft.Colors.WHITE)
        self.bgcolor = bg
        self.border = ft.border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.WHITE))
        self.border_radius = 12
        self.shadow = ft.BoxShadow(
            blur_radius=self._blur,
            color=ft.Colors.with_opacity(0.1, ft.Colors.BLACK),
            offset=ft.Offset(0, 4),
        )
Result: All glass containers look identical and theme‑aware.

🚀 Smart Async List with Built‑in Skeleton Loading
python
class ChunkedListView(ft.ListView):
    def __init__(self, items, card_builder, batch_size=16):
        super().__init__(expand=True, spacing=8, padding=20)
        self.items = items
        self.card_builder = card_builder
        self.batch_size = batch_size
        self._gen = 0
        self.controls = self._build_skeletons(4)  # placeholder loading cards

    def _build_skeletons(self, count):
        return [SkeletonCard() for _ in range(count)]

    def load(self):
        if not items:
            self.controls = [EmptyState("No items found")]
            self.update()
            return
        self._gen += 1
        gen = self._gen
        # First batch of 4 real cards
        self.controls = [self.card_builder(item) for item in self.items[:4]]
        self.update()
        # Schedule rest in chunks
        page = ... # get page reference
        page.run_task(self._append_rest, self.items[4:], gen)

    async def _append_rest(self, rest, gen):
        for i in range(0, len(rest), self.batch_size):
            if gen != self._gen:
                return
            batch = rest[i:i+self.batch_size]
            self.controls.extend(self.card_builder(item) for item in batch)
            self.update()
            await asyncio.sleep(0)
Why it’s better: No generation‑tracking clutter in parent pages, built‑in skeleton state, and clean interruption.

🎛️ Refined Scan Progress HUD
Extract the entire scan UI into ScanHUD, a control with:

start() / update(snap) / complete() / error() methods.

Internally manages the progress ring, dual‑phase text, chunk bar, and ETA.

Smooths ring value changes with animate property (Flet supports animation).

ETA uses a proper moving average with confidence — already implemented, but simply moved.

The dashboard page becomes:

python
class DashboardPage(ft.Column, CerebroPage):
    def __init__(self, bridge, folder_picker):
        self.hud = ScanHUD(self._bridge)
        self.folders = FolderPicker(...)
        self.options = ScanOptionsPanel(...)
        # layout assembly...
🖼️ Enhanced File Inspector with Context‑Aware Preview
Instead of a fixed 280px panel, make it a slide‑out drawer that appears with a slide‑in animation (using animate_opacity and offset). Add:

Quick actions: “Open in Explorer”, “Copy Path”.

For images: preview immediately, with zoom on click.

For text files: show first few lines.

Use ft.Container with clip_behavior=HARD_EDGE for smooth corners.

🔍 Search & Filter Quick‑Jump
Add a persistent search bar on the review page that filters groups in real‑time as you type, with highlighted matches. Use a simple TextField with on_change that sets self._search_query and re‑renders.

🧹 Remove Dead Code & Legacy Mixins
ReviewPageChromeMixin, ReviewPageNavThemeMixin, etc., are all absorbed into the new components.

Delete _total_reclaimable_scan and compute on‑the‑fly when needed.

Remove all _page_is_set checks by ensuring every component only updates after being added to the page (the did_mount lifecycle).

📐 Concrete Redesigned Pages — Summary
Page	Key Changes	Lines (Before → After)
ReviewPage	Uses GlassContainer, ChunkedGridView, SmartSelectionRow, FileInspector. All mixins replaced by composed widgets. Compare view becomes a separate ComparePanel that swaps in/out.	1200 → ~250
ResultsPage	Shares filter bar, smart selection, inspector. List/grid view driven by ChunkedListView. Dashboard moved to a ResultsSummary component.	1400 → ~200
DashboardPage	ScanHUD, FolderPicker, ScanOptionsPanel are independent. Checkpoint management handled by CheckpointBanner.	1300 → ~300
🧪 Implementation Roadmap (Ordered by Impact)
Create design_system/glass.py and apply it everywhere → immediate visual consistency.

Build ScanHUD and integrate into DashboardPage → cuts dashboard in half.

Extract FilterBar → removes 150 lines from both results and review pages.

Introduce SmartSelectionRow → eliminates duplicated rule logic.

Refactor list/grid builders → significant performance and maintainability win.

Move FileInspector to a shared component → cleaner code, better animations.

Polish micro‑interactions → fade‑ins, hover effects, and smooth transitions.

This is not just a clean‑up — it’s a modern application shell that will make your duplicate finder feel like a premium product. The modular components will also speed up future feature development tenfold.