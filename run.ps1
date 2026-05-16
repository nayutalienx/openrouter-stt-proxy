$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venvPath = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
$requirementsFile = Join-Path $PSScriptRoot "requirements.txt"
$envFile = Join-Path $PSScriptRoot ".env"
$envExampleFile = Join-Path $PSScriptRoot ".env.example"

$pythonVersion = py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10+ is required but py launcher is not available."
}

$versionParts = $pythonVersion.Trim().Split(".")
$major = [int]$versionParts[0]
$minor = [int]$versionParts[1]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
    throw "Python 3.10+ is required. Current default py -3 version: $pythonVersion"
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment in .venv ..."
    py -3 -m venv $venvPath
}

Write-Host "Installing dependencies ..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirementsFile

if (-not (Test-Path $envFile)) {
    Write-Host ""
    Write-Host "Missing .env file."
    Write-Host "Create it from .env.example and set OPENROUTER_API_KEY:"
    Write-Host "  Copy-Item $envExampleFile $envFile"
    exit 1
}

Write-Host "Starting proxy on http://127.0.0.1:8787 ..."
& $venvPython -m uvicorn app:app --host 127.0.0.1 --port 8787
