param(
    [string]$PythonLauncher = "py -3"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Invoke-Expression "$PythonLauncher -m venv .venv"
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "Virtual environment created at $projectRoot\.venv"
Write-Host "Activate with: .\.venv\Scripts\Activate.ps1"
