# Start 7 parallel Nightmare Studio workers, one per Chrome CDP account
# Each worker handles a slice of scenes (round-robin job assignment via API)
#
# Usage: .\scripts\start-live-flow-multi.ps1

$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location $taskRoot

$Accounts = @(
    @{ port = 9223; httpPort = 8001 },
    @{ port = 9224; httpPort = 8002 },
    @{ port = 9225; httpPort = 8003 },
    @{ port = 9226; httpPort = 8004 },
    @{ port = 9227; httpPort = 8005 },
    @{ port = 9228; httpPort = 8006 },
    @{ port = 9229; httpPort = 8007 }
)

foreach ($acc in $Accounts) {
    $env:NIGHTMARE_MEDIA_MODE              = "google_flow_cdp"
    $env:NIGHTMARE_CANVAS_CDP_URL          = "http://127.0.0.1:$($acc.port)"
    $env:NIGHTMARE_CANVAS_IMAGE_URL        = $env:NIGHTMARE_CANVAS_IMAGE_URL ?? "https://labs.google/fx/vi/tools/flow/project/c1bba921-ab2f-445b-82a0-1240e4da4d29"
    $env:NIGHTMARE_CANVAS_VIDEO_URL        = $env:NIGHTMARE_CANVAS_VIDEO_URL ?? "https://labs.google/fx/vi/tools/flow/project/c1bba921-ab2f-445b-82a0-1240e4da4d29"
    $env:NIGHTMARE_CANVAS_TIMEOUT_SECONDS  = "600"
    $env:NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH = "$taskRoot\assets\mrkane-flow-reference.png"
    $env:NIGHTMARE_FLOW_MODEL_IMAGE        = "Nano Banana 2"
    $env:NIGHTMARE_FLOW_MODEL_VIDEO        = "Omni 1.1 Flash"
    $env:NIGHTMARE_FLOW_VIDEO_RESOLUTION   = "360p"
    $env:NIGHTMARE_FLOW_ASPECT_RATIO       = "16:9"
    $env:NIGHTMARE_FLOW_VIDEO_INPUT_MODE   = "ingredients"
    $env:NIGHTMARE_FLOW_VIDEO_DURATION     = "6"
    $env:NIGHTMARE_FLOW_RUNNER             = "auto"

    $logFile = "$taskRoot\logs\worker-$($acc.httpPort).log"
    New-Item -ItemType Directory -Force -Path "$taskRoot\logs" | Out-Null

    $cmd = "py.exe -m uvicorn app.main:app --host 127.0.0.1 --port $($acc.httpPort)"
    Start-Process powershell -ArgumentList "-NoProfile -Command `"Set-Location '$taskRoot'; `$env:NIGHTMARE_CANVAS_CDP_URL='http://127.0.0.1:$($acc.port)'; `$env:NIGHTMARE_MEDIA_MODE='google_flow_cdp'; $cmd`" > '$logFile' 2>&1" -WindowStyle Minimized
    Write-Host "[OK] Worker port $($acc.httpPort) → CDP $($acc.port)" -ForegroundColor Green
    Start-Sleep -Milliseconds 300
}

Write-Host ""
Write-Host "7 workers running on ports 8001-8007" -ForegroundColor Cyan
Write-Host "Logs: $taskRoot\logs\worker-800*.log" -ForegroundColor Yellow
