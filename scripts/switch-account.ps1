#!/usr/bin/env pwsh
# switch-account.ps1 - switch the Google Flow account used by the render pipeline.
#
# Usage:
#   .\scripts\switch-account.ps1 -List                              # registry + live flowkit status
#   .\scripts\switch-account.ps1 -Account 2                         # switch to account 2
#   .\scripts\switch-account.ps1 -Account 2 -ProjectId "<uuid>"     # switch and register a known UUID
#   .\scripts\switch-account.ps1 -Account 2 -NoBrowser              # register only, do not launch Chromium
#
# What a switch does:
#   1. restart Chromium on the account's profile (--user-data-dir=account-NN) so the
#      FlowKit extension reconnects under the new Google account
#   2. if that account has no Flow project yet, create one through the extension
#      (a Flow project belongs to the account that created it)
#   3. lift the FlowKit unusual-activity hold (it is global, not per account)
#   4. verify the account can run a real Flow RPC against that project
#   5. mark the account active in data/flow-accounts.json and update NIGHTMARE_FLOWKIT_PROJECT
#   6. restart the render pipeline, which resumes the episode and skips finished clips
#
# Signing in: Chromium opens on flow.google.com under the target profile. Sign in to
# Google there when the account is new - the script keeps retrying and picks up the
# session automatically. Each account keeps its own profile, so sign-ins never clash.
#
# NOTE: your normal Google Chrome is never touched - only the ungoogled-chromium instances.

param(
    [int]$Account      = 0,
    [string]$ProjectId = "",
    [switch]$List,
    [switch]$NoBrowser,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"

$ChromiumExe  = "F:\truyen_ma\chromium\ungoogled-chromium_156.0.8078.79-1.1_windows_x64\chrome.exe"
$ProfilesRoot = "F:\truyen_ma\chrome-profiles"
$ExtensionDir = "F:\truyen_ma\flowkit\extension"
$AccountsJson = Join-Path (Split-Path -Parent $PSScriptRoot) "data\flow-accounts.json"
$StudioEnv    = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"

# -- Registry helpers ----------------------------------------------------------
function Get-Registry {
    if (-not (Test-Path $AccountsJson)) {
        return [PSCustomObject]@{ active_account = 0; accounts = @() }
    }
    try {
        $raw = Get-Content $AccountsJson -Encoding utf8 -Raw | ConvertFrom-Json
        if ($null -eq $raw) {
            return [PSCustomObject]@{ active_account = 0; accounts = @() }
        }
        $accounts = @()
        if ($raw.accounts) { $accounts = @($raw.accounts) }
        elseif ($raw.id)   { $accounts = @($raw) }
        $active = 0
        if ($raw.PSObject.Properties.Name -contains "active_account") { $active = [int]$raw.active_account }
        elseif ($accounts.Count -eq 1) { $active = [int]$accounts[0].id }
        return [PSCustomObject]@{ active_account = $active; accounts = $accounts }
    } catch {
        Write-Warning "Could not parse $AccountsJson; starting a fresh registry."
        return [PSCustomObject]@{ active_account = 0; accounts = @() }
    }
}

function Save-Registry($registry) {
    $dir = Split-Path -Parent $AccountsJson
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
    $payload = [PSCustomObject]@{
        active_account = [int]$registry.active_account
        accounts       = @($registry.accounts)
    }
    $json = $payload | ConvertTo-Json -Depth 5
    $tmp = "$AccountsJson.tmp"
    [System.IO.File]::WriteAllText($tmp, $json, [System.Text.Encoding]::UTF8)
    Move-Item -Path $tmp -Destination $AccountsJson -Force   # atomic: readers never see a half file
}

function Set-EnvKey($filePath, $key, $value) {
    if (-not (Test-Path $filePath)) { return }
    $lines = @(Get-Content $filePath -Encoding utf8)
    $out = @()
    $replaced = $false
    foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($key))=") {
            $out += "$key=$value"
            $replaced = $true
        } else {
            $out += $line
        }
    }
    if (-not $replaced) { $out += "$key=$value" }
    [System.IO.File]::WriteAllLines($filePath, $out, [System.Text.Encoding]::UTF8)
}

function Get-FlowkitBase {
    $base = "http://127.0.0.1:8100"
    if (Test-Path $StudioEnv) {
        $m = Select-String -Path $StudioEnv -Pattern '^NIGHTMARE_FLOWKIT_URL=(.*)$' -ErrorAction SilentlyContinue
        if ($m) { $base = $m.Matches[0].Groups[1].Value.Trim() }
    }
    return $base.TrimEnd('/')
}

function Get-FlowkitHealth($base) {
    try {
        return Invoke-RestMethod -Uri "$base/health" -TimeoutSec 3 -ErrorAction Stop
    } catch {
        return $null
    }
}

$registry = Get-Registry
$flowkitBase = Get-FlowkitBase

# -- -List: registry + live status ---------------------------------------------
if ($List) {
    Write-Host "`n=== Flow accounts ($AccountsJson) ===" -ForegroundColor Cyan
    if (@($registry.accounts).Count -eq 0) {
        Write-Host "  (none registered)" -ForegroundColor Gray
    }
    foreach ($a in $registry.accounts) {
        $mark = if ([int]$a.id -eq [int]$registry.active_account) { "ACTIVE" } else { "" }
        $prof = "$ProfilesRoot\account-$('{0:D2}' -f $a.id)"
        $profMark = if (Test-Path $prof) { "profile: yes" } else { "profile: NO" }
        Write-Host ("  [{0}] id={1} project={2}  {3}  {4}" -f $mark, $a.id, $a.project_id, $profMark, "")
    }
    $health = Get-FlowkitHealth $flowkitBase
    Write-Host "`n=== FlowKit ($flowkitBase) ===" -ForegroundColor Cyan
    if (-not $health) {
        Write-Host "  not reachable" -ForegroundColor Red
    } else {
        Write-Host ("  extension_connected : {0}" -f $health.extension_connected) -ForegroundColor Gray
        Write-Host ("  active connections  : {0}" -f $health.ws.active_connections) -ForegroundColor Gray
        Write-Host ("  connects / disconn. : {0} / {1}" -f $health.ws.connects, $health.ws.disconnects) -ForegroundColor Gray
    }
    try {
        $st = Invoke-RestMethod -Uri "$flowkitBase/api/flow/status" -TimeoutSec 3 -ErrorAction Stop
        $th = $st.generation_throttle
        Write-Host ("  cooldown            : {0} ({1}s, reason={2})" -f $th.cooldown_active, [math]::Round($th.cooldown_remaining_s,1), $th.cooldown_reason) -ForegroundColor Gray
    } catch {}
    Write-Host ""
    exit 0
}

if ($Account -le 0) {
    Write-Host "Usage: .\scripts\switch-account.ps1 -Account <N> [-ProjectId <uuid>] [-List] [-NoBrowser]" -ForegroundColor Yellow
    exit 1
}

# -- Resolve the Flow project UUID for this account (or prompt once browser opens)
$entry = @($registry.accounts) | Where-Object { [int]$_.id -eq $Account } | Select-Object -First 1
if (-not $ProjectId -and $entry -and $entry.project_id) {
    $ProjectId = [string]$entry.project_id
    Write-Host "Project UUID for account $Account (from registry): $ProjectId" -ForegroundColor Gray
}
if (-not $ProjectId -and $NoBrowser) {
    Write-Error "Account $Account has no Flow project on record and -NoBrowser cannot create one. Pass -ProjectId <uuid>."
    exit 1
}

# -- Stop our Chromium (never the user's normal Chrome) ------------------------
$beforeHealth = Get-FlowkitHealth $flowkitBase
$beforeConnects = 0
if ($beforeHealth -and $beforeHealth.ws) { $beforeConnects = [int]$beforeHealth.ws.connects }

$crProcs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
           Where-Object { $_.ExecutablePath -like "*ungoogled-chromium*" }
if ($crProcs) {
    Write-Host "Stopping $($crProcs.Count) ungoogled-chromium process(es)..." -ForegroundColor Yellow
    foreach ($p in $crProcs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
    Start-Sleep -Milliseconds 1200
} else {
    Write-Host "No ungoogled-chromium running." -ForegroundColor Gray
}

# -- Launch Chromium on the account's profile ----------------------------------
$profileDir = "$ProfilesRoot\account-$('{0:D2}' -f $Account)"
$flowUrl = if ($ProjectId) { "https://labs.google/fx/vi/tools/flow/project/$ProjectId" } else { "https://flow.google.com" }
if (-not $NoBrowser) {
    if (-not (Test-Path $ChromiumExe)) {
        Write-Error "Chromium executable missing: $ChromiumExe"
        exit 1
    }
    New-Item -ItemType Directory -Force $profileDir | Out-Null
    Write-Host "Launching Chromium profile: account-$('{0:D2}' -f $Account)" -ForegroundColor Cyan
    Write-Host "Opening: $flowUrl" -ForegroundColor Cyan
    Start-Process $ChromiumExe -ArgumentList @(
        "--user-data-dir=$profileDir",
        "--load-extension=$ExtensionDir",
        "--no-first-run",
        "--no-default-browser-check",
        $flowUrl
    )
}

# -- Wait for the extension to reconnect under the new account -----------------
Write-Host "Waiting for the FlowKit extension to connect..." -ForegroundColor Gray
$deadline = (Get-Date).AddSeconds(120)
$ready = $false
while ((Get-Date) -lt $deadline) {
    $health = Get-FlowkitHealth $flowkitBase
    if ($health -and $health.extension_connected -and $health.ws -and [int]$health.ws.connects -gt $beforeConnects) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 2
}
if ($ready) {
    Write-Host "Extension connected." -ForegroundColor Green
} else {
    Write-Warning "The extension has not reconnected yet."
    Write-Host "  -> Sign in to Google in the Chromium window that just opened." -ForegroundColor Yellow
    Write-Host "  -> The pipeline keeps retrying, so you can sign in at any time." -ForegroundColor Yellow
}

# -- Get a working project for this account, then prove the account can use it -
# A Flow project belongs to the Google account that created it, so a new account
# needs a new project. FlowKit creates it through the extension, which returns
# the project uuid directly - no manual copy/paste from the URL.
# The proof is a real Flow RPC against that project: it only answers when the
# browser session is authenticated and the project belongs to that account. A
# project the account cannot see answers with a short error envelope (~143
# bytes) instead of the real listing, so the payload size is the discriminator.
if (-not $ProjectId) {
    Write-Host "`nNo Flow project on record for account $Account - creating one under this account." -ForegroundColor Yellow
    Write-Host "Sign in to Google in the Chromium window that just opened (flow.google.com)." -ForegroundColor Yellow
    Write-Host "If Google sends you to accounts.google.com, sign in there and then" -ForegroundColor Yellow
    Write-Host "navigate back to https://flow.google.com/ - the RPC needs that page." -ForegroundColor Yellow
}
Write-Host "Waiting for the account to sign in and own a Flow project ..." -ForegroundColor Gray
$deadline2 = (Get-Date).AddSeconds(1800)
$probed = $false
while ((Get-Date) -lt $deadline2) {
    $health = Get-FlowkitHealth $flowkitBase
    if ($health -and $health.extension_connected) {
        if (-not $ProjectId) {
            try {
                $body = @{ name = "Nightmare Studio - account $Account"; material = "realistic" } | ConvertTo-Json
                $created = Invoke-RestMethod -Uri "$flowkitBase/api/projects" -Method Post -ContentType "application/json" `
                            -Body $body -TimeoutSec 60 -ErrorAction Stop
                if ($created.id) {
                    $ProjectId = [string]$created.id
                    Write-Host "Created Flow project $ProjectId under account $Account." -ForegroundColor Green
                }
            } catch {
                # Not signed in yet, or the RPC failed - retry until the deadline.
            }
        }
        if ($ProjectId) {
            try {
                $probe = Invoke-RestMethod -Uri "$flowkitBase/api/flow/debug-project-media?project_id=$ProjectId" -TimeoutSec 90 -ErrorAction Stop
                if ([int]$probe.raw_length -gt 1000) { $probed = $true; break }
            } catch {
            }
        }
    }
    Start-Sleep -Seconds 5
}
if (-not $probed) {
    Write-Warning "Could not reach Google Flow with this account. Active account left unchanged."
    Write-Host "  -> Sign in to Google in the Chromium window (each account has its own profile)." -ForegroundColor Yellow
    Write-Host "  -> Make sure the page is flow.google.com, not accounts.google.com." -ForegroundColor Yellow
    Write-Host "  -> Then re-run: .\scripts\switch-account.ps1 -Account $Account" -ForegroundColor Yellow
    exit 1
}
Write-Host "Account $Account is signed in and owns project $ProjectId ($($probe.found_uuids_count) media items)." -ForegroundColor Green

# -- Lift the global generation hold (it belongs to the old account) -----------
try {
    $r = Invoke-RestMethod -Uri "$flowkitBase/api/flow/clear-hijack" -Method Post -ContentType "application/json" -Body "{}" -TimeoutSec 5 -ErrorAction Stop
    Write-Host ("Cleared generation hold (was_active={0})." -f $r.was_active) -ForegroundColor Green
} catch {
    Write-Warning "Could not clear the generation hold: $_"
}

# -- Persist the account in the registry ---------------------------------------
$accounts = @()
$found = $false
foreach ($a in @($registry.accounts)) {
    if ([int]$a.id -eq $Account) {
        $accounts += [PSCustomObject]@{ id = [int]$Account; project_id = $ProjectId }
        $found = $true
    } else {
        $accounts += $a
    }
}
if (-not $found) {
    $accounts += [PSCustomObject]@{ id = [int]$Account; project_id = $ProjectId }
}
$registry.accounts = $accounts

# -- Make the account active for the running pipeline --------------------------
$registry.active_account = [int]$Account
Save-Registry $registry
Write-Host "Active account set to $Account (project $ProjectId) in $AccountsJson" -ForegroundColor Green

Set-EnvKey $StudioEnv "NIGHTMARE_FLOWKIT_PROJECT" $ProjectId
Write-Host ".env: NIGHTMARE_FLOWKIT_PROJECT=$ProjectId" -ForegroundColor Green

# -- Restart the render pipeline so it loads the new project id ----------------
if (-not $NoRestart) {
    $jobProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                  Where-Object { $_.CommandLine -like "*produce-full-episode*" })
    foreach ($p in $jobProcs) {
        Write-Host "Stopping render job (PID $($p.ProcessId))..." -ForegroundColor Yellow
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
    if ($jobProcs.Count -gt 0) { Start-Sleep -Seconds 2 }
    $root = Split-Path -Parent $PSScriptRoot
    $logDir = Join-Path $root "logs"
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
    # The produce script auto-resumes the episode that is still in progress, so
    # starting it is safe whether or not a job was running before the switch.
    Start-Process "python" -ArgumentList "-u", "scripts/produce-full-episode.py" -WorkingDirectory $root `
        -RedirectStandardOutput (Join-Path $logDir "production.log") `
        -RedirectStandardError (Join-Path $logDir "production.err") -WindowStyle Minimized
    Write-Host "Render job started on account $Account (logs/production.log)." -ForegroundColor Green
} else {
    Write-Host "Skipping render job restart (-NoRestart specified)." -ForegroundColor Gray
}

Write-Host ""
Write-Host "Switch done." -ForegroundColor Cyan
Write-Host "  profile : $profileDir" -ForegroundColor Gray
Write-Host "  project : $ProjectId" -ForegroundColor Gray
