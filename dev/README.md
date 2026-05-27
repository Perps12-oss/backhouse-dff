# CEREBRO — development tree

Everything that is not required to **run** the app from the repo root.

| Path | Contents |
|------|----------|
| [tests/](tests/) | Pytest suite (`pytest` from repo root) |
| [docs/](docs/) | Architecture, plans, smoke checklists |
| [scripts/](scripts/) | Build, audit, smoke, bisect helpers |
| [packaging/](packaging/) | Optional `app.ico` for Windows builds |
| [build/](build/) | `CEREBRO.spec`, `requirements-build.txt` |
| [notes/](notes/) | Engineering notes and archived audits |
| [editor/](editor/) | Shared VS Code settings (optional) |

## Flet (UI dependency)

Production installs target **Flet 0.84.x** (`flet>=0.84.0,<0.85.0`). See [docs/flet-versions.md](docs/flet-versions.md) for CI matrix and dropdown compatibility helpers.

## Common commands (from repo root)

```bash
pytest
python dev/scripts/post_v1_audit_verify.py
powershell -ExecutionPolicy Bypass -File dev/scripts/build_windows.ps1
```
