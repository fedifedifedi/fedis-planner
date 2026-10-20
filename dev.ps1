# Lance l'API (port 8000) et l'interface (port 3000) en local, chacune dans sa fenêtre PowerShell.
# Usage : .\dev.ps1            (interface en mode développement)
#         .\dev.ps1 -Prod      (interface compilée : npm run build puis next start)
param([switch]$Prod)

$root = $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; .venv\Scripts\python.exe -m uvicorn api.main:app --port 8000"
if ($Prod) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run build; if (`$?) { npx next start -p 3000 }"
} else {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
}
Write-Host "API : http://127.0.0.1:8000/docs   Interface : http://localhost:3000"
