$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $workspace
& (Join-Path $workspace 'run_kneura.ps1') -LoadOnly
foreach ($port in @(8000,5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Use the existing service or stop it explicitly before starting another."
    }
}
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
$logRoot = Join-Path $workspace '.kneura\presentation-logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$apiProcess = Start-Process -FilePath 'python' -ArgumentList @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $workspace -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$stamp-api.out.log") -RedirectStandardError (Join-Path $logRoot "$stamp-api.err.log")
$uiProcess = Start-Process -FilePath 'node' -ArgumentList @('node_modules/vite/bin/vite.js','preview','--host','127.0.0.1','--port','5173','--strictPort') -WorkingDirectory $workspace -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$stamp-ui.out.log") -RedirectStandardError (Join-Path $logRoot "$stamp-ui.err.log")
@{ apiPid=$apiProcess.Id; uiPid=$uiProcess.Id; startedAt=(Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot "$stamp-processes.json")
Write-Output "Started local presentation processes: API $($apiProcess.Id), UI $($uiProcess.Id)."
Write-Output 'Open http://127.0.0.1:5173/login. The report worker runs inside the API process.'
Write-Output 'Run python scripts/preflight.py --model to verify readiness. Local loopback HTTP is not an HTTPS deployment.'
Write-Output 'Stop these specific processes before backup. Process IDs and logs are recorded under .kneura/presentation-logs.'
