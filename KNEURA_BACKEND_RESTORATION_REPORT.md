# KNEURA backend restoration report

Date: 2026-09-24

## 1. app.py restored

**YES — runtime restored using a controlled bytecode bridge.** The original source was not found. `backend/app.py` is a minimal loader that executes the protected compiled KNEURA backend. No route logic was invented or copied from another application.

## 2. Backup

Backup created before restoration:

`.kneura/recovery-backup-20260924-213508/`

The original `.pyc`, frontend, configuration and existing backend directory were preserved there.

## 3. Restoration method

The source-missing sibling modules load their matching Python 3.14 cache files through `_pyc_loader.py`. The app loads a separate preserved copy at `.kneura/recovery/app-original.cpython-314.pyc`; the original cache file is untouched. `PYTHONDONTWRITEBYTECODE=1` is required when running this bridge.

## 4. Routes restored

All 26 routes recovered from bytecode are available, including authentication, health, cases, integration upload/result, analysis, decisions, report generation/edit/finalize, images, model, validation, export, LLM health, report jobs, audit verification, statement evidence, source images and readiness.

## 5. Sibling modules

Compiled sibling modules were available for `auth`, `audit`, `demo`, `demo_validation`, `inference`, `ingestion`, `narrative`, `readiness`, `recovery`, `relationships`, `reporting`, and `report_jobs`. Minimal loaders were added. `viewer.py` was already present. The exact original source remains unavailable.

## 6. Backend startup

**PASS.** `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000` started successfully with `PYTHONDONTWRITEBYTECODE=1`. The app reports `KNEURA` and 30 registered FastAPI routes (including duplicate aliases).

## 7. Health and metadata

**PASS:** `GET /api/health` returned HTTP 200 with `worker_ready: true`.

**PASS:** authenticated `GET /api/model` returned KNEE-AI 3.3, 12 outputs and the existing checkpoint metadata.

**BLOCKED:** authenticated `GET /api/validation` returned HTTP 500 because `02_PERFORMANCE/KNEE_AI_3_3_PERFORMANCE_EVIDENCE.json` is absent from the restored project. This is a missing validation artifact, not a model failure.

## 8. AI inference and Grad-CAM

**PASS:** the supplied 40-slice MRI uploaded as `KN-3CF3E659177D`, and analysis completed with `AI_READY` and 12 findings. The frozen checkpoint and inference module were not changed. The checkpoint reported by the backend remains SHA-256 `66504783a2ad62d852767db58aa8fde802d6bd71171cd9836d8cdfba66e21611`.

The earlier supplied-study verification established 36 windows, unchanged probabilities through Grad-CAM, and all 12 evidence links. No AI or Grad-CAM implementation was changed during restoration.

## 9. Evidence and audit

**PASS:** audit verification for `KN-3CF3E659177D` returned `valid: true` with five events. Source-image and evidence routes are present in the restored route set.

## 10. Finding approval gate

**Not fully rerun after restoration.** The bytecode route and imported `reporting.approved_findings` are present. A complete 12-decision report workflow must be rerun after frontend/API configuration is restored.

## 11. LLM

**BLOCKED:** `/api/system/llm/health` returned HTTP 200 with `configured: false` and requires `KNEURA_LLM_URL` and `KNEURA_LLM_MODEL` under the compiled adapter. No provider or credentials were invented. The supplied `mem2.zip` Gemini service remains a separate integration package and is not silently substituted.

## 12. Report/finalization

**BLOCKED:** live report generation was not claimed because no LLM is configured. Export correctly returned HTTP 409 for the unfinalized case, showing finalization gating remains active.

## 13. Readiness

**PASS:** `/api/system/readiness` responded. It correctly reports the database and worker, while readiness remains false until required model execution/demo/LLM conditions are satisfied.

## 14. Frontend compatibility

**PARTIAL:** the recovered backend route set covers the frontend's expected core endpoints. The current `src/api.ts` is an older/minimal client and does not expose the newer report-job, audit-verify, statement-evidence or source-image methods; this is an existing frontend/API version mismatch and was not silently changed during restoration.

## 15. AI integrity

**PASS:** frozen `knee_ai_inference.py` SHA-256 is `4A86A64ABA740089F03C2A169C89D8F612731BD43E45591963532E191D27A677`. The original app `.pyc` SHA-256 is `46C195B612016C3D6136D12113E6780AA29EC327E91425B446207D9229CD94CD`. No checkpoint, preprocessing, inference, Grad-CAM, canonical class order or AI contract was modified.

## 16. Remaining blockers

1. Original backend source remains unavailable; current restoration executes protected bytecode through reviewed loaders.
2. Validation evidence JSON is missing, causing `/api/validation` to return 500.
3. LLM endpoint/model is not configured, so live narrative report generation is unavailable.
4. Frontend API client must be aligned with the restored finals endpoints before claiming the complete frontend workflow.
