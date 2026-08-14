$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location $taskRoot

$env:NIGHTMARE_MEDIA_MODE = "google_flow_cdp"
$env:NIGHTMARE_CANVAS_CDP_URL = "http://127.0.0.1:9222"
$env:NIGHTMARE_CANVAS_IMAGE_URL = "https://labs.google/fx/vi/tools/flow/project/c1bba921-ab2f-445b-82a0-1240e4da4d29"
$env:NIGHTMARE_CANVAS_VIDEO_URL = "https://labs.google/fx/vi/tools/flow/project/c1bba921-ab2f-445b-82a0-1240e4da4d29"
$env:NIGHTMARE_CANVAS_TIMEOUT_SECONDS = "600"
$env:NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH = "$taskRoot\assets\mrkane-flow-reference.png"

py.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
