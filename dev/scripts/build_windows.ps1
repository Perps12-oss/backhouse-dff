# Build a shippable Windows folder app (PyInstaller onedir, no console).
# Run from repo root:
#   powershell -ExecutionPolicy Bypass -File dev\scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

Write-Host "==> Repo: $RepoRoot"

Write-Host "==> Installing runtime + build deps..."
python -m pip install -U pip
python -m pip install -r requirements.txt -r dev/build/requirements-build.txt

Write-Host "==> PyInstaller (dev/build/CEREBRO.spec)..."
python -m PyInstaller --noconfirm dev/build/CEREBRO.spec

$exe = Join-Path $RepoRoot "dist\CEREBRO\CEREBRO.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "BUILD OK: $exe"
    Write-Host "Zip the whole folder dist\CEREBRO\ for distribution (all DLLs live beside the exe)."
} else {
    Write-Host "BUILD FAILED: expected $exe"
    exit 1
}
