$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$runner = Join-Path $PSScriptRoot "background_runner.py"

Start-Process -FilePath $pythonExe -ArgumentList "background_runner.py" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
