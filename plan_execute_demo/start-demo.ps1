param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$demoRoot = Split-Path -Parent $PSScriptRoot
$port = 8765
$url = "http://127.0.0.1:$port"
$python = (Get-Command python -ErrorAction Stop).Source

function Import-DemoEnv {
    $envPath = Join-Path $PSScriptRoot '.env'
    if (-not (Test-Path -LiteralPath $envPath)) { return }
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) { continue }
        $name, $value = $trimmed.Split('=', 2)
        if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim()
        }
    }
}

Push-Location $demoRoot
try {
    # Tests must not consume an optional model key or call a configured provider.
    Remove-Item Env:PLAN_EXECUTE_LLM_URL -ErrorAction SilentlyContinue
    Remove-Item Env:PLAN_EXECUTE_LLM_API_KEY -ErrorAction SilentlyContinue
    & $python -m compileall -q plan_execute_demo
    & $python -m unittest plan_execute_demo.test_demo
    if ($LASTEXITCODE -ne 0) { throw 'Demo verification failed; the service was not started.' }
    Import-DemoEnv

    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($owner.CommandLine -notmatch 'plan_execute_demo\.server') {
            throw "Port $port is already used by another program. It was not stopped."
        }
        Write-Host "Reusing the existing Plan-Execute Demo at $url"
    }
    else {
        $process = Start-Process -FilePath $python -ArgumentList '-m plan_execute_demo.server' `
            -WorkingDirectory $demoRoot -WindowStyle Hidden -PassThru
        $ready = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            Start-Sleep -Milliseconds 250
            try {
                $response = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 1
                if ($response.StatusCode -eq 200) { $ready = $true; break }
            }
            catch { }
        }
        if (-not $ready) {
            if (-not $process.HasExited) { Stop-Process -Id $process.Id }
            throw 'Demo service did not become ready.'
        }
        Write-Host "Plan-Execute Demo started at $url"
    }
    if (-not $NoBrowser) { Start-Process $url }
}
finally {
    Pop-Location
}
