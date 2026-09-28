# KNEURA Technova Finals implementation audit

Date: 2026-09-24. Scope: the supplied 37-section implementation request.

**Delivery status:** the real-backend software workflow is demonstrable using synthetic DICOM and the supplied checkpoint. The final report provider used in the live walkthrough is the explicitly labeled evidence-bound template. An actual LLM service and clinical DICOM/evaluation dataset were not supplied; neither LLM execution nor clinical validation is claimed.

## 1. Features already existed

- React/Vite/TypeScript frontend with role navigation, case queue, search/filter/sort, MRI slices and overlapping windows, class selection, Grad-CAM, finding decisions, report editing, statement traces, audit timeline, model/validation pages and final role-specific views.
- FastAPI backend with local cookie authentication, radiologist authorization, patient-ID matching, orthopedist grants, SQLite persistence and protected image endpoints.
- DICOM/ZIP ingestion, CSV series eligibility, conservative explicitly labeled metadata fallback, InstanceNumber ordering and original preprocessing.
- Strict loading of the supplied learned 5-to-3 projection/EfficientNet-B0 checkpoint, all-window mean probabilities, canonical display aliases and 12 class-specific Grad-CAM overlays.
- All-12 review gate, server-derived approved-only report inputs, template provider, optional constrained LLM ordering adapter, immutable final reports and report revision storage.
- Supplied golden-case/Grad-CAM reference remains an explicitly simulated, read-only handoff. It is never seeded into the clinical worklist.

## 2. Features fixed

- Empty eligibility CSV no longer silently enables heuristic selection. A supplied CSV is authoritative even when it contains no eligible records.
- Missing/blank patient identity and empty study/series/image UIDs are rejected instead of creating unassignable studies.
- Failed/interrupted inference persists `ERROR`, with an error filter and explicit retry action. It never publishes fake findings.
- Decision changes now preserve previous/current state, case/finding IDs, actor identity and timestamps.
- The backend requires decision provenance for all 12 findings, not merely approved/rejected status strings.
- Finalization requires a saved report review and non-placeholder impression; invalid review gates return meaningful HTTP errors.
- Original and edited report versions preserve author/editor identity. Existing historical records remain unchanged.
- Integration exports contain approved findings only and exclude draft revisions even for radiologists.
- Anonymous/denied requests are logged; signing in rotates the existing browser session; unsupported roles fail closed. Expired clinical requests clear the frontend and return to login.
- Validation API values now come from the supplied performance/model-lock JSON, rather than duplicated rounded constants.
- Inference rejects malformed/non-finite probabilities and non-finite Grad-CAM before findings are published.

## 3. Features newly implemented

- Replaceable identity-provider protocol and local implementation in `backend/auth.py`.
- Structured case audit service in `backend/audit.py`.
- Case-aggregate relationship validator in `backend/relationships.py`.
- Analysis/evidence IDs, inference timestamps and evidence model references; case creation timestamp and DICOM patient demographic mapping.
- `UNDER_REVIEW` report status, saved-review identity/time and radiologist-visible version history.
- Direct evidence-card jump to the associated MRI location, creation/report columns, explicit demo notice, error styles and future-validation section.
- Synthetic DICOM generator with no seeded probabilities, decisions or reports. Files are marked DEMO and existing packages are not overwritten.
- An isolated real-backend Playwright test covering upload through final patient distribution without intercepted API responses or mocked inference.

## 4. Features partially implemented

| Feature | Implemented portion | Exact remaining limitation |
| --- | --- | --- |
| LLM draft | Optional chat-completions adapter receives approved IDs/names only, validates returned IDs and creates evidence-bound statements. Successful and malicious provider responses are tested. | No actual LLM URL/model was configured for this verification. The provider deliberately orders allowed statements; it does not generate unrestricted narrative prose. The demonstrated fallback is a template, not an LLM. |
| MRI viewer | Real backend-rendered slices, windows, zoom/pan, evidence jump, Grad-CAM and image error states. | Displays frozen-pipeline normalized 224x224 previews. No full diagnostic PACS viewer, diagnostic window/level tooling or multi-frame support is claimed. |
| Hospital integration | Authenticated final-only JSON adapter with explicit demonstration label. | No DICOMweb/C-STORE, HL7/FHIR transport, PACS/RIS/EHR deployment or vendor certification. |
| Authentication/security | Replaceable local provider, salted password hashes, expiring HttpOnly/SameSite cookies, origin checks, RBAC and access logs. | No deployed SSO, MFA, centralized revocation, login rate limiting, multi-hospital tenancy or independent security assessment. |
| Data protection | Configurable storage directory, no-store responses, secure-cookie option and documented same-origin HTTPS deployment. | Application-managed encryption at rest and an actual TLS/reverse-proxy deployment are not included. Storage encryption requires deployment infrastructure/key management. |
| Validation | Documented 9 studies, 844 windows, 27 series and exact supplied macro AUROC displayed with limitations. | No original evaluation dataset was supplied; the clinical metrics were not independently reproduced. |
| Traceability after prose edits | Unchanged approved statements retain finding links. New text records radiologist-authored provenance and version/sign-off. | Arbitrary new clinical prose is not automatically assigned an AI evidence link. This prevents fabricated attribution. |

## 5. Features still blocked

- **Actual LLM-service demonstration:** requires an approved reachable endpoint, model identifier and any locally configured credentials. None were supplied during this audit. No data was sent to an unapproved external service.
- **Anatomical MRI/clinical demonstration and evaluation:** requires an authorized, appropriately de-identified clinical DICOM sample and the original evaluation data. The repository contains overlays/provenance, but not the original clinical DICOM dataset. Synthetic noise cannot establish diagnostic quality.
- **Deployed hospital interoperability, SSO and encryption verification:** requires hospital endpoints, identity-provider configuration and deployment infrastructure. Adapter boundaries and configuration are present; external integration is not claimed.

These do not prevent running the local synthetic software demonstration with the labeled template provider.

## 6. Files changed in this audit

Existing files modified:

- `backend/app.py`, `backend/ingestion.py`, `backend/inference.py`, `backend/reporting.py`
- `src/App.tsx`, `src/api.ts`, `src/types.ts`, `src/clinical.tsx`, `src/case-milestones.tsx`, `src/theme.css`
- `tests/test_backend.py`, `tests/browser/clinical.spec.ts`
- `package.json`, `vite.config.ts`, `.env.example`, `README.md`

New files:

- `backend/auth.py`, `backend/audit.py`, `backend/relationships.py`, `backend/demo.py`
- `tests/live_server.py`, `tests/live/workflow.spec.ts`, `playwright.live.config.ts`
- `docs/TECHNOVA_IMPLEMENTATION_AUDIT.md`

The workspace already contained many uncommitted changes at task start. This list identifies this audit's edits rather than claiming ownership of the entire Git diff. No changes were made to either supplied inference module or model tensors.

## 7. Database/model changes

SQLite remains the persistence store. Users, sessions, grants and access logs are rows; patient/study/series/images/analysis/findings/evidence/decisions/reports/revisions/audit are stored together in an atomic case document. This reuses the existing implementation rather than performing a disruptive normalization rewrite.

New JSON fields include `createdAt`, patient demographics, analysis/evidence IDs and timestamps, structured audit references, report author/editor IDs, `reviewedAt` and `reviewedById`. New status values are case `ERROR` and report `UNDER_REVIEW`. Relationship checks reject orphaned evidence and unapproved report links before writes.

No destructive migration is required. Older documents may lack new optional metadata. Older drafts need to be saved to record explicit review before finalization; the UI permits this even without text changes. Existing final reports remain final and immutable. Old audit events are not rewritten to invent missing identities.

The inference module SHA-256 remains `4A86A64ABA740089F03C2A169C89D8F612731BD43E45591963532E191D27A677`, matching the supplied handoff copy. Checkpoint reconstruction repackages unchanged tensors; its archive hash is distinguished from the original supplied archive hash.

## 8. API changes and contract audit

No existing frontend endpoint was renamed. Existing methods and payloads remain compatible; state/provenance fields are additive.

| Endpoint | Contract / authorization verified |
| --- | --- |
| `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` | Server-owned role, cookie session, expiry, rotation and logout. |
| `GET /api/cases`, `GET /api/cases/{id}` | Authenticated, assignment/patient scoped and role-filtered. |
| `POST /api/cases` | Radiologist-only multipart `files`, actual DICOM validation, persisted study/case/patient linkage. |
| `POST /api/cases/{id}/analysis` | Radiologist-only; RECEIVED/ERROR to PROCESSING; real asynchronous inference to AI_READY or ERROR. |
| `POST /api/cases/{id}/findings/{id}/decision` | Radiologist-only; APPROVED/REJECTED; previous/current audit; locked once a report exists. |
| `POST /api/cases/{id}/report` | All 12 recorded decisions required; exact server-approved input only; provider failure saves no draft. |
| `PATCH /api/cases/{id}/report` | Radiologist-only; persists prior version and editor; status UNDER_REVIEW. |
| `POST /api/cases/{id}/report/finalize` | Radiologist-only; all decisions, saved review and impression required; immutable FINAL. |
| `GET /api/cases/{id}/images/{filename}` | Scoped study images; approved Grad-CAM only for assigned orthopedist; patient denied. |
| `GET /api/cases/{id}/export` | Final-only approved findings; no draft revisions; explicitly labeled MVP adapter. |
| `GET /api/model`, `GET /api/validation` | Radiologist-only; checkpoint errors meaningful; supplied validation provenance. |
| `GET /api/health` | Public service availability, not a claim of model or provider readiness. |

The documented handoff endpoint `/api/v1/ai/analyze` is not a live endpoint in this app. The frontend consistently uses `/api/cases/{id}/analysis`; no false alias is advertised.

## 9. Frontend changes

The existing design and routes are preserved. Cases open actual API-backed study workspaces. All 12 classes, their probabilities and explicit decisions are shown; MRI/evidence navigation and final role distribution remain connected to server state. Added errors/retry, creation/report columns, direct evidence jumps, report version history, UNDER_REVIEW display, demo labeling and expiry handling improve the existing flow.

The browser uses same-origin `/api`, with optional `KNEURA_API_PROXY` for the Vite upstream. Report export now uses the configured API base. A reverse proxy must preserve same-origin image/cookie routing when deployed.

## 10. Tests run

```powershell
python -m pytest tests/test_backend.py -q -p no:cacheprovider --tb=short
npm run build
npm run lint
npm test
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:e2e
npm run test:live
```

Backend coverage includes the supplied checkpoint, unchanged frozen mean aggregation, canonical ordering, 12 actual CAM images, ingestion failures, empty-CSV selection, missing identity/checkpoint, orphan references, decision history, revisions, finalization, session expiry/rotation, access logs, role isolation and exact approved-only provider inputs.

The most important report test approves ACL, MCL and Medial Meniscus, rejects the remaining nine, and asserts that the provider receives exactly those three IDs/names. A malicious extra ID yields HTTP 502 and no report. A valid ordering produces a DRAFT. These provider tests use an explicit test double; they do not claim live LLM execution.

## 11. Test results

- Production TypeScript/Vite build: passed.
- Lint: passed.
- Workflow unit tests: 6 passed.
- Backend tests: 15 passed, including real checkpoint inference and comparison to the untouched supplied pipeline.
- Desktop/mobile browser tests: 34 passed.
- Live browser test: 1 passed (36.1 seconds total); uses real HTTP, sessions, SQLite, DICOM ingestion, checkpoint inference and Grad-CAM with synthetic input. All 56 automated checks passed.

Initial sandbox runs could not create pytest temporary files or launch Vite subprocesses; allowed external execution resolved those environment restrictions. Playwright's bundled Chromium was absent, so installed Microsoft Edge was used. One retry-button regression was found and fixed; its desktop/mobile checks now pass. A Starlette/httpx deprecation warning remains, with no failing backend checks.

## 12. End-to-end demo status

The real-browser walkthrough exercises login, upload, case detail, real inference, all 12 outputs, MRI/evidence/Grad-CAM navigation, 3 approvals and 9 rejections, approved-only template draft, editing, statement trace, final approval, audit, orthopedist assignment/sign-in and patient sign-in. It checks that rejected heatmaps and patient MRI access are denied.

The test provisions only a new `.kneura/live-test-<UUID>` database and randomly generated temporary credentials. It does not seed or mutate the user's existing clinical database. Screenshots are `test-results/live-real-inference.png` and `test-results/live-final-patient.png`.

**The exact requested flow with an actual LLM is not yet verified.** The local template flow is demonstrable; LLM-service execution remains dependent on external configuration.

## 13. Known limitations

- Synthetic DICOM verifies software behavior, not anatomical image quality, clinical accuracy, calibration or patient outcomes.
- Series metadata fallback is a heuristic; supplied eligibility CSV remains the reproducible selection method.
- Grad-CAM is class-specific five-slice model attention overlaid on the first input slice, not lesion segmentation or proven slice-localized pathology.
- Single-process/single-worker backend, local SQLite and a process-local workflow lock are appropriate to this MVP, not multi-node deployment. Provider requests can hold the workflow lock until timeout.
- Clinical children use application-validated JSON aggregate relationships, not normalized foreign-key tables. Database/file administrators can still modify storage; audit is not tamper-proof.
- Local authentication and deployment options do not establish hospital-grade security, regulatory compliance, encrypted storage or real interoperability.
- Report prose authored by a radiologist is traceable to the editor/revision/sign-off, not automatically to an inferred MRI claim.
- Patient explanations describe the approved class without inventing severity, treatment or prognosis.

## 14. Exact next steps

1. Run the local demo with `npm run api` and `npm run dev`; provision the three users using `backend.manage` as documented in the README.
2. Use an authorized de-identified study, or run `npm run demo:dicom` and upload the clearly marked artificial demo ZIP. Start analysis and make explicit decisions for all 12 findings.
3. For the actual LLM path, set `KNEURA_LLM_URL`, `KNEURA_LLM_MODEL` and, if required, `KNEURA_LLM_KEY` in the API process environment. Restart the API and generate a report for a newly reviewed case. Verify the provider label is LLM-ordered and run an approved-input capture against that authorized service. Do not put keys in Git or browser code.
4. Save the radiologist impression and approve final. Assign the case to the orthopedist with `python -m backend.manage assign --email ... --case ...`. Match the patient account to the DICOM PatientID (`DEMO-SYNTHETIC` for generated demo input).
5. Before hospital use, configure SSO, TLS, encrypted storage, operational monitoring/backups, transport adapters and independent security/clinical validation. These are separate deployment and evaluation tasks.

## Final checklist mapping

| Checklist group | Result |
| --- | --- |
| Core AI | Real checkpoint, unchanged architecture/preprocessing, five slices, all 12 outputs and canonical order verified. |
| DICOM | Actual ingestion, series detection/selection, ordered windows and provenance verified; clinical dataset unavailable. |
| Evidence | Actual class-specific CAM, evidence objects, cards and MRI jumps verified. |
| Radiologist | Real worklist, persisted explicit decisions and all-12 gate verified. |
| Report | Approved-only input, template draft, edit/version/review/final gates verified; live LLM pending configuration. |
| Traceability | Approved statement to finding/probability/series/window/slices/CAM/decision verified; authored prose explicitly distinguished. |
| Audit | Receipt, analysis, findings, decisions, drafts, edits and finalization persisted with timestamps/actors and new structured references. |
| Roles | Radiologist, assigned orthopedist and matching patient access verified at API and UI layers. |
| Product | Case management, documented model/validation, demo export, loading/empty/error/retry states verified. |
| Security | Local identity abstraction, RBAC, protected routes, session handling and access logging verified; production hardening remains outside demonstrated scope. |
