# Start nightmare studio services
# 1. flowkit (port 8100, ws 9222) — phải chạy thủ công từ F:\truyen_ma\flowkit
# 2. MCP server (port 8200)
#
# Chỉ chạy MỘT flowkit. Đổi Google account bằng scripts/switch-account.ps1
# (tuần tự), không chạy song song nhiều profile.

$studioRoot = "F:\truyen_ma\nightmare_studio"
$flowkitRoot = "F:\truyen_ma\flowkit"

# MCP server
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "cd '$studioRoot'; python -m uvicorn app.mcp_server:app --host 127.0.0.1 --port 8200") -WindowStyle Minimized

Write-Host "Services starting..."
Write-Host "  MCP server:   http://127.0.0.1:8200/"
Write-Host ""
Write-Host "Flowkit must be started manually:"
Write-Host "  cd $flowkitRoot; python -m agent.main --port 8100 --ws-port 9222"
Write-Host ""
Write-Host "Switch account (sequential, one flowkit only):"
Write-Host "  $studioRoot\scripts\switch-account.ps1 -Account N"
