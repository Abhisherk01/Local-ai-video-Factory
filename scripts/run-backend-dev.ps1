# run-backend-dev.ps1 - start the backend for browser development (Phase 2)
# Usage:  powershell -ExecutionPolicy Bypass -File .\scripts\run-backend-dev.ps1
# Then in a second terminal:  npm run dev   ->  http://localhost:5173
# The Vite dev proxy injects the dev token automatically.

param(
    [int]$Port = 8756,
    [string]$Token = "dev-token"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"

$env:LAF_TOKEN = $Token
$env:LAF_DATA_DIR = Join-Path $repo "data"
$env:PYTHONPATH = Join-Path $repo "backend"

Write-Host "Local AI Video Factory backend (development mode)"
Write-Host "  bind : 127.0.0.1:$Port"
Write-Host "  data : $env:LAF_DATA_DIR"
Write-Host "  token: $Token (development constant, not a secret)"

if (Test-Path $venvPython) {
    & $venvPython -m laf.server --port $Port --data-dir $env:LAF_DATA_DIR
} else {
    Write-Host "venv not found - falling back to the py launcher (py -3.12)"
    & py -3.12 -m laf.server --port $Port --data-dir $env:LAF_DATA_DIR
}
