<#
.SYNOPSIS
  Local AI Video Factory - read-only hardware probe.

.DESCRIPTION
  Collects OS, CPU, RAM, GPU/VRAM, disk, dev tools, and download speed.
  Installs nothing. Safe to run any time. Used in Phase 0; keep for
  re-verifying the machine after upgrades.

.USAGE
  powershell -ExecutionPolicy Bypass -File .\scripts\probe-hardware.ps1
#>

"=== WINDOWS / RAM ==="
$os = Get-CimInstance Win32_OperatingSystem
"OS:   $($os.Caption)  (build $($os.BuildNumber))"
"Arch: $([Environment]::Is64BitOperatingSystem)"
"RAM:  {0:N1} GB total" -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)

"=== CPU ==="
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
"CPU:  $($cpu.Name.Trim())"
"Cores: $($cpu.NumberOfCores) physical / $($cpu.NumberOfLogicalProcessors) logical"

"=== GPU / VRAM ==="
Get-CimInstance Win32_VideoController | ForEach-Object { "GPU:  $($_.Name)  (driver $($_.DriverVersion))" }
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
} else { "nvidia-smi: not found (no NVIDIA GPU, or driver not in PATH)" }

"=== DISK FREE ==="
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    "Drive {0}  {1:N0} GB free of {2:N0} GB" -f $_.DeviceID, ($_.FreeSpace/1GB), ($_.Size/1GB) }

"=== DEV TOOLS ALREADY PRESENT ==="
foreach ($tool in @('git','python','py','node','npm','ffmpeg','docker','winget')) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if ($found) { "{0,-8} FOUND  {1}" -f $tool, $found.Source } else { "{0,-8} not found" -f $tool }
}
if (Get-Command docker -ErrorAction SilentlyContinue) { docker --version }

"=== DOWNLOAD SPEED (~25 MB test) ==="
try {
    $t = Measure-Command { Invoke-WebRequest -Uri "https://speed.cloudflare.com/__down?bytes=25000000" -OutFile "$env:TEMP\laf_spd.bin" -UseBasicParsing }
    "Down: {0:N0} Mbit/s  (25 MB in {1:N1} s)" -f (25*8/$t.TotalSeconds), $t.TotalSeconds
    Remove-Item "$env:TEMP\laf_spd.bin" -ErrorAction SilentlyContinue
} catch { "Speed test failed - check fast.com manually" }

"=== UPLOAD SPEED ==="
"Not measured here - run fast.com, click 'Show more info', note the upload figure."

"=== DONE ==="
