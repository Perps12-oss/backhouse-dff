# Build a shippable Windows folder app (PyInstaller onedir, no console).
# Run from repo root OR from scripts/:
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
$RepoRoot = if ($PSScriptRoot) {
    (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    (Get-Location).Path
}
Set-Location $RepoRoot

Write-Host "==> Repo: $RepoRoot"

Write-Host "==> Installing runtime + build deps..."
python -m pip install -U pip
python -m pip install -r requirements.txt -r requirements-build.txt

Write-Host "==> PyInstaller (CEREBRO.spec)..."
python -m PyInstaller --noconfirm CEREBRO.spec

$exe = Join-Path $RepoRoot "dist\CEREBRO\CEREBRO.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "BUILD OK: $exe"
    Write-Host "Zip the whole folder dist\CEREBRO\ for distribution (all DLLs live beside the exe)."
} else {
    Write-Host "BUILD FAILED: expected $exe"
    exit 1
}
