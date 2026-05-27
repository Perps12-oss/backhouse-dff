# Flet version policy

## Supported for installs and releases

| Constraint | Value |
|------------|--------|
| Minimum | **0.84.0** |
| Maximum (exclusive) | **0.85.0** |

Declared in `pyproject.toml` and `requirements.txt`:

```text
flet>=0.84.0,<0.85.0
```

On app startup, `cerebro.v2.ui.flet_app.flet_compat.assert_supported_flet()` can be used to fail fast when the environment resolved a different version.

## CI matrix (broader than production pin)

GitHub Actions job **`flet-compat`** installs `flet==0.80.0` and `flet==0.84.0` (overriding the pin) and runs UI compatibility tests. That validates `flet_compat` shims without claiming we ship on 0.80.

## Control event cheat sheet

| Control | Flet ≥ 0.80 | Flet &lt; 0.80 |
|---------|-------------|----------------|
| `Dropdown` | `on_select` | `on_change` |
| `Switch`, `Checkbox`, `Slider` | `on_change` | `on_change` |

Use `dropdown_handler_kwargs(handler)` or `bind_dropdown(dd, handler)` from `cerebro.v2.ui.flet_app.flet_compat` when wiring dropdown handlers.

## Bumping Flet

1. Read [Flet releases](https://github.com/flet-dev/flet/releases).
2. Update `SUPPORTED_FLET_MIN` / `SUPPORTED_FLET_MAX` in `flet_compat.py` and the pin in `pyproject.toml` / `requirements.txt`.
3. Extend the CI matrix if you add a new minor to test.
4. Run `pytest dev/tests/test_flet_compat.py` locally on the new version.
