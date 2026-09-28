$ErrorActionPreference = "Stop"
$env:MARKET_PILOT_ROOT = $PSScriptRoot
& (Join-Path $PSScriptRoot "launcher\build-launcher.ps1")
Start-Process -FilePath (Join-Path $PSScriptRoot "dist\MarketPilotLauncher.exe") -ArgumentList "--start"
