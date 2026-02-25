# cerebro/services/startup_assertions.py  (ensure StartupHealth export)

from dataclasses import dataclass


@dataclass(frozen=True)
class StartupHealth:
    ui_ready: bool
    theme_initialized: bool
    event_bus_ready: bool
    scan_state: str
    deletion_state: str
    worker_threads: int
    runtime_mode: str


class StartupAssertionError(RuntimeError):
    pass


class StartupAssertions:
    @staticmethod
    def run(context) -> StartupHealth:
        theme_engine = context.theme_engine
        theme_initialized = (
            getattr(theme_engine, "initialized", None)
            if hasattr(theme_engine, "initialized")
            else True
        )

        health = StartupHealth(
            ui_ready=context.ui is not None,
            theme_initialized=bool(theme_initialized),
            event_bus_ready=bool(context.event_bus) if context.event_bus else True,
            scan_state=context.scan_state,
            deletion_state=context.deletion_state,
            worker_threads=(context.thread_registry.count() if context.thread_registry else 0),
            runtime_mode=context.runtime_mode,
        )

        StartupAssertions._validate(health)
        return health

    @staticmethod
    def _validate(h: StartupHealth):
        errors = []
        if not h.ui_ready:
            errors.append("UI not ready")
        if not h.theme_initialized:
            errors.append("Theme engine not initialized")
        if h.scan_state != "IDLE":
            errors.append("Scan state not IDLE at startup")
        if h.deletion_state != "LOCKED":
            errors.append("Deletion not LOCKED at startup")
        if h.worker_threads != 0:
            errors.append("Worker threads present at startup")
        if errors:
            raise StartupAssertionError(" | ".join(errors))
