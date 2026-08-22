param(
    [Parameter(Mandatory = $true)]
    [int]$AnalysisId,
    [string]$BaseUrl = "http://127.0.0.1:3000"
)

$ErrorActionPreference = "Stop"
$output = Join-Path $PSScriptRoot "market-pilot-report.png"
$url = "$($BaseUrl.TrimEnd('/'))/analysis/$AnalysisId"

npx playwright screenshot `
    --viewport-size="1440,900" `
    --wait-for-timeout=1500 `
    $url `
    $output

Write-Host "Captured README report screenshot: $output"
