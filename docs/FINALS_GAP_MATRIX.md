# Finals stabilization gap matrix

Baseline inspected: React/Vite frontend; FastAPI; SQLite case aggregates; local cookie
identity provider; unchanged `knee_ai_inference.py`; ingestion/inference/reporting/audit
modules; existing FastAPI background analysis tasks; unit/API/mock-browser/live-browser tests.

The newly supplied handoff ZIP is byte-identical to the existing supplied files and
contains no source DICOM or language model. The implementation plan is additional
reference context; the user's finals request controls scope. Model tensors and both
frozen inference modules remain unchanged.

| Finding | Baseline location/state | Finals implementation | Verification |
| --- | --- | --- | --- |
| LLM | `backend/reporting.py`: template or statement ordering | Dedicated narrative schema/prompt/provider, health, no silent fallback, 5-approved/7-rejected gate | Provider contract, malformed responses, no-config failure, live test only when endpoint supplied |
| Clinical MRI | Supplied handoff has overlays only | Controlled demo directory, hash-bound authorization/pixel-review attestation, DICOM verifier | Metadata/selection checks; clinical run blocked without authorized DICOM |
| Viewer | `src/App.tsx`: normalized preview | Separate native-resolution rendering, width/level/reset and adjustable class CAM | Pixel dimensions, window changes, access controls, browser controls |
| Selection | `backend/ingestion.py`: uploaded CSV or labeled heuristic | Required-CSV mode, configured CSV, explicit coverage and SHA-256 provenance | Deterministic windows, missing/inconsistent CSV rejection |
| Validation | Supplied internal metrics | Preserve precise values and pending-reproduction label | No new accuracy claim; source dataset unavailable |
| Authentication | Local cookie/RBAC abstraction | Retain RBAC and add temporary failed-login throttling | Expiry, role controls, repeated-failure test |
| Deployment | Local API/UI | Build/start procedure, offline verified backup/restore, HTTPS proxy example | Round-trip restore and readiness; no deployed TLS claim |
| Integration | Final-only JSON export | Labeled import/result aliases using same authorization and upload service | Scoped final-only result tests |
| Provider blocking | Synchronous generation under global lock | Persistent background jobs; network outside lock; idempotency/restart recovery | Slow-provider concurrency, failed/retry/duplicate job tests |
| Audit | Append-oriented events, no hashes | Chained hashes, legacy-prefix anchor, stored head and verification UI/API | Mutation/reorder/truncation tests; no tamper-proof claim |
| Edited provenance | Authored text has editor/version only | Explicit approved finding/evidence attachment, versioned and audited | Rejected/stale/final attachment denial; persistence on unchanged prose |

Production-only scope remains SSO/MFA, enterprise tenancy, real PACS/RIS/EHR transport,
full PACS functionality, external clinical validation and independent security testing.
