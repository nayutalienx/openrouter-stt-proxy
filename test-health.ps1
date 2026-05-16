$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$response = Invoke-RestMethod -Uri "http://127.0.0.1:8787/health"
$response | ConvertTo-Json -Depth 5
