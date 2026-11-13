# Launch N ungoogled-chromium instances, each with its own persistent profile.
#
# Usage:
#   .\scripts\launch-chromium-profiles.ps1                 # 10 instances, ports 9233-9242
#   .\scripts\launch-chromium-profiles.ps1 -Count 3        # only 3
#   .\scripts\launch-chromium-profiles.ps1 -StartPort 9300
#
# Profiles live in $ProfileRoot\chromium-NN and are reused on the next launch
# (cookies / Google sign-in persist). Each instance gets its own CDP port.
#
# The FlowKit extension is deliberately NOT loaded: FlowKit is a single-instance
# bridge (one ws server at :8100), so 10 extensions would fight over it. Use
# .\scripts\switch-account.ps1 for the pipeline's signed-in instance.

param(
    [int]$Count     = 10,
    [int]$StartPort = 9233,
    [string]$Url    = "https://accounts.google.com"
)

$ErrorActionPreference = "Stop"

$ChromiumExe = "F:\truyen_ma\chromium\ungoogled-chromium_156.0.8078.79-1.1_windows_x64\chrome.exe"
$ProfileRoot = "F:\truyen_ma\chrome-profiles"

if (-not (Test-Path $ChromiumExe)) {
    Write-Error "Chromium executable missing: $ChromiumExe"
    exit 1
}
New-Item -ItemType Directory -Force $ProfileRoot | Out-Null

for ($i = 0; $i -lt $Count; $i++) {
    $n = $i + 1
    $name = "chromium-{0:D2}" -f $n
    $port = $StartPort + $i
    $profileDir = Join-Path $ProfileRoot $name
    New-Item -ItemType Directory -Force $profileDir | Out-Null

    Start-Process -FilePath $ChromiumExe -ArgumentList @(
        "--remote-debugging-port=$port",
        "--user-data-dir=$profileDir",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--new-window",
        $Url
    )
    Write-Host ("[OK] {0} -> port {1} -> {2}" -f $name, $port, $profileDir) -ForegroundColor Green
    Start-Sleep -Milliseconds 700
}

Write-Host ""
Write-Host "$Count Chromium instances launched on ports $StartPort-$($StartPort + $Count - 1)." -ForegroundColor Cyan
Write-Host "Profiles persist in $ProfileRoot - sign in once per profile, reuse later." -ForegroundColor Yellow
