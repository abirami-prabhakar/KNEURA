# Finals presentation runbook

## What is and is not ready

The existing KNEE-AI checkpoint is used for knee analysis and class-specific Grad-CAM.
It is not a language model and cannot supply source MRI. The provided handoff ZIP
contains overlays/provenance, not DICOM. No language-model endpoint or authorized
clinical MRI has been configured by this work. Until those are provided, do not
claim that the full real-MRI/live-LLM acceptance flow is complete.

Synthetic test data remains explicitly labeled and separate from clinical input.
The template report is an explicit fallback, never an automatic substitute for failed LLM generation.

## Configure the presentation shell

Export settings in the shell that starts the API. Python does not auto-load `.env`.
Keep credentials local and out of Git/browser code.

```powershell
$env:KNEURA_LLM_URL = 'http://127.0.0.1:1234/v1/chat/completions'
$env:KNEURA_LLM_MODEL = 'THE_ACTUAL_INSTALLED_LANGUAGE_MODEL'
$env:LLM_PROVIDER = 'your-approved-provider'
$env:LLM_TIMEOUT_SECONDS = '30'
$env:LLM_MAX_RETRIES = '2'
$env:KNEURA_REQUIRE_SERIES_CSV = '1'
$env:KNEURA_SERIES_CSV = 'data/series_eligibility.csv'
$env:KNEURA_DEMO_MRI_DIR = 'demo_data/knee_mri'
$env:KNEURA_DEMO_AUTHORIZATION = '.kneura/demo-authorization.json'
```

The URL is an example, not an installed service. Configure `KNEURA_LLM_KEY` securely
if the approved endpoint requires a bearer token. `LLM_URL`, `LLM_MODEL` and
`LLM_API_KEY` aliases are also supported; `KNEURA_*` values take precedence.
The endpoint must support chat-completions JSON output. Health probes invoke the
configured model with a tiny non-patient JSON request; provider charges may apply.
Never put authentication in URL query parameters or URL user information.

## Prepare authorized MRI and eligibility

1. Obtain authorization and complete the responsible institution's de-identification
   process, including human review for burned-in identifying pixels.
2. Put the approved `.dcm` files in `demo_data/knee_mri/` (ignored by Git).
3. Populate `data/series_eligibility.csv` with actual StudyInstanceUID and SeriesInstanceUID
   values, plus `Fluid_Sensitive` and `Fat_Suppression` as 0/1. In required mode every
   uploaded series must be classified. The shipped header-only file selects nothing.
4. Create a local authorization manifest containing `authorized`, `deidentified`, and
   `pixel_reviewed` confirmations and `files` mapping relative filenames to SHA-256.
   These confirmations must come from the responsible reviewer, not from this utility.
5. Run `npm run demo:verify -- --authorization .kneura/demo-authorization.json`.

The verifier checks readability, identity-removal flags, selected identifying tags,
private tags, dimensions, instance ordering, decoding and exact ingestion/selection.
It rejects synthetic input as a clinical demonstration. Metadata flags and file hashes
do not independently prove legal authorization or complete de-identification.
The utility does not remove identifiers or alter files.

At ingestion an uploaded CSV takes precedence over the configured CSV. Required
mode never silently uses description heuristics. Outside required mode the existing
fallback remains explicitly labeled. Selected series persist their CSV hash, UIDs,
description, image count and five-slice provenance.

## Start and check

Provision real local demo accounts using `python -m backend.manage create-user`
and the README role instructions. No last-minute SQL editing is needed.

```powershell
npm run demo:start
npm run preflight
```

The launcher builds the frontend and starts one localhost API and one static Vite
preview process in hidden windows. Worker execution is built into the API; there is
no separate broker. Process IDs and logs are recorded in `.kneura/presentation-logs`.
It refuses to reuse occupied ports, does not kill unrelated processes, and does not
claim readiness merely because processes started.

Preflight loads/executes the supplied checkpoint and verifies database integrity,
API availability, in-process worker initialization, LLM response, clinical demo
verification and required-CSV configuration. It exits nonzero if finals prerequisites
are missing. The authenticated `/api/system/readiness?execute_model=true` provides
the same checks inside the running API. File-metadata-only checks are explicitly
distinguished from executed model checks.

Open `http://127.0.0.1:5173/login` for a local demonstration. Local loopback HTTP is not
a deployed HTTPS service. For an actual network deployment use the provided
`deploy/Caddyfile.example`, a real domain, `KNEURA_SECURE_COOKIE=1` and exact HTTPS
origins in `KNEURA_ORIGINS`. Caddy/DNS/certificates must be configured and verified
on that deployment; the example alone does not implement TLS.

## Rehearse the workflow

1. Upload the authorized study, inspect its explicit series selection and start real inference.
2. Inspect all 12 findings and actual evidence. Native-resolution images support
   window/level, zoom/pan/reset and slice/window navigation. CAM opacity uses the
   actual saved class activation map on the first slice of its model input window.
   Older analyses without the raw map retain their legacy saved overlay.
3. Approve/reject all 12 findings. AI probabilities are not diagnoses.
4. Open the report workspace, check the LLM connection, enter only permitted
   de-identified indication/context, and select **Generate LLM narrative draft**.
5. Observe QUEUED/PROCESSING then the actual generated draft. The job ID, provider,
   model and approved source IDs persist. Provider latency does not hold the case lock.
6. Review and save the narrative. Structured validation checks IDs, sections,
   prohibited class mentions and numeric/severity claims; it cannot prove arbitrary
   prose medically correct. Human review remains mandatory.
7. For newly authored text, open its trace and use **Attach Evidence**, select the
   approved finding/evidence, and save. This creates an explicitly attributed revision.
   Changing linked text removes automatic carryover; unchanged text preserves links.
8. Finalize as a radiologist. Final reports and finding decisions cannot be edited.
9. Open Audit history and **Verify audit chain**. Hash consistency is tamper evidence,
   not protection from administrators who can rewrite the database and recompute hashes.
10. Assign the final case with `backend.manage assign`, then sign in as the orthopedist
    and matching patient. Confirm final-only information and role-filtered evidence.

## New API contracts

| Method / path | Behavior |
| --- | --- |
| `GET /api/system/llm/health` (also `/api/v1/system/llm/health`) | Radiologist-only configuration/model-response check; never returns credentials. |
| `POST /api/cases/{id}/report-jobs` | Radiologist-only; exact approvedFindingIds, optional reviewed clinical_context, optional requestId. Returns 202 with job_id/status. |
| `GET /api/cases/{id}/report-jobs/{job_id}` | Persisted job state and approved-only input for the radiologist. |
| `POST /api/cases/{id}/report` | Existing explicitly selected template fallback. Never invokes or impersonates an LLM. |
| `POST /api/cases/{id}/report/statements/{statement_id}/evidence` | Explicit attachment with findingId, evidenceId and current report version; rejects stale/final/unapproved references. |
| `GET /api/cases/{id}/source-images/{image_id}` | Native-resolution PNG; width/center/finding/opacity query parameters; same image and role authorization. |
| `GET /api/v1/audit/{case_id}/verify` | Radiologist-only hash-chain verification, failures and legacy-prefix count. |
| `GET /api/system/readiness` | Authenticated presentation checks; optional execute_model=true. |
| `POST /api/integration/cases` | Hospital Integration Adapter Demo alias of authorized DICOM upload. |
| `GET /api/integration/cases/{id}/result` | Final-only adapter result, approved findings only; no live hospital transport. |

Narrative output is JSON with `report_type: DRAFT`, Findings/Impression prose,
`source_finding_ids` and exact section statement texts with approved IDs. The old
LLM ordering-only implementation has been removed. Templates remain explicitly separate.

## Recovery and backup

- Failed LLM jobs preserve decisions, show FAILED, and permit a new retry. Only
  transient network/provider errors receive bounded automatic retries. Invalid
  clinical structure fails without a substituted report.
- Active jobs lock finding decisions. Repeated requests with the same requestId
  return the same job; differing payloads with that key are rejected. A completed
  case cannot acquire a duplicate report.
- Interrupted inference/report jobs become retryable failure states at restart.
  Browser refresh reloads persisted cases/jobs, not temporary frontend state.
- Stop the recorded API/UI processes before backup so file assets and the database
  snapshot correspond. Keep backups on restricted storage; they are not encrypted
  by this utility and may contain sensitive clinical records and password hashes.

```powershell
python -m backend.recovery backup --source .kneura --output backups/finals.zip --server-stopped
python -m backend.recovery restore --archive backups/finals.zip --destination .kneura-restored
```

Restore requires a new destination, validates file hashes/SQLite/audit chains, and
revokes old sessions. It never overwrites existing clinical storage. Point
`KNEURA_DATA_DIR` at the verified restored directory, retain the original model files,
restore environment secrets independently, and rerun preflight. Never treat a hash
manifest from an untrusted party as proof of authenticity.

Freeze the tested build and checkpoint after the real clinical/LLM rehearsal.
SSO/MFA, enterprise tenancy, live PACS/RIS/EHR, full PACS tooling, external clinical
validation and independent security testing remain later work.
