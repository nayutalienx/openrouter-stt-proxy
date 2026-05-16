param(
    [string]$Text = "ну короче я хотел сказать что давай наверное завтра это обсудим потому что сейчас не очень удобно"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$headers = @{}

if ($env:LOCAL_PROXY_API_KEY) {
    $headers["Authorization"] = "Bearer $($env:LOCAL_PROXY_API_KEY)"
}

$body = @{
    text = $Text
} | ConvertTo-Json
$bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)

$response = Invoke-RestMethod -Uri "http://127.0.0.1:8787/debug/cleanup" -Method Post -ContentType "application/json; charset=utf-8" -Headers $headers -Body $bodyBytes
$response | ConvertTo-Json -Depth 5
