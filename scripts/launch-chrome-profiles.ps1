# Launch 7 Chrome instances with separate profiles and CDP ports (9223-9229)
# Each instance = 1 Google account. Sign in manually after first launch.
#
# Usage: .\scripts\launch-chrome-profiles.ps1
# To kill all:  Get-Process chrome | Stop-Process (careful — kills ALL Chrome)

$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$ProfileRoot = "F:\truyen_ma\chrome-profiles"

$Accounts = @(
    @{ id = 1; port = 9223; name = "account-01" },
    @{ id = 2; port = 9224; name = "account-02" },
    @{ id = 3; port = 9225; name = "account-03" },
    @{ id = 4; port = 9226; name = "account-04" },
    @{ id = 5; port = 9227; name = "account-05" },
    @{ id = 6; port = 9228; name = "account-06" },
    @{ id = 7; port = 9229; name = "account-07" }
)

foreach ($acc in $Accounts) {
    $profileDir = Join-Path $ProfileRoot $acc.name
    New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

    $args = @(
        "--remote-debugging-port=$($acc.port)",
        "--user-data-dir=$profileDir",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "https://accounts.google.com"
    )

    Start-Process -FilePath $Chrome -ArgumentList $args
    Write-Host "[OK] account-$($acc.id) → port $($acc.port) → $profileDir" -ForegroundColor Green
    Start-Sleep -Milliseconds 500
}

Write-Host ""
Write-Host "7 Chrome instances launched on ports 9223-9229." -ForegroundColor Cyan
Write-Host "Sign in to each Google account, then run start-live-flow-multi.ps1" -ForegroundColor Yellow
