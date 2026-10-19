<#
.SYNOPSIS
  Local AI Video Factory - Windows prerequisite check / install (Phase 1).

.DESCRIPTION
  Verifies development prerequisites for the project.
    -Check    : report only, installs nothing (default behavior with no installs)
    -Install  : install MISSING items via winget (requires internet)
  Docker is intentionally NOT used by this project (ADR-003).
  Nothing is installed unless you pass -Install explicitly.

.USAGE
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Check
  powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1 -Install
#>
param(
    [switch]$Check,
    [switch]$Install
)

$ErrorActionPreference = "Continue"

function Get-VersionOutput {
    param([string]$Exe, [string[]]$ExeArgs = @("--version"))
    $found = Get-Command $Exe -ErrorAction SilentlyContinue
    if (-not $found) { return $null }
    try {
        $line = (& $Exe @ExeArgs 2>$null | Select-Object -First 1)
        if ($null -eq $line) { return "present" }
        return ("{0}  [{1}]" -f $line.Trim(), $found.Source)
    } catch {
        return "present (version check failed)"
    }
}

function Get-Python312 {
    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if (-not $pyLauncher) { return $null }
    try {
        $out = & py -3.12 --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return $out.ToString().Trim() } else { return $null }
    } catch { return $null }
}

$tools = @(
    @{ Name = "winget";         Id = $null;                Detect = { Get-VersionOutput "winget" } },
    @{ Name = "Git";            Id = "Git.Git";            Detect = { Get-VersionOutput "git" } },
    @{ Name = "Python 3.12";    Id = "Python.Python.3.12"; Detect = { Get-Python312 } },
    @{ Name = "Node.js LTS";    Id = "OpenJS.NodeJS.LTS";  Detect = { Get-VersionOutput "node" } },
    @{ Name = "FFmpeg";         Id = "Gyan.FFmpeg";        Detect = { Get-VersionOutput "ffmpeg" @("-version") } },
    @{ Name = "Rust toolchain"; Id = "Rustlang.Rustup";    Detect = { Get-VersionOutput "cargo" } }
)

"=== Local AI Video Factory - Windows prerequisites ==="
$missing = @()
foreach ($t in $tools) {
    $status = $t.Detect.Invoke()
    if ($null -eq $status) {
        $missing += $t
        ("MISSING  {0}" -f $t.Name)
    } else {
        ("OK       {0,-14} {1}" -f $t.Name, $status)
    }
}
""

if ($missing.Count -eq 0) {
    "All prerequisites present."
} elseif ($Install) {
    foreach ($t in $missing) {
        if ($null -eq $t.Id) { continue }
        ("Installing {0} via winget ({1})..." -f $t.Name, $t.Id)
        winget install --id $t.Id -e --silent --accept-package-agreements --accept-source-agreements
    }
    "Install pass complete. Open a NEW terminal, then re-run with -Check to verify PATH changes."
} elseif ($Check) {
    ("{0} item(s) missing. To install them via winget, re-run with -Install, or manually:" -f $missing.Count)
    foreach ($t in $missing) {
        if ($null -ne $t.Id) { ("  winget install --id {0} -e" -f $t.Id) }
    }
} else {
    "No mode selected. Use -Check to report, or -Install to install missing items."
}

""
"Notes:"
"- Python 3.12 is required alongside any newer Python (PyTorch wheel support; see INSTALLATION.md)."
"- Rust is only needed from Phase 2 (Tauri desktop shell)."
"- FFmpeg is needed from Phase 5 (rendering)."
"- Docker is NOT used by this project."
"- After installs, PATH changes require a new terminal window."
