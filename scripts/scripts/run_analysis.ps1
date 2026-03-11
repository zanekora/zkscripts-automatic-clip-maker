param(
    [string]$Input = "input",
    [string]$Output = "output",
    [string]$Review = "review",
    [string]$Config = "config\defaults.json"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m src.main --input $Input --output $Output --review $Review --config $Config
