param(
    [Parameter(Mandatory = $true)][string]$Prompt,
    [ValidateSet("image", "video")][string]$Mode = "image",
    [string]$AspectRatio = "16:9",
    [string]$Model = "",
    [int]$Variants = 1,
    [int]$Duration = 6,
    [string]$Resolution = "360p",
    [ValidateSet("frames", "ingredients")][string]$VideoInputMode = "ingredients",
    [string[]]$Media = @(),
    [string]$Output = "",
    [string]$Cdp = "",
    [string]$ProjectUrl = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = $PSScriptRoot
$runnerScript = Join-Path $scriptRoot "google-flow-cdp-runner.ts"

if (-not (Test-Path $runnerScript)) {
    Write-Error "Runner script not found at $runnerScript"
    exit 1
}

$cdpTarget = if ($Cdp) { $Cdp } elseif ($env:NIGHTMARE_CANVAS_CDP_URL) { $env:NIGHTMARE_CANVAS_CDP_URL } else { "http://127.0.0.1:9222" }
$urlTarget = if ($ProjectUrl) {
    $ProjectUrl
} elseif ($Mode -eq "image" -and $env:NIGHTMARE_CANVAS_IMAGE_URL) {
    $env:NIGHTMARE_CANVAS_IMAGE_URL
} elseif ($Mode -eq "video" -and $env:NIGHTMARE_CANVAS_VIDEO_URL) {
    $env:NIGHTMARE_CANVAS_VIDEO_URL
} else {
    $env:GOOGLE_FLOW_PROJECT_URL
}

$cmdArgs = @("--yes", "tsx", $runnerScript, "--prompt", $Prompt, "--mode", $Mode, "--aspectRatio", $AspectRatio, "--variants", $Variants)
if ($Model) {
    $cmdArgs += @("--model", $Model)
} elseif ($Mode -eq "video") {
    $cmdArgs += @("--model", "Omni 1.1 Flash")
}
if ($Mode -eq "video") {
    $cmdArgs += @("--duration", $Duration, "--resolution", $Resolution, "--videoInputMode", $VideoInputMode)
}
if ($Output) {
    $cmdArgs += @("--output", $Output)
}
if ($cdpTarget) {
    $cmdArgs += @("--cdp", $cdpTarget)
}
if ($urlTarget) {
    $cmdArgs += @("--projectUrl", $urlTarget)
}
if ($Media.Count -gt 0) {
    $cmdArgs += "--media"
    $cmdArgs += $Media
}

Write-Host "Executing Google Flow CDP Runner ($Mode)..." -ForegroundColor Cyan
& npx @cmdArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
