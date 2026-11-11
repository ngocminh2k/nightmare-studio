# Start nightmare studio services
# 1. flowkit instance 1 (port 8100) — phải chạy thủ công từ F:\truyen_ma\flowkit
# 2. flowkit instance 2 (port 8101) — phải chạy thủ công
# 3. pool manager (port 8888)
# 4. MCP server (port 8200)

$studioRoot = "F:\truyen_ma\nightmare_studio"
$flowkitRoot = "F:\truyen_ma\flowkit"

# Pool manager
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "cd '$studioRoot'; `$env:FLOW_ACCOUNTS='8100:,8101:'; python -m uvicorn app.pool_manager:app --host 127.0.0.1 --port 8888") -WindowStyle Minimized

Start-Sleep 2

# MCP server
Start-Process powershell -ArgumentList @("-NoExit", "-Command", "cd '$studioRoot'; python -m uvicorn app.mcp_server:app --host 127.0.0.1 --port 8200") -WindowStyle Minimized

Write-Host "Services starting..."
Write-Host "  Pool manager: http://127.0.0.1:8888/api/pool-status"
Write-Host "  MCP server:   http://127.0.0.1:8200/"
Write-Host ""
Write-Host "Flowkit instances must be started manually:"
Write-Host "  Profile 1: cd $flowkitRoot; python -m agent.main --port 8100 --ws-port 9222"
Write-Host "  Profile 2: cd $flowkitRoot; python -m agent.main --port 8101 --ws-port 9223"
