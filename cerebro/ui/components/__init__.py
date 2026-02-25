from .collapsible_section import CollapsibleSection
from .status_indicator import StatusIndicator

__all__ = [
    "CollapsibleSection",
    "StatusIndicator",
]

# Modern card-based components (optional import)
try:
    from .modern import (
        PageScaffold,
        PageHeader,
        SidebarNav,
        SidebarNavItem,
        TopToolbar,
        StickyActionBar,
        StatCard,
        ContentCard,
        PreviewInspector,
        HistoryCard,
        ThemeCard,
    )
    __all__ += [
        "PageScaffold", "PageHeader", "SidebarNav", "SidebarNavItem",
        "TopToolbar", "StickyActionBar", "StatCard", "ContentCard",
        "PreviewInspector", "HistoryCard", "ThemeCard",
    ]
except Exception:
    pass
