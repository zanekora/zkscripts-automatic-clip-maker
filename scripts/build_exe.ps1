param(
    [string]$OutputDir = "dist_portable",
    [string]$FfmpegBinDir = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment Python not found at $python"
}

& $python -m pip install pyinstaller
& $python -m PyInstaller --noconfirm --clean ".\packaging\gameplay_pipeline.spec"

$buildRoot = Join-Path $projectRoot "dist\GameplayHighlightPipeline"
$portableRoot = Join-Path $projectRoot $OutputDir

if (Test-Path $portableRoot) {
    Remove-Item -Recurse -Force $portableRoot
}

Copy-Item -Recurse -Force $buildRoot $portableRoot

foreach ($folder in @("input", "intermediate", "output", "review", "logs")) {
    $target = Join-Path $portableRoot $folder
    New-Item -ItemType Directory -Force $target | Out-Null
}

if ($FfmpegBinDir -and (Test-Path $FfmpegBinDir)) {
    Copy-Item -Force (Join-Path $FfmpegBinDir "ffmpeg.exe") (Join-Path $portableRoot "ffmpeg.exe")
    Copy-Item -Force (Join-Path $FfmpegBinDir "ffprobe.exe") (Join-Path $portableRoot "ffprobe.exe")
}

Write-Host "Portable build prepared at: $portableRoot"
