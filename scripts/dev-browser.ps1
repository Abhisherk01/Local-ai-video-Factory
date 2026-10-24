<#
.SYNOPSIS
  One-command browser dev mode for Local AI Video Factory.
  Boots the backend on a fixed port with a known token, waits for /health,
  then starts the Vite dev server. Ctrl+C stops both.

.DESCRIPTION
  Why this exists: the Tauri shell spawns the backend on a RANDOM free port
  (main.rs free_port()) and hands port+token to the WebView via IPC
  (get_backend_info, ADR-008). The Vite dev proxy targets a FIXED port
  (LAF_PORT, default 8756) and injects the X-LAF-Token header from LAF_TOKEN.
  Plain browser mode therefore needs a backend started manually on that fixed
  port with a matching token. This script automates that, plus cleanup.

  Usage:
    .\scripts\dev-browser.ps1                 # defaults: port 8756, token dev-token
    .\scripts\dev-browser.ps1 -Port 8800      # custom port (LAF_PORT is set for you)

  Stop with Ctrl+C. Do not just close the terminal window, or the backend
  process is orphaned and will hold the port.
#>
#requires -Version 5
param(
    [int]$Port = 8756,
    [string]$Token = "dev-token"
)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv python not found: $python (run from the repo)" }

# Resolve the desktop app's data dir from the Tauri identifier so browser
# mode sees the same episodes/db as the desktop window.
$confPath = Join-Path $repo "src-tauri\tauri.conf.json"
$conf = Get-Content $confPath -Raw
if ($conf -notmatch '"identifier"\s*:\s*"([^"]+)"') { throw "identifier not found in $confPath" }
$dataDir = Join-Path $env:LOCALAPPDATA $Matches[1]

# Guard 1: the fixed port must be free.
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $ownerPid = $listener.OwningProcess | Select-Object -First 1
    throw "port $Port is already in use (PID $ownerPid). Stop that process first, or pass -Port <other>."
}

# Guard 2: the desktop app must not share the DB with a second backend.
if (Get-Process laf-shell -ErrorAction SilentlyContinue) {
    Write-Warning "laf-shell (desktop app) is running. Close it first - two backends must not share one DB."
}

$backendDir = Join-Path $repo "backend"
$logsDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$outLog = Join-Path $logsDir "dev-backend.out.log"
$errLog = Join-Path $logsDir "dev-backend.err.log"

Write-Host "[dev-browser] repo      : $repo"
Write-Host "[dev-browser] data dir  : $dataDir"
Write-Host "[dev-browser] backend   : python -m laf.server --port $Port"
Write-Host "[dev-browser] bak logs  : $outLog / $errLog"

$env:LAF_TOKEN = $Token   # inherited by the backend child; the Vite proxy reads it too
$argStr = "-m laf.server --port $Port --data-dir `"$dataDir`""
$proc = Start-Process -FilePath $python -ArgumentList $argStr -WorkingDirectory $backendDir -NoNewWindow -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

$health = $null
try {
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { throw "backend exited during startup - see $errLog" }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.status -eq "ok") { break }
        } catch { $health = $null }
    }
    if ($null -eq $health -or $health.status -ne "ok") { throw "backend not healthy after 30s - see $errLog" }
    Write-Host "[dev-browser] backend ready: v$($health.version) on 127.0.0.1:$Port"
    Write-Host "[dev-browser] starting vite - open http://localhost:5173 - Ctrl+C stops both"

    $env:LAF_PORT = "$Port"
    Push-Location $repo
    try { npm run dev } finally { Pop-Location }
    Write-Host "[dev-browser] vite exited (npm code $LASTEXITCODE)"
}
finally {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "[dev-browser] backend (PID $($proc.Id)) stopped."
    }
}
