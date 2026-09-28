# KNEURA

Evidence-governed knee MRI research MVP, using the supplied **KNEE-AI 3.3** model and the existing React paper-ticket UI. The FastAPI backend now implements DICOM ingestion, real inference, Grad-CAM evidence, radiologist review, draft/final reports, scoped clinical views and persistent audit history.

## Run locally

Python with PyTorch/torchvision support and Node.js 22.6+ are required. Use compatible torch/torchvision builds for your Python version.

```powershell
python -m pip install -r backend/requirements.txt
npm install
python -m backend.manage check-model
python -m backend.manage create-user --email radiologist@kneura.local --name "Demo Radiologist" --role radiologist
```

The account command securely prompts for a password of at least 12 characters. No default passwords or patient cases are seeded. Start the API and frontend in separate terminals:

```powershell
npm run api
```

```powershell
npm run dev
```

Open **http://localhost:5173/login** and sign in with your new account. Vite forwards `/api` to `127.0.0.1:8000`; no `.env` is required. API documentation is available at **http://127.0.0.1:8000/docs**. Bind the API to localhost and run a **single worker** for this MVP.

## Walk through the product

1. Sign in as a radiologist and upload one knee MR study as DICOM files or a ZIP, optionally with the series eligibility CSV below.
2. Start analysis. The server decodes images, orders InstanceNumbers, evaluates overlapping five-slice windows and creates 12 findings with actual class-specific Grad-CAM.
3. Open each finding, inspect the MRI/evidence window, and explicitly approve or reject all 12 outputs.
4. Generate a draft. The server independently checks all decisions and constructs input from approved findings only. Decisions then lock.
5. Review/edit the findings and **write the impression**, then save. The placeholder impression cannot be finalized.
6. Approve the final report. It becomes immutable and available to the matched patient and assigned orthopedists. Use **Integration JSON** to inspect the final-only adapter output.
7. Inspect statement trace links, audit events, deployed checkpoint information and the roadmap's reported internal validation metrics.

## Supplied model: preserved

`knee_ai_inference.py` remains unchanged. `Model/` contains an extracted PyTorch archive, including `data.pkl` and tensor storage files. The adapter reconstructs a `.pt` ZIP in `.kneura/checkpoints/` without changing tensors, loads the supplied architecture strictly, and records its SHA-256 with each analysis. Alternatively set `KNEURA_CHECKPOINT` to an original `.pt`/`.pth` checkpoint. Do not load untrusted checkpoints.

The pipeline retains the supplied MONOCHROME1 handling, 1st/99th percentile normalization, PIL bilinear resize to 224×224, learned 5→3 projection, EfficientNet-B0, sigmoid outputs and mean probability across all study windows. Output indices are unchanged; UI aliases are `PF OA` → `Patellofemoral OA` and `Baker's` → `Baker's cyst`.

For exact series eligibility, include a CSV alongside the DICOM files or inside the ZIP:

```csv
StudyInstanceUID,SeriesInstanceUID,Fluid_Sensitive,Fat_Suppression
1.2.3,1.2.3.1,1,1
1.2.3,1.2.3.2,0,0
```

With a CSV, only explicitly marked fluid-sensitive AND fat-suppressed series are eligible. Without a CSV, conservative matching of DICOM descriptions (T2/PD/STIR/TIRM and fat suppression terms) is used and explicitly identified as a heuristic. Confirm acquisition metadata before relying on this fallback. Series need at least five single-frame grayscale MR images. Multi-study packages, duplicate instances, unsupported frames and undecodable pixels are rejected. Compressed transfer syntaxes may require additional pydicom decoders.

Each finding's evidence uses its highest-scoring window, while the displayed probability remains the **study mean**. Grad-CAM uses the final convolutional features and the same five-slice input. It is a **window-level attribution**, shown over the first input slice, not a lesion segmentation or proof of slice-localized pathology. Actual InstanceNumbers are retained. Unsupported anatomical orientation markers are not fabricated.

## Reports and traceability

A separately selected **evidence-bound template** fallback remains available so the software workflow can be exercised without external service access. The report screen presents genuine LLM narrative generation as its primary option and clearly reports LLM unavailable when configuration is missing. It does not invent severity, location or diagnoses beyond approved class labels.

The genuine narrative provider is now separate from the explicit template fallback. Configure a chat-completions-compatible endpoint with `KNEURA_LLM_URL`, `KNEURA_LLM_MODEL` and optionally `KNEURA_LLM_KEY`. It generates Findings and Impression prose plus statement source IDs, validated before saving. Only approved finding IDs/names and explicitly entered permitted context are sent. Provider failure saves no draft and never silently substitutes a template. See [Finals runbook](docs/FINALS_RUNBOOK.md) for the background-job API and verification limits.

Generated statements link to their approved findings and imaging evidence. Exact unchanged statements retain their links after edits. New prose is marked **radiologist-authored**, with revision history and final sign-off as provenance; the application never invents AI evidence links for edited text. Final reports cannot be edited or re-analyzed.

## Roles and persistence

Accounts are provisioned locally; the login role selector cannot grant a different role. Cookie sessions expire after eight hours. Passwords use salted PBKDF2, and the server enforces permissions on every case, mutation, export and image request.

```powershell
python -m backend.manage create-user --email clinician@kneura.local --name "Demo Orthopedist" --role orthopedist
python -m backend.manage assign --email clinician@kneura.local --case KN-YOURCASEID
python -m backend.manage create-user --email patient@kneura.local --name "Patient" --role patient --patient-id EXACT_DICOM_PATIENT_ID
```

Patient accounts match the exact DICOM PatientID. Orthopedists need explicit case assignment. Both see only final reports and approved findings. Raw probabilities, rejected findings and draft revisions are removed from their API responses. Patients receive plain-language descriptions and cannot access raw MRI/Grad-CAM endpoints. Radiologists share the local worklist; multi-hospital tenancy is outside this MVP.

SQLite, uploaded DICOM, previews and heatmaps live under `.kneura/`, excluded from Git. Set `KNEURA_DATA_DIR` to relocate storage. Server audit events and report revisions persist across restarts; interrupted analysis is marked ERROR for explicit retry. Access requests are recorded in SQLite. This is a local research implementation, not production-hardened hospital authentication, encrypted storage, externally anchored/tamper-proof audit, PACS transport or clinical deployment infrastructure.

## API

| Method | Endpoint | Behavior |
| --- | --- | --- |
| POST | `/api/auth/login` | Authenticate email/password and server-owned role |
| GET / POST | `/api/auth/me`, `/api/auth/logout` | Session lookup / logout |
| GET / POST | `/api/cases` | Scoped worklist / multipart DICOM upload |
| GET | `/api/cases/{id}` | Authorized role-filtered case |
| POST | `/api/cases/{id}/analysis` | Start real model inference and evidence generation |
| POST | `/api/cases/{id}/findings/{findingId}/decision` | Approve or reject |
| POST / PATCH | `/api/cases/{id}/report` | Generate / edit draft |
| POST | `/api/cases/{id}/report/finalize` | Radiologist final approval |
| GET | `/api/cases/{id}/images/{filename}` | Authorized MRI or Grad-CAM PNG |
| GET | `/api/cases/{id}/export` | Final-only integration adapter JSON |
| GET | `/api/model`, `/api/validation` | Checkpoint metadata / attributed roadmap metrics |
| GET | `/api/health` | Service health |

Use a same-origin `/api` reverse proxy when hosting a built frontend. Configure `KNEURA_ORIGINS` for the exact UI origins and `KNEURA_SECURE_COOKIE=1` when using HTTPS. No external PACS/RIS/EHR connection is claimed by the JSON export adapter.

## Verification

```powershell
npm run build
npm run lint
npm test
npm run test:backend
npm run model:check
```

Backend tests include authentication, role/assignment isolation, review completeness, rejected-input exclusion, report locking, authored statement provenance, invalid DICOM rejection, real supplied-checkpoint inference, generated Grad-CAM images, and equality with the untouched supplied study-inference function on six synthetic slices. Synthetic test data establishes software behavior only, not clinical accuracy.

The validation API reads the supplied performance and model-lock JSON files: 9 studies, 844 windows, 27 series and approximately 0.714 macro AUROC. These metrics were not independently reproduced; no evaluation date was provided. No real clinical DICOM sample or original evaluation dataset was supplied in the project.

The existing responsive UI, theme, print styles and role-specific routes are retained. Pilot and startup roadmap work—live PACS/RIS/EHR transport, SSO, deployment hardening, external validation, additional joints and RAG—remains outside the finals MVP.

## Clinical frontend verification

The existing case workspace now includes stable five-slice window selection, individual InstanceNumber buttons, slice stepping, and a return-to-selected-evidence action. Evidence cards and report trace dialogs reuse the backend MRI and Grad-CAM URLs, with loading, unavailable, error and retry states. They display the supplied series UID, window index, InstanceNumbers, decision provenance and analysis model version. Missing metadata is labeled unavailable.

The frontend consumes the existing `/api` camelCase contract: `Case.findings`, `Finding.evidence`, `Finding.decision`, `Case.analysis.modelVersion`, `Case.report` and `Case.audit`. Series `id` is the DICOM SeriesInstanceUID returned by ingestion. No parallel snake_case endpoint or clinical adapter was introduced. Displaying a probability as a percentage does not alter the server's prediction. Orthopedist and patient views hide probabilities; patient views also omit imaging and model provenance.

No new routes replace the current navigation. Radiologists use `/radiologist/cases/:id` and its `/review`, `/report`, `/audit` tabs. Orthopedists use `/orthopedist/cases/:id` and `/report`; patients use `/patient/mri/:id`. The existing `/ROLE/report/:id` detail alias is retained. All-rejected cases can generate the existing backend's empty-approved-input draft; the UI explicitly states that this does not establish a normal examination. Final status is accepted only from the backend response.

Browser tests use synthetic, intercepted API fixtures to exercise the real frontend without seeding patient data. Backend tests separately verify actual authorization, inference and report gates. Run:

```powershell
npx playwright install chromium
npm run test:e2e
```

If Chromium cannot be downloaded and Microsoft Edge is installed:

```powershell
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:e2e
```

The suite covers desktop (1440px) and mobile (390px) routes, canonical ordering, MRI/window navigation, backend-image display and recovery, all 12 explicit decisions, approved-only and all-rejected drafts, editing/finalization, report provenance, role isolation, missing evidence and processing states. Screenshots and failure traces are written to the ignored `test-results/` directory. These fixtures establish software behavior, not clinical image quality or diagnostic accuracy.

## AI team handoff integration

Open **AI handoff** in the radiologist navigation (`/radiologist/handoff`) to inspect the supplied canonical reference. The frontend imports `05_GOLDEN_CASE/KNEE_AI_GOLDEN_CASE.json` and joins the matching study/class entries from `07_GRADCAM/GRADCAM_ALL_12_RESULTS.json` to the original PNG overlays. Assets are bundled by Vite without image processing. The read-only reference never creates a clinical case, sends decisions, generates a report, or grants final approval. Its six approvals and six rejections are explicitly simulated; its report remains DRAFT with final approval PENDING.

Study-mean probabilities and individual-window probabilities are shown separately at their supplied precision. Model output names (`PF OA`, `Baker's`) and zero-based handoff window indexes remain unchanged. Existing live case display aliases and one-based backend evidence windows retain their own contract. Original DICOM slices and separate raw MRI images were not included, so the reference provides the supplied overlays and provenance without inventing slice navigation or extracting a new image from the overlay.

Model and Validation pages also display attributed reference metadata from `01_MODEL`, `02_PERFORMANCE`, and the Grad-CAM contract. `03_MRI_PROVENANCE` supplies the reference series table. The canonical golden case takes precedence over the slightly different floating-point values in `06_AI_MODULE/.../DEMO`; no probabilities are averaged, thresholded or replaced. The original checkpoint hash is reference metadata, not a claim that the reconstructed local checkpoint ZIP has the same file hash.

The handoff documents `POST /api/v1/ai/analyze`, but this local backend implements `POST /api/cases/{id}/analysis`. The frontend continues to use the working case API for live studies. Adding the documented versioned endpoint is backend integration work; the UI does not pretend it is available. Neither the supplied inference modules nor the existing backend/model logic were changed for this frontend integration.

Live case pages also render optional patient display ID, age, sex, symptoms, medical history and clinical notes from the API patient/context schema. Radiologists can inspect supplied analysis counts, aggregation, deployed checkpoint hash, exact study probability and selected-window probability. Orthopedist/patient views retain their existing restrictions. Missing context is labeled Not supplied; golden-case properties are never copied into a live case. The current ingestion API does not populate the optional hospital/clinician context fields or accept edits to them.

Expandable source sections in Model, Validation and AI handoff expose the remaining supplied model, preprocessing, reproducibility, Grad-CAM statistics, MRI provenance, patient schema, backend/AI contracts, validation summary, manifest and report-input properties. These are attributed package records, not newly performed checks or clinical approvals.


## Technova verification and controlled demo

See [the implementation audit](docs/TECHNOVA_IMPLEMENTATION_AUDIT.md) for verified behavior, changes, remaining limitations and the 14-part delivery report.

A real-backend browser test now covers the full workflow with actual checkpoint inference. It starts isolated local API/Vite servers, creates temporary demo accounts, uploads six synthetic DICOM images, reviews all 12 findings, edits/finalizes a report and signs in as both downstream roles. No HTTP responses or model outputs are mocked in this test. It explicitly uses the **template** report provider, not an LLM. Demo credentials are randomly generated for the test run and never installed in the clinical database.

```powershell
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm run test:live
```

For a manual software demonstration without a clinical sample:

```powershell
npm run demo:dicom
```

Upload `.kneura/demo-study.zip` using the existing UI. This contains artificial noise, clearly marked **DEMO**, not anatomical MRI. Run analysis to obtain actual model outputs; those outputs have no clinical meaning. The command does not seed predictions, reports or approvals and refuses to overwrite an existing package. Choose another file with `python -m backend.demo --output .kneura/demo-study-2.zip`. For patient access, provision a patient account with `--patient-id DEMO-SYNTHETIC`; explicitly assign the created case to an orthopedist using the existing `manage assign` command.

Workflow additions:

- Failed/interrupted analysis persists `ERROR`; the worklist offers an Errors filter and the case offers Retry analysis.
- Case creation records `createdAt` and the DICOM patient reference. Available age in years and sex are retained; absent clinical context is not invented.
- Decisions record previous/current state, actor ID, finding ID, case ID and timestamp. Report generation also requires a matching persisted decision, reviewer ID and timestamp for every class.
- Reports move `DRAFT -> UNDER_REVIEW -> FINAL`. Saving records review/editor identity; finalization requires saved review and a radiologist-authored impression. Every prior version retains its text and editor provenance. Older drafts can be saved again to record explicit review; historical identities are never fabricated.
- Evidence cards can jump directly to their original MRI location. The report screen exposes saved version history to radiologists.
- Export is labeled an MVP demonstration adapter, contains approved findings only and excludes draft revisions for every role.
- `backend/auth.py` defines the replaceable identity-provider boundary. The existing local cookie provider remains the implementation; no SSO integration is claimed. Signing in rotates the current browser session; denied/anonymous API requests are logged. Expired clinical requests clear the frontend workspace and return to sign-in.
- SQLite keeps clinical children in an atomic case JSON aggregate. `backend/relationships.py` rejects broken study/patient, evidence/series/image/analysis, report/finding and audit/case links before persistence. This is application-enforced aggregate integrity, not a normalized relational clinical schema or tamper-proof store.

All new fields are additive in existing JSON case documents; no destructive database migration is required. Old audit records lack the newly introduced structured fields and remain unchanged. `KNEURA_API_PROXY` optionally changes the local Vite upstream (default `http://127.0.0.1:8000`); `VITE_API_BASE_URL` remains the browser base URL. Use same-origin `/api` for cookie and image routing.


## Latest finals stabilization

The [Finals runbook](docs/FINALS_RUNBOOK.md), [gap matrix](docs/FINALS_GAP_MATRIX.md), and [engineering report](docs/FINALS_ENGINEERING_REPORT.md) supersede the earlier audit for the newly added narrative provider, jobs, viewer, audit hashes and manual attachments.

New commands:

```powershell
npm run demo:start
npm run preflight
npm run demo:verify -- --authorization .kneura/demo-authorization.json
```

Readiness is deliberately nonzero while the actual LLM, authorized de-identified MRI, required eligibility CSV or running services are missing. The supplied KNEE-AI weights are the knee classifier, not MRI data or a report-writing language model. The newer handoff ZIP was identical to the existing files and did not supply either missing dependency.
