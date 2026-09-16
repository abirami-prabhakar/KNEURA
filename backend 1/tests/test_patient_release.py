from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app, get_db
from app.models.audit_log import AuditLog
from app.models.orthopedic_review import OrthopedicReview
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.report import Report
from app.models.study import Study
from app.workflow import WorkflowState

SURGEON_HEADERS = {
    "X-Authenticated-User-Id": "surgeon-77",
    "X-User-Role": "ORTHOPEDIC",
}

ORTHO_SURGEON_HEADERS = {
    "X-Authenticated-User-Id": "surgeon-88",
    "X-User-Role": "ORTHOPEDIC_SURGEON",
}

RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "radiologist-42",
    "X-User-Role": "RADIOLOGIST",
}

CLINICIAN_HEADERS = {
    "X-Authenticated-User-Id": "clinician-99",
    "X-User-Role": "CLINICIAN",
}

PATIENT_A_HEADERS = {
    "X-Authenticated-User-Id": "patient-101",
    "X-User-Role": "PATIENT",
}

PATIENT_B_HEADERS = {
    "X-Authenticated-User-Id": "patient-202",
    "X-User-Role": "PATIENT",
}


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_patient_release.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client, session_factory

    app.dependency_overrides.clear()
    engine.dispose()


# --------------------------------------------------------------------------
# 1. Release requires authentication (401)
# --------------------------------------------------------------------------
def test_1_release_requires_authentication(client):
    res = client[0].post("/studies/study-1/patient-release")
    assert res.status_code == 401
    assert "Authentication is required" in res.json()["detail"]


# --------------------------------------------------------------------------
# 2. Release requires clinical authority (403 for PATIENT and non-clinicians)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [
    PATIENT_A_HEADERS,
    {"X-Authenticated-User-Id": "unknown-1", "X-User-Role": "NURSE"},
    {"X-Authenticated-User-Id": "unknown-2", "X-User-Role": "ANALYST"},
])
def test_2_release_requires_clinical_authority(client, headers):
    res = client[0].post("/studies/study-1/patient-release", headers=headers)
    assert res.status_code == 403


# --------------------------------------------------------------------------
# 3. Authorized clinician roles can release study
# --------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [SURGEON_HEADERS, ORTHO_SURGEON_HEADERS, RADIOLOGIST_HEADERS, CLINICIAN_HEADERS])
def test_3_authorized_clinicians_can_release(client, headers):
    study_id = f"study-{headers['X-User-Role']}"
    db = client[1]()
    db.add(Study(study_id=study_id, workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="pat-1"))
    db.add(Report(id=None, study_id=study_id, author_id="rad-1", status="APPROVED", draft_content="Approved Report"))
    db.add(OrthopedicReview(study_id=study_id, reviewer_id="ortho-1", assessment="Assess", recommendation="Rec"))
    db.commit()
    db.close()

    res = client[0].post(f"/studies/{study_id}/patient-release", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["study_id"] == study_id
    assert data["workflow_state"] == "PATIENT_RELEASED"
    assert data["released_by"] == headers["X-Authenticated-User-Id"]


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 4. Study must be in ORTHOPEDIC_REVIEW before patient release
# 5, 6, 7, 8. Ineligible states rejected (409)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("ineligible_state", [
    WorkflowState.AI_COMPLETE.value,
    WorkflowState.RADIOLOGIST_REVIEW.value,
    WorkflowState.REPORT_DRAFT.value,
    WorkflowState.RADIOLOGIST_APPROVED.value,
])
def test_4_to_8_ineligible_states_rejected(client, ineligible_state):
    db = client[1]()
    db.add(Study(study_id="study-ineligible", workflow_state=ineligible_state, patient_id="p-1"))
    db.add(Report(id=None, study_id="study-ineligible", author_id="rad-1", status="APPROVED", draft_content="Approved Report"))
    db.add(OrthopedicReview(study_id="study-ineligible", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    res = client[0].post("/studies/study-ineligible/patient-release", headers=SURGEON_HEADERS)
    assert res.status_code == 409
    assert "Illegal workflow transition" in res.json()["detail"]


# --------------------------------------------------------------------------
# 9. Missing approved report blocks patient release (409)
# --------------------------------------------------------------------------
def test_9_missing_approved_report_blocks_release(client):
    db = client[1]()
    db.add(Study(study_id="study-no-report", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="p-1"))
    db.add(OrthopedicReview(study_id="study-no-report", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    res = client[0].post("/studies/study-no-report/patient-release", headers=SURGEON_HEADERS)
    assert res.status_code == 409
    assert "approved radiology report" in res.json()["detail"].lower()


# --------------------------------------------------------------------------
# 10. Missing orthopedic review blocks patient release (409)
# --------------------------------------------------------------------------
def test_10_missing_ortho_review_blocks_release(client):
    db = client[1]()
    db.add(Study(study_id="study-no-ortho", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="p-1"))
    db.add(Report(id=None, study_id="study-no-ortho", author_id="rad-1", status="APPROVED", draft_content="Approved Report"))
    db.commit()
    db.close()

    res = client[0].post("/studies/study-no-ortho/patient-release", headers=SURGEON_HEADERS)
    assert res.status_code == 409
    assert "orthopedic clinical review" in res.json()["detail"].lower()


# --------------------------------------------------------------------------
# 10b. Unassigned study (patient_id is NULL) cannot be released (409)
# --------------------------------------------------------------------------
def test_10b_unassigned_study_cannot_be_released(client):
    db = client[1]()
    db.add(Study(study_id="study-unassigned", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id=None))
    db.add(Report(id=None, study_id="study-unassigned", author_id="rad-1", status="APPROVED", draft_content="Approved Report"))
    db.add(OrthopedicReview(study_id="study-unassigned", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    res = client[0].post("/studies/study-unassigned/patient-release", headers=SURGEON_HEADERS)
    assert res.status_code == 409
    assert "no associated patient id" in res.json()["detail"].lower()


# --------------------------------------------------------------------------
# 10c. Release with patient_id supplied in body cannot arbitrarily bind ownership
# --------------------------------------------------------------------------
def test_10c_client_supplied_patient_id_cannot_bind_ownership(client):
    db = client[1]()
    # Study with NO patient_id attempting release with client-supplied patient_id
    db.add(Study(study_id="study-arbitrary-bind", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id=None))
    db.add(Report(id=None, study_id="study-arbitrary-bind", author_id="rad-1", status="APPROVED", draft_content="Approved Report"))
    db.add(OrthopedicReview(study_id="study-arbitrary-bind", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    res = client[0].post(
        "/studies/study-arbitrary-bind/patient-release",
        headers=SURGEON_HEADERS,
        json={"patient_id": "arbitrary-attacker-id"},
    )
    # Must reject release with 409 because server-side patient_id is not already populated
    assert res.status_code == 409
    assert "no associated patient id" in res.json()["detail"].lower()

    # Verify study.patient_id is still NULL in database
    db = client[1]()
    study = db.query(Study).filter(Study.study_id == "study-arbitrary-bind").one()
    assert study.patient_id is None
    assert study.workflow_state == WorkflowState.ORTHOPEDIC_REVIEW.value
    db.close()


# --------------------------------------------------------------------------
# 10d. Patient ownership remains unchanged during release
# --------------------------------------------------------------------------
def test_10d_patient_ownership_remains_unchanged_during_release(client):
    db = client[1]()
    # Study already has trusted patient_id="trusted-patient-42"
    db.add(Study(study_id="study-trusted", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="trusted-patient-42"))
    db.add(Report(id=None, study_id="study-trusted", author_id="rad-1", status="APPROVED", draft_content="Approved Report"))
    db.add(OrthopedicReview(study_id="study-trusted", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    # Attempt release while sending another patient_id in body
    res = client[0].post(
        "/studies/study-trusted/patient-release",
        headers=SURGEON_HEADERS,
        json={"patient_id": "hijacker-patient-99"},
    )
    assert res.status_code == 200

    # Verify patient_id remained trusted-patient-42
    db = client[1]()
    study = db.query(Study).filter(Study.study_id == "study-trusted").one()
    assert study.patient_id == "trusted-patient-42"
    assert study.workflow_state == WorkflowState.PATIENT_RELEASED.value
    db.close()


# --------------------------------------------------------------------------
# 11. Duplicate release is rejected (409)
# --------------------------------------------------------------------------
def test_11_duplicate_release_rejected(client):
    db = client[1]()
    db.add(Study(study_id="study-dup", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="p-1"))
    db.add(Report(id=None, study_id="study-dup", author_id="rad-1", status="APPROVED", draft_content="Report text"))
    db.add(OrthopedicReview(study_id="study-dup", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    # First release succeeds
    res1 = client[0].post("/studies/study-dup/patient-release", headers=SURGEON_HEADERS)
    assert res1.status_code == 200

    # Second release fails with 409 Conflict
    res2 = client[0].post("/studies/study-dup/patient-release", headers=SURGEON_HEADERS)
    assert res2.status_code == 409
    assert "already been released" in res2.json()["detail"].lower()


# --------------------------------------------------------------------------
# 12, 13, 14. Persistence, transition, and audit logs
# --------------------------------------------------------------------------
def test_12_13_14_persistence_and_audit(client):
    db = client[1]()
    db.add(Study(study_id="study-audit-test", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="patient-101"))
    db.add(Report(id=None, study_id="study-audit-test", author_id="rad-1", status="APPROVED", draft_content="Report text"))
    db.add(OrthopedicReview(study_id="study-audit-test", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    res = client[0].post(
        "/studies/study-audit-test/patient-release",
        headers=SURGEON_HEADERS,
    )
    assert res.status_code == 200

    # Verify DB state
    db = client[1]()
    study = db.query(Study).filter(Study.study_id == "study-audit-test").one()
    assert study.workflow_state == WorkflowState.PATIENT_RELEASED.value
    assert study.patient_id == "patient-101"

    # Verify audit logs
    audits = db.query(AuditLog).filter(AuditLog.study_id == "study-audit-test").all()
    actions = {a.action for a in audits}
    assert "WORKFLOW_TRANSITION" in actions
    assert "PATIENT_RELEASED" in actions

    release_audit = [a for a in audits if a.action == "PATIENT_RELEASED"][0]
    assert release_audit.actor_id == SURGEON_HEADERS["X-Authenticated-User-Id"]
    assert "released_to=patient-101" in release_audit.details

    transition_audit = [a for a in audits if a.action == "WORKFLOW_TRANSITION"][0]
    assert "from_state=ORTHOPEDIC_REVIEW; to_state=PATIENT_RELEASED" in transition_audit.details
    db.close()


# --------------------------------------------------------------------------
# 15. Transactional rollback safety
# --------------------------------------------------------------------------
def test_15_release_failure_rolls_back_cleanly(client, monkeypatch):
    db = client[1]()
    db.add(Study(study_id="study-rollback", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="patient-101"))
    db.add(Report(id=None, study_id="study-rollback", author_id="rad-1", status="APPROVED", draft_content="Report text"))
    db.add(OrthopedicReview(study_id="study-rollback", reviewer_id="ortho-1", assessment="A", recommendation="R"))
    db.commit()
    db.close()

    # Inject failure during db.commit
    def failing_commit(*args, **kwargs):
        raise RuntimeError("Database connection lost during release commit")

    from sqlalchemy.orm import Session
    monkeypatch.setattr(Session, "commit", failing_commit)

    with pytest.raises(RuntimeError, match="Database connection lost"):
        client[0].post("/studies/study-rollback/patient-release", headers=SURGEON_HEADERS)

    # Verify study is still in ORTHOPEDIC_REVIEW and no audit log was saved
    db = client[1]()
    study = db.query(Study).filter(Study.study_id == "study-rollback").one()
    assert study.workflow_state == WorkflowState.ORTHOPEDIC_REVIEW.value
    audits = db.query(AuditLog).filter(AuditLog.study_id == "study-rollback").all()
    assert len(audits) == 0
    db.close()


# --------------------------------------------------------------------------
# 16. Patient report access requires authentication (401)
# --------------------------------------------------------------------------
def test_16_patient_report_access_requires_auth(client):
    res1 = client[0].get("/patient/reports")
    assert res1.status_code == 401

    res2 = client[0].get("/patient/reports/study-1")
    assert res2.status_code == 401


# --------------------------------------------------------------------------
# 17. Patient report access requires PATIENT role (403 for non-patient)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [SURGEON_HEADERS, RADIOLOGIST_HEADERS, CLINICIAN_HEADERS])
def test_17_patient_report_access_requires_patient_role(client, headers):
    res1 = client[0].get("/patient/reports", headers=headers)
    assert res1.status_code == 403

    res2 = client[0].get("/patient/reports/study-1", headers=headers)
    assert res2.status_code == 403


# --------------------------------------------------------------------------
# 18. Patient can access their own released report (200)
# --------------------------------------------------------------------------
def test_18_patient_can_access_own_released_report(client):
    db = client[1]()
    db.add(Study(study_id="study-pat-101", workflow_state=WorkflowState.PATIENT_RELEASED.value, patient_id="patient-101"))
    db.add(Report(id=None, study_id="study-pat-101", author_id="rad-1", status="APPROVED", draft_content="Clear knee MRI findings"))
    db.add(AuditLog(action="PATIENT_RELEASED", actor_id="surgeon-77", study_id="study-pat-101", details="released_to=patient-101"))
    db.commit()
    db.close()

    res = client[0].get("/patient/reports/study-pat-101", headers=PATIENT_A_HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["study_id"] == "study-pat-101"
    assert data["status"] == "RELEASED"
    assert data["approved_report"] == "Clear knee MRI findings"
    assert "released_at" in data


# --------------------------------------------------------------------------
# 19. Patient cannot access another patient's report (403 cross-patient)
# --------------------------------------------------------------------------
def test_19_cross_patient_isolation(client):
    db = client[1]()
    # Study belongs to Patient A
    db.add(Study(study_id="study-pat-a", workflow_state=WorkflowState.PATIENT_RELEASED.value, patient_id="patient-101"))
    db.add(Report(id=None, study_id="study-pat-a", author_id="rad-1", status="APPROVED", draft_content="Report A text"))
    db.commit()
    db.close()

    # Patient B attempts to access Patient A's study
    res = client[0].get("/patient/reports/study-pat-a", headers=PATIENT_B_HEADERS)
    assert res.status_code == 403
    assert "Access forbidden" in res.json()["detail"]


# --------------------------------------------------------------------------
# 20, 21, 22, 23, 24. Pre-release states are not accessible to patient (409)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("pre_release_state", [
    WorkflowState.AI_COMPLETE.value,
    WorkflowState.RADIOLOGIST_REVIEW.value,
    WorkflowState.REPORT_DRAFT.value,
    WorkflowState.RADIOLOGIST_APPROVED.value,
    WorkflowState.ORTHOPEDIC_REVIEW.value,
])
def test_20_to_24_pre_release_states_inaccessible_to_patient(client, pre_release_state):
    study_id = f"study-{pre_release_state}"
    db = client[1]()
    db.add(Study(study_id=study_id, workflow_state=pre_release_state, patient_id="patient-101"))
    db.add(Report(id=None, study_id=study_id, author_id="rad-1", status="APPROVED", draft_content="Draft/Approved content"))
    db.commit()
    db.close()

    res = client[0].get(f"/patient/reports/{study_id}", headers=PATIENT_A_HEADERS)
    assert res.status_code == 409
    assert "not released to patient" in res.json()["detail"].lower()


# --------------------------------------------------------------------------
# 25. Patient report contains approved report text
# --------------------------------------------------------------------------
def test_25_patient_report_contains_approved_text(client):
    db = client[1]()
    db.add(Study(study_id="study-text-check", workflow_state=WorkflowState.PATIENT_RELEASED.value, patient_id="patient-101"))
    db.add(Report(id=None, study_id="study-text-check", author_id="rad-1", status="APPROVED", draft_content="FINAL_APPROVED_REPORT_TEXT_RSNA_001"))
    db.commit()
    db.close()

    res = client[0].get("/patient/reports/study-text-check", headers=PATIENT_A_HEADERS)
    assert res.status_code == 200
    assert res.json()["approved_report"] == "FINAL_APPROVED_REPORT_TEXT_RSNA_001"


# --------------------------------------------------------------------------
# 26-31. Strict clinical data-boundary allowlist tests:
# Verify NO raw probabilities, rejected findings, radiologist internal notes,
# orthopedic clinician notes, draft reports, or DICOM paths leak.
# --------------------------------------------------------------------------
def test_26_to_31_strict_clinical_data_boundary_allowlist(client):
    study_id = "boundary-study-patient"
    db = client[1]()
    study = Study(
        study_id=study_id,
        workflow_state=WorkflowState.PATIENT_RELEASED.value,
        patient_id="patient-101",
        study_root="/secret/dicom/study/root/path",
        series_metadata_path="/secret/dicom/series_metadata.json",
    )
    db.add(study)

    # Predictions
    db.add_all([
        Prediction(study_id=study_id, label="ACL", confidence=0.887766),
        Prediction(study_id=study_id, label="Baker's", confidence=0.443322),
    ])

    # Radiologist review with secret notes and rejected finding
    rev = RadiologistReview(
        study_id=study_id,
        reviewer_id="rad-secret",
        decision="EDITED",
        notes="CONFIDENTIAL_RADIOLOGIST_NOTES_FOR_INTERNAL_CLINICAL_USE_ONLY",
    )
    db.add(rev)
    db.flush()
    db.add_all([
        ValidatedFinding(review_id=rev.id, finding="ACL tear", outcome="CONFIRMED", details="Confirmed tear"),
        ValidatedFinding(review_id=rev.id, finding="Baker cyst", outcome="REJECTED", details="SECRET_REJECTED_FINDING_DETAILS_XYZZY"),
    ])

    # Orthopedic review with secret surgical assessment and notes
    db.add(OrthopedicReview(
        study_id=study_id,
        reviewer_id="surgeon-secret",
        assessment="CONFIDENTIAL_SURGICAL_RISK_ASSESSMENT_INTERNAL",
        recommendation="Surgical reconstruction candidate",
        notes="CONFIDENTIAL_INTERNAL_ORTHOPEDIC_NOTES_DO_NOT_REVEAL",
    ))

    # Draft report (id 10) superseded by Approved report (id 11)
    db.add(Report(id=10, study_id=study_id, author_id="rad-1", status="DRAFT", draft_content="OLD_DRAFT_REPORT_DO_NOT_LEAK"))
    db.add(Report(id=11, study_id=study_id, author_id="rad-1", status="APPROVED", draft_content="FINAL_APPROVED_CLINICAL_REPORT_PATIENT_FACING"))

    # Patient release audit
    db.add(AuditLog(action="PATIENT_RELEASED", actor_id="surgeon-77", study_id=study_id, details="released_to=patient-101"))
    db.commit()
    db.close()

    res = client[0].get(f"/patient/reports/{study_id}", headers=PATIENT_A_HEADERS)
    assert res.status_code == 200
    body = res.json()
    raw_response_text = str(body)

    # 1. APPROVED REPORT IS PRESENT
    assert body["approved_report"] == "FINAL_APPROVED_CLINICAL_REPORT_PATIENT_FACING"

    # 26. RAW PROBABILITIES: NEVER PRESENT
    assert "0.887766" not in raw_response_text
    assert "0.443322" not in raw_response_text
    assert "probabilities" not in body

    # 27. REJECTED FINDINGS: NEVER PRESENT
    assert "SECRET_REJECTED_FINDING_DETAILS_XYZZY" not in raw_response_text
    assert "rejected_findings" not in body

    # 28. RADIOLOGIST INTERNAL NOTES: NEVER PRESENT
    assert "CONFIDENTIAL_RADIOLOGIST_NOTES_FOR_INTERNAL_CLINICAL_USE_ONLY" not in raw_response_text
    assert "notes" not in body

    # 29. ORTHOPEDIC CLINICIAN NOTES: NEVER PRESENT
    assert "CONFIDENTIAL_INTERNAL_ORTHOPEDIC_NOTES_DO_NOT_REVEAL" not in raw_response_text
    assert "CONFIDENTIAL_SURGICAL_RISK_ASSESSMENT_INTERNAL" not in raw_response_text
    assert "assessment" not in body
    assert "recommendation" not in body

    # 30. DRAFT REPORT: NEVER EXPOSED
    assert "OLD_DRAFT_REPORT_DO_NOT_LEAK" not in raw_response_text
    assert "draft_content" not in body

    # 31. DICOM METADATA / PATHS: NEVER EXPOSED
    assert "/secret/dicom" not in raw_response_text
    assert "study_root" not in body
    assert "series_metadata_path" not in body


# --------------------------------------------------------------------------
# 32. GET /patient/reports lists only released studies belonging to that patient
# --------------------------------------------------------------------------
def test_32_list_patient_reports_filters_by_patient_and_release_state(client):
    db = client[1]()
    # Study 1: Patient A, Released -> Should be in list
    db.add(Study(study_id="study-a1", workflow_state=WorkflowState.PATIENT_RELEASED.value, patient_id="patient-101"))
    db.add(Report(id=None, study_id="study-a1", author_id="rad-1", status="APPROVED", draft_content="Report A1"))

    # Study 2: Patient A, Unreleased (in ORTHOPEDIC_REVIEW) -> Should NOT be in list
    db.add(Study(study_id="study-a2", workflow_state=WorkflowState.ORTHOPEDIC_REVIEW.value, patient_id="patient-101"))
    db.add(Report(id=None, study_id="study-a2", author_id="rad-1", status="APPROVED", draft_content="Report A2"))

    # Study 3: Patient B, Released -> Should NOT be in Patient A's list
    db.add(Study(study_id="study-b1", workflow_state=WorkflowState.PATIENT_RELEASED.value, patient_id="patient-202"))
    db.add(Report(id=None, study_id="study-b1", author_id="rad-1", status="APPROVED", draft_content="Report B1"))

    db.commit()
    db.close()

    res = client[0].get("/patient/reports", headers=PATIENT_A_HEADERS)
    assert res.status_code == 200
    studies = res.json()
    assert len(studies) == 1
    assert studies[0]["study_id"] == "study-a1"
    assert studies[0]["status"] == "RELEASED"
    assert studies[0]["approved_report"] == "Report A1"
