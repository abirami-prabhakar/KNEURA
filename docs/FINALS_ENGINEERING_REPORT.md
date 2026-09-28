# KNEURA finals engineering report

Verification date: 2026-09-24. The supplied implementation plan was treated as supporting reference for the user's existing implementation request. The existing application and frozen knee inference pipeline were retained.

## 1. Audit findings

The prior application had a working review workflow, but its optional LLM path only ordered template statements. Viewer previews did not provide native-resolution window/level controls. Report generation lacked persisted job state, manual report prose lacked explicit evidence attachment, and audit events lacked a verifiable chain. Real clinical DICOM and an actual narrative LLM endpoint were absent from the supplied files/environment. See [gap matrix](FINALS_GAP_MATRIX.md).

## 2. Root causes

Template composition had been presented as the report-generation integration, display assets were coupled to model-sized previews, and synchronous aggregate updates were unsuitable for slow external calls. The model handoff contains knee classifier weights, overlays and provenance; those assets cannot substitute for original MRI or a language model.

## 3. Implementation

Added an explicit chat-completions-compatible narrative adapter with approved-only input, strict structured output and failure reporting. Added persisted background report jobs, decision fingerprints, bounded provider retries and restart recovery. Provider calls run outside the workflow lock. Template generation remains a separately labeled user action, with no automatic substitution.

Added source-resolution MRI rendering, window/level and heatmap opacity controls, class-specific saved attention maps, CSV provenance/required mode, a controlled MRI verification utility, versioned manual evidence links, chained audit verification, login throttling, backup/restore, startup and readiness tooling. Existing final-approval and role-distribution gates remain enforced.

## 4. Files changed

| Area | Main files |
| --- | --- |
| Narrative and jobs | `backend/narrative.py`, `backend/report_jobs.py`, `backend/reporting.py`, `backend/app.py` |
| MRI display and ingestion | `backend/viewer.py`, `backend/ingestion.py`, `backend/inference.py` |
| Integrity and operations | `backend/audit.py`, `backend/recovery.py`, `backend/readiness.py`, `backend/demo_validation.py` |
| Frontend | `src/App.tsx`, `src/finals-panels.tsx`, `src/api.ts`, `src/types.ts`, `src/theme.css` |
| Configuration and scripts | `.env.example`, `.gitignore`, `package.json`, `scripts/preflight.py`, `scripts/verify_dicom_study.py`, `scripts/start-finals.ps1`, `deploy/Caddyfile.example` |
| Demo input contract | `data/series_eligibility.csv`, `demo_data/knee_mri/README.md` |
| Verification and documentation | `tests/test_backend.py`, `tests/browser/clinical.spec.ts`, `tests/live/workflow.spec.ts`, `README.md`, `docs/FINALS_*.md` |

The frozen `knee_ai_inference.py` was not modified. Display operations are independent of its preprocessing and study probability aggregation.

## 5. API changes

Added LLM health, asynchronous report submission/status, native source-image rendering, explicit statement/evidence attachment, audit verification and system readiness endpoints. Added authenticated upload/result integration aliases. Request and response details are in the [runbook](FINALS_RUNBOOK.md). Reports remain drafts until a radiologist saves review and explicitly finalizes the current version.

## 6. Database changes

SQLite retains the existing case JSON aggregate design. Case documents now persist report-job state/history, request and decision fingerprints, explicit statement link metadata, and audit-chain metadata. Added `login_attempts` and its identity/time index. SQLite connections now close reliably on Windows. Backup uses SQLite's backup API and a checksummed study archive; restore requires a new destination, validates integrity and revokes restored sessions.

## 7. Frontend changes

The study workspace exposes all 12 finding decisions, probability/evidence, review progress and report review. Native MRI controls show source dimensions and allow window/level and heatmap opacity changes. Report UI displays persisted generation progress, failures and retry. Trace review allows radiologist-authored statements to be explicitly linked to approved evidence. Audit UI verifies the chain. Orthopedist and patient access remains limited to finalized approved content.

## 8. Tests added or expanded

Coverage includes five-approved/seven-rejected narrative payloads; invalid, invented and incorrectly traced narrative output; slow-provider lock isolation; missing-provider failure; interrupted-job recovery; native dimensions/windowing and authorization; versioned manual attachments; audit mutation/reorder/truncation; throttled login; backup/restore; mandatory CSV provenance; and refusal to label missing or synthetic MRI as clinical input. Browser coverage includes persisted narrative failure/retry and the existing desktop/mobile workflow. The live workflow now exercises viewer controls, explicit evidence attachment and audit verification.

## 9. Test results

All 68 automated tests passed: 25 backend tests (71.64 seconds), six workflow unit tests, 36 desktop/mobile browser tests (1.4 minutes), and one real-backend browser workflow (50.7 seconds including startup). Production build and lint passed. Backend tests emitted one Starlette/httpx deprecation warning. An initial Windows backup cleanup failure was corrected by closing SQLite handles; the final backend run passed. A sandbox-only Vite subprocess error was resolved by rerunning the build with approved execution permissions.

The frozen inference file's SHA-256 remains `4A86A64ABA740089F03C2A169C89D8F612731BD43E45591963532E191D27A677`.

## 10. LLM verification result

**Live-provider verification is blocked.** No LLM endpoint/model is configured. Contract tests use an explicit HTTP response double and prove approved-only serialization, schema validation, trace validation and job behavior; they do not prove a real model's narrative quality. The adapter performs an actual small generation request for health when configured. No template output is reported as LLM output. Schema and lexical checks cannot establish the medical correctness of arbitrary prose; radiologist review remains necessary.

## 11. MRI verification result

**Authorized clinical-MRI verification is blocked.** The supplied handoff ZIP has no DICOM study. The knee checkpoint executed successfully and produced 12 finite outputs. Synthetic DICOM validates ingestion, windowing, model execution and Grad-CAM plumbing only. The verifier checks metadata, file-bound authorization attestation, operator pixel-review attestation and series eligibility; it does not independently prove authorization or absence of burned-in identifiers.

## 12. End-to-end demo result

The browser-to-real-API workflow passed: synthetic DICOM upload, supplied checkpoint inference, finding decisions, explicit template draft, radiologist edits/evidence links, final approval and role-specific distribution. It used no API request mocks. The complete authorized-MRI plus live-LLM demonstration has not passed because those inputs are unavailable.

Preflight executed against an isolated temporary data directory: database and actual model checks passed; LLM configured/reachable was false; DICOM count was zero; required CSV mode was false. No presentation API was running, so backend/worker checks were false. It correctly returned `finals_ready: false` and exit code 1. Startup and deployment examples are provided, not claimed as a deployed HTTPS service.

## 13. Remaining limitations and finals impact

| Unresolved item | Why | Impact |
| --- | --- | --- |
| Live narrative model | Endpoint/model not supplied | Blocks actual LLM acceptance and full finals flow |
| Authorized de-identified MRI | Source study and attestations not supplied | Blocks real-study acceptance and full finals flow |
| Presentation configuration | Required CSV mode, actual study CSV, API startup and environment configuration still needed | Blocks readiness on the presentation machine |
| HTTPS deployment | Only a configurable reverse-proxy example exists | Must configure and verify if presenting beyond localhost |
| Job execution | In-process FastAPI worker; persisted interrupted jobs fail safely for retry | Suitable for one local API process, not a distributed durable queue |
| Idempotency scope | Key deduplication covers the current/latest report job | Not a permanent global request-key registry across all historical retries |
| Audit integrity | Hash chain and stored head are locally verifiable | A privileged attacker able to rewrite all data can recompute the chain; no external immutable anchor |
| Model evidence | Window-level Grad-CAM, research checkpoint, no validated decision threshold | Does not establish lesion localization or clinical performance |

## 14. Future production requirements

Production work remains separate: managed identity/SSO/MFA, tenant isolation, durable external job queues, managed secrets and rotation, validated clinical performance and intended-use review, hospital integration/PACS, externally anchored audit retention, monitoring/alerts, encrypted storage and operational key management, backup scheduling and disaster-recovery exercises, and load/security assessment. These are not claimed complete for the local finals MVP.

Use [FINALS_RUNBOOK.md](FINALS_RUNBOOK.md) for configuration, presentation steps, failure recovery and backup/restore commands.
