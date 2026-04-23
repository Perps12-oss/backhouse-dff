# Building CEREBRO for Windows (shippable app)

This project is a **Python + CustomTkinter** GUI. Distribution is a **PyInstaller “onedir”** bundle: a folder containing `CEREBRO.exe` plus DLLs and dependencies.

## Prerequisites

- **Windows 10/11**, **64-bit Python 3.10–3.12** (or newer if you verify the bundle; CI uses 3.11).
- A **venv** is recommended so the bundle matches what you ship.

### Auto-install when running from source

If someone runs `python main.py` or `python -m cerebro.v2` without installing wheels first, `cerebro.runtime_deps` will run `pip install -r requirements.txt` and restart the process **once** (requires network, write access to the active environment). This is **disabled** for the PyInstaller `.exe` (`sys.frozen`): the frozen folder must already contain every dependency. Set `CEREBRO_SKIP_AUTO_DEPS=1` to disable auto-install for source runs.

## One-command build

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

Or manually:

```text
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller --noconfirm CEREBRO.spec
```

**Output:** `dist\CEREBRO\CEREBRO.exe`  
Ship the **entire** `dist\CEREBRO\` directory (zip it or use an installer tool). Do not distribute only the `.exe` alone.

## Optional: drag-and-drop

```text
pip install tkinterdnd2
```

Rebuild so the hook bundles it; without it, the app still runs but DnD may be disabled.

## Optional: application icon

Place an icon file at:

`packaging\app.ico`

Rebuild; `CEREBRO.spec` picks it up automatically when present.

## Smoke test before release

1. Copy `dist\CEREBRO\` to a machine **without** Python installed.
2. Run `CEREBRO.exe`: welcome → scan → results → review → settings → theme switch.
3. Confirm photo / image-dedupe paths if you ship those modes (`imagehash`, `numpy` are in `requirements.txt`).

## Code signing (optional)

Unsigned executables may trigger **Windows SmartScreen**. For fewer warnings, sign `CEREBRO.exe` (and the installer if you use one) with a commercial code-signing certificate using `signtool`.

## Version number

Release version is tracked in `pyproject.toml` (`[project].version`). Bump it when you tag a release; you can later wire it into the spec or about-dialog if desired.
