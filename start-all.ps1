Write-Host "MD System - Starting all services locally..." -ForegroundColor Cyan

# 1. Independent Vault
Write-Host "Installing Vault dependencies..." -ForegroundColor Yellow
Push-Location .\independent-vault
npm install
Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run dev"
Pop-Location

# 2. Merkle Aggregator
Write-Host "Installing Aggregator dependencies..." -ForegroundColor Yellow
Push-Location .\merkle-aggregator
npm install
Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run dev"
Pop-Location

# 3. Verifier DApp
Write-Host "Installing Verifier DApp dependencies..." -ForegroundColor Yellow
Push-Location .\verifier-dapp
npm install
Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run dev" -Environment @{PORT="3001"}
Pop-Location

# 4. Hardware Emulator
Write-Host "Installing Emulator dependencies..." -ForegroundColor Yellow
Push-Location .\hardware-emulator
pip install -r requirements.txt
Start-Process -NoNewWindow -FilePath "python" -ArgumentList "main.py"
Pop-Location

Write-Host "All services started!" -ForegroundColor Green
Write-Host "Vault (API): http://localhost:4000"
Write-Host "Aggregator (API): http://localhost:3000"
Write-Host "Verifier DApp (UI): http://localhost:3001"
Write-Host "Press any key to exit this script (services will continue running in the background of your terminal session)"
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
