$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$projectFile = Join-Path $PSScriptRoot "MarketPilot.Launcher\MarketPilot.Launcher.csproj"
$outputDirectory = Join-Path $projectRoot "dist"

dotnet publish $projectFile `
    --configuration Release `
    --runtime win-x64 `
    --self-contained false `
    -p:PublishSingleFile=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    --output $outputDirectory

Write-Host ""
Write-Host "Launcher created: $outputDirectory\MarketPilotLauncher.exe"
