# Approval handoff fix and rollout

## Expected flow

1. The radiologist reviews all 12 findings, generates a report, enters and saves the clinical impression, then selects **Approve final report**. Both the case and report must be `FINAL`.
2. Every authenticated orthopedist in this workspace can see that case in Cases and Reports. **Needs attention** includes finalized cases awaiting patient release. No manual `assign` command is required by the current authorization policy.
3. The orthopedist selects **Approve for Patient**. The server persists the release flag, approving account, timestamp and audit event.
4. Only the patient account whose `patient_id` matches the case's saved patient identity can see the released case. An unrelated patient receives no list entry and HTTP 404 for direct case/export access.

Individual finding approvals and saved drafts do not constitute final report approval.

## Changes

- `src/App.tsx`: clear search and filter state after login; use role-aware attention filtering.
- `src/workflow.ts`: orthopedist attention means a final report awaiting release; radiologist attention retains its existing states.
- `backend/app.py`: patient authorization uses `patient.patient_id`, falling back to `study.patientId` for legacy records without a saved patient ID. It never accepts either of two conflicting IDs. Attaching DICOM must not change who owns a patient-first case.
- `backend/manage.py`: correct the patient provisioning instructions.
- `backend/patient_cases.py`: retain HTTP 200 for legacy multipart uploads; JSON case creation continues to return HTTP 201.

Existing finalization, report contents, audit records, release persistence and six-second downstream worklist refresh remain in place. No database migration or automatic approval is performed.

## Existing patient accounts

For a patient-first case, provision the patient account using its saved `patient.patient_id`. For older DICOM uploads, the saved ID equals `study.patientId`; records without a patient object still use `study.patientId`. Do not use a patient name as an authorization key. If an existing patient-first account was provisioned against the DICOM ID instead of the saved patient ID, an administrator must verify the identity and correct the account mapping before release is visible. The application must not infer that relationship.

## Rollout

Back up the active persistent data directory (SQLite plus studies and evidence) with the API stopped, then deploy backend and frontend from the same revision. For the existing Docker setup:

```powershell
docker compose stop api
# Take your deployment's backup of the kneura-data volume here.
docker compose up -d --build --wait
docker compose ps
```

Keep the same named volume and Compose project name. Do not run `down -v`. A fresh Docker volume does not contain local `.kneura` cases or accounts. See [Docker setup](DOCKER.md) for account provisioning and runtime configuration. This change needs no new environment variables or dependencies. Keep the existing single API worker.

## Acceptance checks

Use a synthetic case and separate authenticated browser profiles:

- Before final report approval: orthopedist and patient cannot list or open the case.
- After final report approval: orthopedist sees it under All cases and Needs attention; patient still cannot open it.
- After orthopedist release: the matching patient sees it; a different patient cannot open the case or export.
- Refresh and restart the API: the release remains saved.
- Switch from a radiologist account with an active search/Needs attention filter to an orthopedist account: the new worklist starts unfiltered.
- For a patient-first case with a differing DICOM ID, only the account matching the saved patient ID has access.

If All cases is still empty, check the authenticated role from `/api/auth/me`, both final statuses in the radiologist response, and whether all users reach the same API and persistent volume. The local source already permits orthopedists to list final reports; do not weaken that finalization gate to compensate for an old deployment or unfinished report.

Rollback uses the prior application image with the same volume. No schema rollback is required; review patient mappings before reverting the identity fix because the old version checks only DICOM IDs.

## Validation completed

- Backend: 61 tests passed across `test_backend.py`, `test_patient_cases.py` and `test_patient_identity.py`, including real checkpoint inference, approval gates, persisted release and patient isolation.
- Workflow: 8 tests passed.
- Browser: 4 targeted Chrome checks passed across desktop/mobile for Needs attention and account switching.
- Production build, TypeScript and lint passed.

No remote deployment or Docker image build was performed as part of this fix.
