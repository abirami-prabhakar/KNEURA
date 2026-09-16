# KNEURA prototype: Windows setup and demonstration

Requires Windows 10/11 x64, Python 3.12.x x64, and internet access for package installation and the existing frontend CDN fonts/Tailwind. No GPU or Node.js is required.

Copy the complete project, including `backend 1`, `backend 2`, `member2_llm`, `frontend`, `demo_inputs`, and `kneura_demo.db`. Do NOT copy `.venv` between laptops. The supplied database contains the real case 7 predictions, review, and mock report. Without it, setup registers studies but does not invent predictions or clinician decisions.

## Fresh laptop

```powershell
cd 'C:\path\to\KNEURA'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r '.\backend 1\requirements.txt'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\run_prototype.ps1' -Setup -MockLlm
```

The execution-policy option applies only to that PowerShell process. If scripts are already allowed, use `.\run_prototype.ps1 -Setup -MockLlm` directly. Setup preserves existing passwords, findings, review decisions, and reports and updates demo paths for the current laptop. If the database is missing, setup prompts for a password of at least 12 characters; choose your own, or use the demo password below.

## Normal startup

```powershell
cd 'C:\Users\praka\Documents\ChatGPT\KNEURA'
.\run_prototype.ps1 -MockLlm
```

From any other directory, invoke the script by its full quoted path with `&`. The server runs in the foreground until Ctrl+C; keep the terminal open. Normal launch reuses the database and never scans DICOMs or recreates demo users. `-Install` explicitly repairs dependencies; `-Setup` explicitly runs setup. Missing Gemini credentials automatically select the labelled mock provider.

Open http://127.0.0.1:8000/ . Existing demo login:

- Email: `radiologist@kneura.local`
- Password: `Kneura-demo-74cP!2026`

## Environment checks and configuration

```powershell
.\.venv\Scripts\python.exe .\scripts\check_environment.py --hash
# While a server is already running:
.\.venv\Scripts\python.exe .\scripts\check_environment.py --skip-port
```

Preflight checks exact direct dependency versions without loading Torch, required paths, writable database/upload/temp locations, and port availability. Hashing is optional so normal startup remains fast. Canonical dependencies are in `backend 1/requirements.txt`; installation was checked with pip dry-run against the working environment, not on a second physical laptop.

Launcher defaults are anchored to the script directory. Relative path overrides are resolved from the project root. Child processes inherit environment variables:

- `KNEE_AI_DATABASE_URL`: persistent SQLite URL, default `sqlite:///C:/.../KNEURA/kneura_demo.db`. Demo setup requires filename `kneura_demo.db`; an existing custom database is reused without automatic setup.
- `KNEE_AI_MEMBER2_PATH`: optional; defaults to sibling `member2_llm`.
- `KNEE_AI_STUDY_ROOT`: writable upload directory, default `.prototype_data/uploads`. Demo studies use their persisted `demo_inputs/DICOM` paths.
- `KNEE_AI_SERIES_METADATA_PATH`: optional series metadata override; persisted demo studies retain their own manifest path.
- `KNEE_AI_AUTH_SECRET`: optional stable signing secret; otherwise generated for the launcher session. Sign in again after a server restart.
- `GEMINI_API_KEY`: needed only for live mode (omit `-MockLlm`). It is never sent to the frontend. Mock mode patches the SDK inside the server process only.
- `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1` are set for child processes.

Port conflicts report the owning PID/process and do not kill anything. An old server may still be alive even when a tooling handle disappears. Inspect `Get-NetTCPConnection -LocalPort 8000 -State Listen` and `Get-Process -Id <PID>`, return to your own server terminal and press Ctrl+C, or launch with `-Port 8001`. For access errors, move the workspace to a writable user directory and check `%TEMP%`. Do not run as administrator just to mask path errors.

## One-minute presentation

1. Sign in and show the 10 registered real MRI studies.
2. Select case 7, study UID ending `90283565381042081768587894596970552767`.
3. Show all 12 persisted real Model 1 probabilities; no inference rerun is needed.
4. Show confirmed Effusion, edited MCL, and 10 rejected findings.
5. Show the persisted report, its explicit MOCK PROVIDER note, DRAFT status, and `final_approval=PENDING`.

The existing case is already at REPORT_DRAFT. Generating a second draft or resubmitting review is intentionally rejected by the workflow state machine. Report generation through the real Member 2 pipeline with a mocked provider was previously verified. Do not reset clinician state for the presentation. Live Gemini: NOT TESTED (no credential available).

## Completion checklist

- [x] runtime/environment verified
- [x] launcher/backend stable
- [x] authentication
- [x] frontend served
- [x] real Model 1 (previously verified; frozen checkpoint hash checked)
- [x] study/review workflow (persisted case)
- [x] Member 2 (previous focused tests; mock report retrieval)
- [x] persistence
- [x] frontend API wiring
- [x] final smoke test (see verification/runtime_checks.json); browser login and case 7 display verified

