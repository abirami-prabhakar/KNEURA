# KNEE-AI 3.3 backend

The API calls the frozen `ai/knee_ai_inference.py` module directly. Do not edit
that file or `best_5slice_model.pth`.

## Windows CPU setup

Python 3.12 is required. Python 3.14 is intentionally not supported because a
compatible, reproducible PyTorch CPU wheel set is not pinned for it.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The default checkpoint location is the sibling extracted canonical package:
`../KNEE_AI_COMPLETE_BACKEND_PACKAGE/01_MODEL_DEPLOYMENT/best_5slice_model.pth`.
When that package is not present, the adapter uses the integrated checkpoint at
`../backend 2/ai/best_5slice_model.pth`. Both locations are verified against
SHA-256 `ac59d8ce17a0b35c15189d691f7c6aa828f31a3dfe14601a02036a6c3b892a82`
before inference. Override the location with `KNEE_AI_CHECKPOINT_PATH`.

Configure the MRI dataset (not included in the supplied package):

```powershell
$env:KNEE_AI_STUDY_ROOT = 'D:\knee-mri\train_images'
$env:KNEE_AI_SERIES_METADATA_PATH = 'D:\knee-mri\train_series.csv'
```

For local DICOM uploads, configure the server-side storage root before starting
the backend. The radiologist frontend upload control sends real multipart DICOM
files to `POST /studies/upload`; the backend reads their StudyInstanceUID,
SeriesInstanceUID, and SOPInstanceUID, stores them under the configured root,
creates a per-study metadata CSV, and registers the existing `Study` row.

```powershell
$env:KNEE_AI_STUDY_ROOT = 'E:\knee-ai-data\uploaded_mri'
$env:KNEE_AI_FRONTEND_ORIGINS = 'http://127.0.0.1:5500,http://localhost:5500'
```

The upload control accepts either individual `.dcm`/`.dicom` files or a ZIP
containing DICOM slices (non-DICOM files inside the ZIP are ignored). All
uploaded DICOMs must belong to one StudyInstanceUID. A study with no
eligible fluid-sensitive/fat-suppressed series remains unavailable for frozen
inference; the API reports that real configuration or series error.

Create/insert a `studies` row for each `study_id`. Per-study `study_root` and
`series_metadata_path` values override the environment defaults. The study root
must contain a directory named after every `SeriesInstanceUID`.

For the bundled SQLite database, a minimal registration command is:

```powershell
python -c "import sqlite3; sqlite3.connect('knee_ai.db').execute(\"INSERT INTO studies (study_id) VALUES ('<StudyInstanceUID>')\").connection.commit()"
```

```powershell
uvicorn app.main:app --app-dir . --reload
pytest -q
```

Create an authenticated user explicitly in the existing database before using
the frontend. Credentials are never seeded automatically:

```powershell
python scripts\create_user.py clinician@example.com '<password>' RADIOLOGIST
```

The frontend signs in through `POST /login` and sends the returned bearer token
to protected study, AI, review, report, orthopedic, and patient endpoints.

`POST /api/v1/ai/analyze` accepts only:

```json
{"study_id":"<StudyInstanceUID>","action":"ANALYZE_KNEE_MRI"}
```

It returns and persists all 12 probabilities in the frozen order. It does not
apply thresholds or produce diagnoses.

## Real 10-study demo smoke test

When the supplied demo package is available, register its real study IDs once
in the local `studies` table, then run one endpoint-based inference. The
reference CSV is read only after inference to compare evidence; it is never an
inference input. The configured DICOM root may contain either series folders
directly or the demo layout `<DICOM>/<StudyInstanceUID>/<SeriesInstanceUID>`;
the adapter resolves the latter to the frozen module's expected series root.

```powershell
$demo = 'C:\Users\praka\Downloads\KNEE_AI_10_REAL_DEMO_INPUTS'
$env:KNEE_AI_STUDY_ROOT = "$demo\DICOM"
$env:KNEE_AI_SERIES_METADATA_PATH = "$demo\ELIGIBLE_SERIES_MANIFEST.csv"
python scripts\run_demo_smoke.py --demo-root $demo --study-id '<StudyInstanceUID>'
```

## Member 2 report integration

Install `requirements.txt`, including `google-genai`, into the backend environment.
Set `GEMINI_API_KEY` in the server process environment. `.env.example` is a
configuration example; the backend does not automatically load it. Member 2
is loaded from the sibling `member2_llm` directory by default, independent of
the server working directory. Keep `backend 1/` and the original `member2_llm/`
from `mem2.zip` together under the project root. `KNEE_AI_MEMBER2_PATH` overrides
that default and supports `~`; relative overrides resolve from the server working
directory. Set the override before startup and restart after changing it.
A missing package produces a controlled integration error with the expected path.
The original Member 2 sources, prompts, validators, and tests are preserved.

Integration verification: 78 focused tests pass with Python 3.12, including
the original Gemini service functions with a mocked SDK client, authenticated
API persistence, safety rejection, and complete-review gating. No live Gemini
request was made. See `../MEMBER2_INTEGRATION_VERIFICATION.md` for commands and
remaining verification limits.
The dependency remains unpinned because no installed/tested SDK version is
available to justify a reproducible pin. Install and validate the real SDK before
live deployment, then pin the version actually validated. Missing SDK imports
produce a controlled integration error (HTTP 503, no report persistence).

The radiologist-only report endpoint calls the adapter once. The adapter maps
CONFIRMED and safely mapped EDITED findings to APPROVED. PENDING/unreviewed
findings are excluded. Rejected findings never enter approved input. Ambiguous,
unknown, missing, invalid, or duplicate canonical prediction mappings fail.
Probabilities are the exact stored Prediction.confidence floats, with no
threshold, rounding, or fallback. Radiologist review remains authoritative.
Edited finding text, outcome, and details are preserved in the existing authorized
clinical_context alongside reviewer notes; no Member 2 finding fields are added.
The backend retains the original review and finding rows unchanged.

Production requires the key and invokes Member 2's real generate_llm_report.
There is no offline report generator. The adapter invokes that provider once;
Member 2 internally retries transient 503 responses up to three attempts.
Missing key/dependency, mapping, provider, schema, or safety failures return HTTP
503 before any Report is added. Tests explicitly inject deterministic providers.
The actual response passes Member 2 schema and safety validation before storage.
For safety validation only, canonical abnormalities outside the authorized set
are denied using Member 2's existing REJECTED checks, without fabricated scores
or sending those entries to the provider. Backend workflow state is DRAFT/PENDING.

Frozen-validator limitation: Member 2 uses textual aliases and a finite treatment
phrase list, not comprehensive semantic validation. It cannot guarantee detection
of arbitrary noncanonical hallucinations, paraphrased treatment advice, or every
malformed finding element. These validators remain unchanged; no claim of complete
clinical safety is made. Authorized free-text context must contain only information
intended for the provider; this adapter does not implement general PHI redaction.
