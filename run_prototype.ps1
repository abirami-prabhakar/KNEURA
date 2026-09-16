param([ValidateRange(1,65535)][int]$Port = 8000, [switch]$Install, [switch]$MockLlm, [switch]$Setup)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $prototypePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $prototypePython)) {
        py -3.12 -m venv (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64, then rerun this script.' }
        $Install = $true
    }
    & $prototypePython -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'The .venv must use Python 3.12 x64. Recreate it; do not copy a venv between laptops.' }
    if ($Install) {
        & $prototypePython -u -m pip install -r (Join-Path $PSScriptRoot 'backend 1\requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the pip error above and connectivity to PyPI and download.pytorch.org.' }
    }
    if (-not $env:KNEE_AI_DATABASE_URL) {
        $env:KNEE_AI_DATABASE_URL = 'sqlite:///' + (Join-Path $PSScriptRoot 'kneura_demo.db').Replace('\', '/')
    }
    # Resolve SQLite and relative overrides once, before any child process starts.
    # Resolve SQLite safely without fragile python -c quoting.
    $DbCheck = @"
import os
from pathlib import Path
from sqlalchemy.engine import make_url

u = make_url(os.environ["KNEE_AI_DATABASE_URL"])

assert u.get_backend_name() == "sqlite", "SQLite is required"
assert u.database, "Database path is missing"
assert u.database != ":memory:", "Use a persistent SQLite database"

print(Path(u.database).expanduser().resolve())
"@

    $prototypeDb = $DbCheck | & $prototypePython -

    if ($LASTEXITCODE -ne 0) {
        throw 'Invalid KNEE_AI_DATABASE_URL. Use sqlite:///C:/path/to/kneura_demo.db.'
    }

    $prototypeDb = "$prototypeDb".Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Invalid KNEE_AI_DATABASE_URL. Use sqlite:///C:/path/to/kneura_demo.db.' }
    $env:KNEE_AI_DATABASE_URL = 'sqlite:///' + $prototypeDb.Replace('\', '/')
    if (-not $env:KNEE_AI_STUDY_ROOT) { $env:KNEE_AI_STUDY_ROOT = Join-Path $PSScriptRoot '.prototype_data\uploads' }
    foreach ($prototypeName in @('KNEE_AI_STUDY_ROOT','KNEE_AI_MEMBER2_PATH','KNEE_AI_SERIES_METADATA_PATH','KNEE_AI_CHECKPOINT_PATH')) {
        $prototypeValue = [Environment]::GetEnvironmentVariable($prototypeName)
        if ($prototypeValue) {
            $prototypeResolved = & $prototypePython -c 'import sys; from pathlib import Path; print(Path(sys.argv[1]).expanduser().resolve())' $prototypeValue
            if ($LASTEXITCODE -ne 0) { throw "Invalid path in $prototypeName." }
            [Environment]::SetEnvironmentVariable($prototypeName, $prototypeResolved, 'Process')
        }
    }
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONUNBUFFERED = '1'
    if (-not $env:OMP_NUM_THREADS) { $env:OMP_NUM_THREADS = '2' }
    if (-not $env:MKL_NUM_THREADS) { $env:MKL_NUM_THREADS = '2' }
    $prototypeListeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    # CIM can be unavailable in restricted shells; netstat still reports owners.
    if (-not $prototypeListeners.Count) {
        $prototypeListeners = @(netstat -ano -p tcp | ForEach-Object {
            if ($_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
                [pscustomobject]@{ OwningProcess = [int]$Matches[1] }
            }
        })
    }
    if ($prototypeListeners.Count) {
        foreach ($prototypeListener in $prototypeListeners) {
            $prototypeOwner = Get-Process -Id $prototypeListener.OwningProcess -ErrorAction SilentlyContinue
            Write-Host "Port $Port is occupied by PID $($prototypeListener.OwningProcess) ($($prototypeOwner.ProcessName))."
        }
        throw "An existing server may still be alive. Check http://127.0.0.1:$Port/ and stop your own server with Ctrl+C, or use -Port 8001. No processes were killed."
    }
    & $prototypePython -u (Join-Path $PSScriptRoot 'scripts\check_environment.py') --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Environment preflight failed. Follow the remediation above.' }
    if (-not $env:KNEE_AI_AUTH_SECRET) {
        $prototypeSecret = New-Object byte[] 32
        $prototypeRng = [Security.Cryptography.RandomNumberGenerator]::Create()
        $prototypeRng.GetBytes($prototypeSecret)
        $prototypeRng.Dispose()
        $env:KNEE_AI_AUTH_SECRET = [Convert]::ToBase64String($prototypeSecret)
    }
    if ($Setup -or -not (Test-Path -LiteralPath $prototypeDb)) {
        if (-not $prototypeDb.EndsWith('kneura_demo.db')) { throw 'Demo setup requires a SQLite database named kneura_demo.db. Set KNEE_AI_DATABASE_URL accordingly.' }
        & $prototypePython -u 'backend 1\scripts\create_demo_users.py'
        if ($LASTEXITCODE -ne 0) { throw "Demo setup failed (exit $LASTEXITCODE)." }
        & $prototypePython -u 'backend 1\scripts\load_demo_study.py' --all
        if ($LASTEXITCODE -ne 0) { throw "Demo ingestion failed (exit $LASTEXITCODE). Rerun with -Setup after fixing the error." }
    } else {
        Write-Host 'Using existing database, accounts, studies, and reports. Use -Setup for explicit setup.'
    }
    if (-not $MockLlm -and -not $env:GEMINI_API_KEY) {
        Write-Host 'GEMINI_API_KEY absent: using explicit MOCK provider. LIVE GEMINI: NOT TESTED.'
        $MockLlm = $true
    }
    Write-Host "Open http://127.0.0.1:$Port/ . Keep this terminal open; Ctrl+C stops the server."
    if ($MockLlm) {
        & $prototypePython -u 'backend 1\scripts\serve_mock_provider.py' --port $Port
    } else {
        & $prototypePython -u -m uvicorn app.main:app --app-dir 'backend 1' --host 127.0.0.1 --port $Port
    }
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE. See server output above." }
} finally {
    Pop-Location
}

