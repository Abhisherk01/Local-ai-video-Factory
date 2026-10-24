# Local AI Video Factory - piper voice downloader (0.4.5-voices, 0.4.10-multilang)
#
# Usage (PowerShell, from the repo root):
#   .\scripts\add_voice.ps1 ryan
#   .\scripts\add_voice.ps1 amy
#   .\scripts\add_voice.ps1 pratham        # Hindi male (0.4.10)
#   .\scripts\add_voice.ps1 priyamvada     # Hindi female (0.4.10)
#   .\scripts\add_voice.ps1 -Name en_US-joe-medium     # full slug works too
#   .\scripts\add_voice.ps1 -List                      # show catalog + installed
#
# Downloads the voice model (.onnx) + its config (.onnx.json) from the
# official rhasspy/piper-voices v1.0.0 release on Hugging Face into
#   <models_dir>\piper\voices\
# The backend picks new voices up on the next render (no restart needed).

param(
    [string]$Name = "",
    [string]$ModelsDir = "",
    [switch]$List
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # 10x faster Invoke-WebRequest on PS 5.1

# short name -> slug (all verified against the v1.0.0 release)
$Catalog = @{
    "pratham"    = "hi_IN-pratham-medium"
    "priyamvada" = "hi_IN-priyamvada-medium"
    "amy"        = "en_US-amy-medium"
    "lessac"     = "en_US-lessac-medium"
    "kathleen"   = "en_US-kathleen-low"
    "kristin"    = "en_US-kristin-medium"
    "harper"     = "en_US-hfc_female-medium"
    "ryan"       = "en_US-ryan-high"
    "joe"        = "en_US-joe-medium"
    "norman"     = "en_US-norman-medium"
    "marcus"     = "en_US-hfc_male-medium"
    "alan"       = "en_GB-alan-low"
}

# slug -> repo path under https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/
function Get-VoicePath([string]$slug) {
    if ($slug -match '^hi_IN-([a-z0-9_]+)-(low|medium|high)$') {
        return "hi/hi_IN/$($Matches[1])/$($Matches[2])/$slug"
    }
    if ($slug -match '^en_(US|GB)-([a-z0-9_]+)-(low|medium|high)$') {
        return "en/en_$($Matches[1])/$($Matches[2])/$($Matches[3])/$slug"
    }
    return $null
}

function Resolve-ModelsDir {
    if ($ModelsDir) { return $ModelsDir }
    if ($env:LAF_MODELS_DIR) { return $env:LAF_MODELS_DIR }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "com.rajbh.localaivideofactory\models"),
        (Join-Path $env:LOCALAPPDATA "LocalAIVideoFactory\models")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $candidates[0]   # default Tauri-shell layout; created below
}

$models = Resolve-ModelsDir
$voices = Join-Path $models "piper\voices"

if ($List) {
    Write-Host "== catalog (short name -> slug) =="
    $Catalog.GetEnumerator() | Sort-Object Name | ForEach-Object {
        $slugFile = Join-Path $voices "$($_.Value).onnx"
        $have = if (Test-Path $slugFile) { "INSTALLED" } else { "not installed" }
        Write-Host ("  {0,-10} {1,-26} {2}" -f $_.Key, $_.Value, $have)
    }
    if (Test-Path $voices) {
        Write-Host "== voices dir: $voices =="
        Get-ChildItem $voices -Filter *.onnx | ForEach-Object { Write-Host "  $($_.Name)" }
    } else {
        Write-Host "== voices dir does not exist yet: $voices =="
    }
    return
}

if (-not $Name) {
    Write-Host "Usage: .\scripts\add_voice.ps1 <name>   e.g. .\scripts\add_voice.ps1 ryan"
    Write-Host "       .\scripts\add_voice.ps1 -List     catalog + installed voices"
    Write-Host "English: $($Catalog.Keys | Where-Object { $Catalog[$_] -like 'en_*' } | Sort-Object)"
    Write-Host "Hindi:   pratham, priyamvada  (0.4.10 - needs a Hindi/Devanagari script)"
    return
}

$key = $Name.ToLower().Trim()
if ($Catalog.ContainsKey($key)) {
    $slug = $Catalog[$key]
} else {
    $slug = $key          # allow full slugs: en_US-joe-medium
}

$voicePath = Get-VoicePath $slug
if (-not $voicePath) {
    Write-Error "Unrecognized voice '$Name'. Use one of: $($Catalog.Keys -join ', ') (or a full slug like en_US-joe-medium)."
}

New-Item -ItemType Directory -Force -Path $voices | Out-Null
$base = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/$voicePath"
$onnxOut = Join-Path $voices "$slug.onnx"
$jsonOut = Join-Path $voices "$slug.onnx.json"

if (Test-Path $onnxOut) {
    Write-Host "$slug is already installed: $onnxOut"
} else {
    Write-Host "Downloading $slug model (~60-120 MB)..."
    Invoke-WebRequest -Uri "$base.onnx" -OutFile $onnxOut
}

if (-not (Test-Path $jsonOut)) {
    Write-Host "Downloading $slug config (~2 MB)..."
    Invoke-WebRequest -Uri "$base.onnx.json" -OutFile $jsonOut
}

$mb = [math]::Round((Get-Item $onnxOut).Length / 1MB, 1)
Write-Host "OK: $slug installed ($mb MB) -> $voices"
Write-Host "The next Render with voice '$slug' (or the UI dropdown) will use it."
Write-Host "Installed voices now:"
Get-ChildItem $voices -Filter *.onnx | ForEach-Object { Write-Host "  $($_.Name)" }
