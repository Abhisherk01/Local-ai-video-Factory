<#
.SYNOPSIS
  Local AI Video Factory - Windows prerequisite check / install (Phase 2).

.DESCRIPTION
  Verifies development prerequisites for the project.
    -Check    : report only, installs nothing (default)
    -Install  : install MISSING items via winget (requires internet)
  Docker is intentionally NOT used by this project (ADR-003).
  Nothing is installed unless you pass -Install explicitly.

  Phase 2 rewrite: the Phase 1 version could print false OK rows and raw
  .NET type names under Windows PowerShell 5.1. Verdicts now come ONLY
  from Get-Command (proven reliable), version strings are best-effort
  display and never affect pass/fail, and the MSVC C++ toolset is
  checked via vswhere (required for Rust/Tauri linking).

.USAGE
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Check
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Install
#>

param(
    [switch]$Check,
    [switch]$Install
)

$ErrorActionPreference = "Continue"

function Get-VersionLine {
    param(
        [string]$Exe,
        [string[]]$ExeArgs = @("--version")
    )
    # Best-effort version display only. Returns a readable line or $null.
    # A failure here never changes a verdict.
    try {
        $raw = & $Exe @ExeArgs 2>&1
        foreach ($item in @($raw)) {
            $text = [string]$item
            if ($text -match '\d' -and $text.Trim().Length -gt 0) {
                return $text.Trim()
            }
        }
    } catch {
        return $null
    }
    return $null
}

function Test-CommandPresent {
    param([string]$Exe)
    return ($null -ne (Get-Command $Exe -ErrorAction SilentlyContinue))
}

function Get-Python312Line {
    try {
        if (-not (Test-CommandPresent "py")) { return $null }
        $raw = & py -3.12 --version 2>&1
        if ($LASTEXITCODE -ne 0) { return $null }
        foreach ($item in @($raw)) {
            $text = [string]$item
            if ($text -match '^Python 3\.12') { return $text.Trim() }
        }
    } catch {
        return $null
    }
    return $null
}

function Get-MsvcInstallPath {
    # Visual Studio C++ x86/x64 toolset via vswhere. Required for Rust MSVC linking (Tauri).
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { return $null }
    try {
        $raw = & $vswhere -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>&1
        foreach ($item in @($raw)) {
            $text = [string]$item
            if ($text -match 'Visual Studio') { return $text.Trim() }
        }
    } catch {
        return $null
    }
    return $null
}

"=== Local AI Video Factory - Windows prerequisites ==="
$missing = @()

# --- Simple executables: verdict = Get-Command only ---
$tools = @(
    @{ Name = "winget";        Exe = "winget";  Id = $null;               VArgs = @("--version") },
    @{ Name = "Git";           Exe = "git";     Id = "Git.Git";           VArgs = @("--version") },
    @{ Name = "Node.js";       Exe = "node";    Id = "OpenJS.NodeJS.LTS"; VArgs = @("--version") },
    @{ Name = "FFmpeg";        Exe = "ffmpeg";  Id = "Gyan.FFmpeg";       VArgs = @("-version") },
    @{ Name = "Rust (rustup)"; Exe = "rustup";  Id = "Rustlang.Rustup";   VArgs = @("--version") },
    @{ Name = "Rust (cargo)";  Exe = "cargo";   Id = $null;               VArgs = @("--version") }
)

$rustupOk = $false
$cargoOk  = $false

foreach ($t in $tools) {
    if (Test-CommandPresent $t.Exe) {
        $ver = Get-VersionLine -Exe $t.Exe -ExeArgs $t.VArgs
        if ($null -eq $ver) { $ver = "version unknown (binary present)" }
        ("OK       {0,-14} {1}" -f $t.Name, $ver)
        if ($t.Exe -eq "rustup") { $rustupOk = $true }
        if ($t.Exe -eq "cargo")  { $cargoOk  = $true }
    } else {
        ("MISSING  {0}" -f $t.Name)
        if ($null -ne $t.Id) { $missing += $t }
    }
}

if ($rustupOk -and -not $cargoOk) {
    ("NOTE     {0}" -f "rustup present but no toolchain yet - run: rustup default stable")
}

# --- Python 3.12 (pinned; see pyproject.toml) ---
$py312 = Get-Python312Line
if ($null -ne $py312) {
    ("OK       {0,-14} {1}" -f "Python 3.12", $py312)
} else {
    ("MISSING  {0}" -f "Python 3.12")
    $missing += @{ Name = "Python 3.12"; Id = "Python.Python.3.12" }
}

# --- MSVC C++ toolset (Rust linker requirement) ---
$msvc = Get-MsvcInstallPath
if ($null -ne $msvc) {
    ("OK       {0,-14} {1}" -f "MSVC C++", $msvc)
} else {
    ("MISSING  {0}" -f "MSVC C++")
    ("  install Visual Studio 2022 Build Tools with the 'Desktop development with C++' workload,")
    ("  or: winget install --id Microsoft.VisualStudio.2022.BuildTools -e ")
    ("  (Rust cannot link Tauri without it)")
}
""

if ($missing.Count -eq 0) {
    "All winget-managed prerequisites present."
} elseif ($Install) {
    foreach ($t in $missing) {
        ("Installing {0} via winget ({1})..." -f $t.Name, $t.Id)
        winget install --id $t.Id -e --silent --accept-package-agreements --accept-source-agreements
    }
    "Install pass complete. Close ALL terminal windows, open a NEW one, then re-run with -Check."
} elseif ($Check) {
    ("{0} item(s) missing. To install via winget, re-run with -Install, or manually:" -f $missing.Count)
    foreach ($t in $missing) {
        ("  winget install --id {0} -e" -f $t.Id)
    }
} else {
    "No mode selected. Use -Check to report, or -Install to install missing items."
}

""
"Notes:"
"- Python 3.12 is required alongside any newer Python (PyTorch wheel support; see INSTALLATION.md)."
"- Rust + MSVC C++ toolset are needed from Phase 2 (Tauri desktop shell)."
"- FFmpeg is needed from Phase 5 (rendering)."
"- Docker is NOT used by this project."
"- After installs, PATH changes require a brand-new terminal window (new tabs in an open"
"  Windows Terminal inherit the old PATH)."
