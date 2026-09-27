$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location $taskRoot

$env:NIGHTMARE_MEDIA_MODE = "google_flow_cdp"
$env:NIGHTMARE_CANVAS_CDP_URL = "http://127.0.0.1:9222"
$env:NIGHTMARE_CANVAS_IMAGE_URL = "https://labs.google/fx/vi/tools/flow/project/c1bba921-ab2f-445b-82a0-1240e4da4d29"
$env:NIGHTMARE_CANVAS_VIDEO_URL = "https://labs.google/fx/vi/tools/flow/project/c1bba921-ab2f-445b-82a0-1240e4da4d29"
$env:NIGHTMARE_CANVAS_TIMEOUT_SECONDS = "600"
$env:NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH = "$taskRoot\assets\mrkane-flow-reference.png"

# Flow model and runner settings
$env:NIGHTMARE_FLOW_MODEL_IMAGE = "Nano Banana 2"
$env:NIGHTMARE_FLOW_MODEL_VIDEO = "Omni 1.1 Flash"
$env:NIGHTMARE_FLOW_VIDEO_RESOLUTION = "360p"
$env:NIGHTMARE_FLOW_ASPECT_RATIO = "16:9"
$env:NIGHTMARE_FLOW_VIDEO_INPUT_MODE = "ingredients"
$env:NIGHTMARE_FLOW_VIDEO_DURATION = "6"
$env:NIGHTMARE_FLOW_RUNNER = "auto"

Write-Host "=== Google Flow CDP Preflight Diagnostics ===" -ForegroundColor Cyan

# 1. Check Chrome CDP connectivity
try {
    $resp = Invoke-RestMethod -Uri "$($env:NIGHTMARE_CANVAS_CDP_URL)/json/version" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "[OK] Chrome CDP connected: $($resp.Browser)" -ForegroundColor Green
} catch {
    Write-Host "[INFO] Chrome CDP not currently reachable at $($env:NIGHTMARE_CANVAS_CDP_URL). Auto-launch or start Chrome with --remote-debugging-port=9222" -ForegroundColor Yellow
}

# 2. Check Node / npx availability
$npxCmd = Get-Command npx -ErrorAction SilentlyContinue
if ($npxCmd) {
    Write-Host "[OK] Node/npx available: $($npxCmd.Source)" -ForegroundColor Green
} else {
    Write-Host "[WARN] 'npx' not found in PATH. Subprocess runner requires Node.js." -ForegroundColor Yellow
}

# 3. Check runner script
$runnerPath = Join-Path $taskRoot "scripts\google-flow-cdp-runner.ts"
if (Test-Path $runnerPath) {
    Write-Host "[OK] Flow CDP runner script present: $runnerPath" -ForegroundColor Green
} else {
    Write-Host "[WARN] Runner script missing at $runnerPath" -ForegroundColor Yellow
}

# 4. Check character reference image
if (Test-Path $env:NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH) {
    Write-Host "[OK] Flow character reference found: $($env:NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH)" -ForegroundColor Green
} else {
    Write-Host "[INFO] Character reference not yet generated at $($env:NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH)" -ForegroundColor Yellow
}

Write-Host "Starting Nightmare Studio server (Google Flow CDP)..." -ForegroundColor Cyan
py.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
