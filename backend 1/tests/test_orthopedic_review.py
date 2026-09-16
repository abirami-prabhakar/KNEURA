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
from app.workflow import WorkflowState, can_transition, transition_workflow

ORTHO_HEADERS = {
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


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_ortho.db'}", connect_args={"check_same_thread": False}
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


# 1. Orthopedic endpoint requires authentication.
def test_1_endpoint_requires_authentication(client):
    res_list = client[0].get("/orthopedic/studies")
    assert res_list.status_code == 401

    res_get = client[0].get("/orthopedic/studies/study-1")
    assert res_get.status_code == 401

    res_sub = client[0].post(
        "/orthopedic/study-1/review",
        json={"assessment": "ACL tear", "recommendation": "Surgery"},
    )
    assert res_sub.status_code == 401


# 2. Non-orthopedic role cannot submit orthopedic review.
@pytest.mark.parametrize("headers", [RADIOLOGIST_HEADERS, CLINICIAN_HEADERS])
def test_2_non_orthopedic_role_rejected(client, headers):
    db = client[1]()
    db.add(Study(study_id="study-1", workflow_state=WorkflowState.RADIOLOGIST_APPROVED.value))
    db.add(Report(id=1, study_id="study-1", author_id="rad", status="APPROVED", draft_content="Approved report text"))
    db.commit()
    db.close()

    res_list = client[0].get("/orthopedic/studies", headers=headers)
    assert res_list.status_code == 403

    res_get = client[0].get("/orthopedic/studies/study-1", headers=headers)
    assert res_get.status_code == 403

    res_post = client[0].post(
        "/orthopedic/study-1/review",
        headers=headers,
        json={"assessment": "ACL tear", "recommendation": "Surgery"},
    )
    assert res_post.status_code == 403


# 3. Orthopedic role can access an eligible study.
@pytest.mark.parametrize("headers", [ORTHO_HEADERS, ORTHO_SURGEON_HEADERS])
def test_3_orthopedic_role_can_access_eligible_study(client, headers):
    db = client[1]()
    db.add(Study(study_id="study-1", workflow_state=WorkflowState.RADIOLOGIST_APPROVED.value))
    db.add(Report(id=1, study_id="study-1", author_id="rad", status="APPROVED", draft_content="Final approved text"))
    db.commit()
    db.close()

    res = client[0].get("/orthopedic/studies", headers=headers)
    assert res.status_code == 200
    studies = res.json()
    assert len(studies) == 1
    assert studies[0]["study_id"] == "study-1"
    assert studies[0]["workflow_state"] == "RADIOLOGIST_APPROVED"
    assert studies[0]["approved_report"] == "Final approved text"

    res_single = client[0].get("/orthopedic/studies/study-1", headers=headers)
    assert res_single.status_code == 200
    assert res_single.json()["study_id"] == "study-1"
    assert res_single.json()["approved_report"] == "Final approved text"


# 4. Study must be RADIOLOGIST_APPROVED before orthopedic review.
# 5, 6, 7. AI_COMPLETE, RADIOLOGIST_REVIEW, REPORT_DRAFT rejected.
@pytest.mark.parametrize(
    "ineligible_state",
    [
        WorkflowState.AI_COMPLETE.value,
        WorkflowState.RADIOLOGIST_REVIEW.value,
        WorkflowState.REPORT_DRAFT.value,
    ],
)
def test_4_5_6_7_ineligible_states_rejected(client, ineligible_state):
    db = client[1]()
    db.add(Study(study_id="ineligible-study", workflow_state=ineligible_state))
    db.commit()
    db.close()

    res_get = client[0].get("/orthopedic/studies/ineligible-study", headers=ORTHO_HEADERS)
    assert res_get.status_code == 409

    res_post = client[0].post(
        "/orthopedic/ineligible-study/review",
        headers=ORTHO_HEADERS,
        json={"assessment": "Plan", "recommendation": "Cons"},
    )
    assert res_post.status_code == 409

    # Also verify it does not appear in list of eligible studies
    res_list = client[0].get("/orthopedic/studies", headers=ORTHO_HEADERS)
    assert res_list.status_code == 200
    assert all(s["study_id"] != "ineligible-study" for s in res_list.json())


# 8. Unapproved report cannot be exposed to orthopedic reviewer.
# 9. Draft report cannot be exposed.
def test_8_9_unapproved_or_draft_report_not_exposed(client):
    db = client[1]()
    db.add(Study(study_id="study-draft-only", workflow_state=WorkflowState.REPORT_DRAFT.value))
    db.add(Report(id=1, study_id="study-draft-only", author_id="rad", status="DRAFT", draft_content="Draft report content"))
    db.commit()
    db.close()

    res = client[0].get("/orthopedic/studies/study-draft-only", headers=ORTHO_HEADERS)
    assert res.status_code == 409

    res_list = client[0].get("/orthopedic/studies", headers=ORTHO_HEADERS)
    assert all(s["study_id"] != "study-draft-only" for s in res_list.json())


# 10, 11, 12, 13, 21. CRITICAL CLINICAL DATA-BOUNDARY TEST:
# Fixture contains raw AI prediction, CONFIRMED finding, REJECTED finding, draft report, approved report, radiologist internal notes.
# Verify orthopedic-facing response contains:
# APPROVED REPORT: YES
# RAW AI PROBABILITIES: NO
# REJECTED FINDING: NO
# DRAFT REPORT: NO
# INTERNAL RADIOLOGIST NOTES: NO
# RAW PREDICTION OBJECT: NO
def test_clinical_data_boundary_security(client):
    db = client[1]()
    db.add(Study(study_id="boundary-study", workflow_state=WorkflowState.RADIOLOGIST_APPROVED.value))

    # Raw AI predictions with probabilities
    db.add_all([
        Prediction(study_id="boundary-study", label="ACL", confidence=0.887766),
        Prediction(study_id="boundary-study", label="Effusion", confidence=0.443322),
    ])

    # Radiologist review with confirmed and rejected findings + internal notes
    rev = RadiologistReview(
        study_id="boundary-study",
        reviewer_id="radiologist-42",
        decision="EDITED",
        notes="CONFIDENTIAL_RADIOLOGIST_INTERNAL_NOTES_DO_NOT_LEAK",
    )
    db.add(rev)
    db.flush()
    db.add_all([
        ValidatedFinding(review_id=rev.id, finding="ACL tear", outcome="CONFIRMED", details="Confirmed tear"),
        ValidatedFinding(review_id=rev.id, finding="Baker cyst", outcome="REJECTED", details="SECRET_REJECTED_FINDING_DETAILS"),
    ])

    # Old draft report and final approved report
    db.add(Report(id=1, study_id="boundary-study", author_id="rad", status="APPROVED", draft_content="FINAL_APPROVED_CLINICAL_REPORT_CONTENT"))
    db.commit()
    db.close()

    res = client[0].get("/orthopedic/studies/boundary-study", headers=ORTHO_HEADERS)
    assert res.status_code == 200
    body = res.json()
    raw_response_text = str(body)

    # APPROVED REPORT: YES
    assert "FINAL_APPROVED_CLINICAL_REPORT_CONTENT" in body["approved_report"]

    # RAW AI PROBABILITIES: NO
    assert "0.887766" not in raw_response_text
    assert "0.443322" not in raw_response_text
    assert "probabilities" not in body

    # REJECTED FINDING: NO
    assert "SECRET_REJECTED_FINDING_DETAILS" not in raw_response_text
    assert "rejected_findings" not in body

    # DRAFT REPORT: NO
    assert "draft_content" not in body

    # INTERNAL RADIOLOGIST NOTES: NO
    assert "CONFIDENTIAL_RADIOLOGIST_INTERNAL_NOTES_DO_NOT_LEAK" not in raw_response_text
    assert "notes" not in body

    # RAW PREDICTION OBJECT: NO
    assert "predictions" not in body
    assert "Prediction" not in raw_response_text


# 14. Orthopedic review persists correctly.
# 15. reviewer_id persists correctly.
# 16. Successful review transitions to ORTHOPEDIC_REVIEW state.
# 17. Successful review creates ORTHOPEDIC_REVIEW_SUBMITTED audit.
# 18. Workflow transition creates WORKFLOW_TRANSITION audit.
def test_orthopedic_review_persistence_and_audit(client):
    db = client[1]()
    db.add(Study(study_id="study-to-review", workflow_state=WorkflowState.RADIOLOGIST_APPROVED.value))
    db.add(Report(id=1, study_id="study-to-review", author_id="rad", status="APPROVED", draft_content="Approved report text"))
    db.commit()
    db.close()

    payload = {
        "assessment": "High-grade complete ACL rupture with medial joint line tenderness.",
        "recommendation": "Recommend arthroscopic ACL reconstruction with autograft.",
        "notes": "Patient advised regarding surgical vs conservative management options.",
    }

    res = client[0].post("/orthopedic/study-to-review/review", headers=ORTHO_HEADERS, json=payload)
    assert res.status_code == 201
    body = res.json()
    assert body["study_id"] == "study-to-review"
    assert body["reviewer_id"] == "surgeon-77"
    assert body["assessment"] == payload["assessment"]
    assert body["recommendation"] == payload["recommendation"]
    assert body["notes"] == payload["notes"]
    assert body["workflow_state"] == "ORTHOPEDIC_REVIEW"

    # Verify database persistence
    db = client[1]()
    persisted_review = db.query(OrthopedicReview).filter_by(study_id="study-to-review").one()
    assert persisted_review.reviewer_id == "surgeon-77"
    assert persisted_review.assessment == payload["assessment"]
    assert persisted_review.recommendation == payload["recommendation"]

    persisted_study = db.query(Study).filter_by(study_id="study-to-review").one()
    assert persisted_study.workflow_state == "ORTHOPEDIC_REVIEW"

    # Verify audit events
    audits = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    actions = [a.action for a in audits]
    assert "ORTHOPEDIC_REVIEW_SUBMITTED" in actions
    assert "WORKFLOW_TRANSITION" in actions

    ortho_audit = [a for a in audits if a.action == "ORTHOPEDIC_REVIEW_SUBMITTED"][0]
    assert ortho_audit.actor_id == "surgeon-77"
    assert ortho_audit.study_id == "study-to-review"

    trans_audit = [a for a in audits if a.action == "WORKFLOW_TRANSITION"][0]
    assert trans_audit.actor_id == "surgeon-77"
    assert trans_audit.study_id == "study-to-review"
    assert "from_state=RADIOLOGIST_APPROVED" in trans_audit.details
    assert "to_state=ORTHOPEDIC_REVIEW" in trans_audit.details
    db.close()


# 19. Failed orthopedic review does not partially persist.
def test_19_failed_review_transactional_rollback(client, monkeypatch):
    db = client[1]()
    db.add(Study(study_id="study-rollback", workflow_state=WorkflowState.RADIOLOGIST_APPROVED.value))
    db.add(Report(id=1, study_id="study-rollback", author_id="rad", status="APPROVED", draft_content="Approved text"))
    db.commit()
    db.close()

    import app.main as main_mod

    def failing_transition(*args, **kwargs):
        raise RuntimeError("Simulated failure during orthopedic transition")

    monkeypatch.setattr(main_mod, "transition_workflow", failing_transition)

    with pytest.raises(RuntimeError, match="Simulated failure during orthopedic transition"):
        client[0].post(
            "/orthopedic/study-rollback/review",
            headers=ORTHO_HEADERS,
            json={"assessment": "Valid assessment", "recommendation": "Valid plan"},
        )

    # Verify complete rollback
    db = client[1]()
    reviews = db.query(OrthopedicReview).filter_by(study_id="study-rollback").all()
    assert reviews == []

    study = db.query(Study).filter_by(study_id="study-rollback").one()
    assert study.workflow_state == "RADIOLOGIST_APPROVED"

    audits = db.execute(select(AuditLog)).scalars().all()
    assert audits == []
    db.close()


# 20. Duplicate/invalid orthopedic submission is handled safely.
def test_20_duplicate_submission_rejected(client):
    db = client[1]()
    db.add(Study(study_id="study-duplicate", workflow_state=WorkflowState.RADIOLOGIST_APPROVED.value))
    db.add(Report(id=1, study_id="study-duplicate", author_id="rad", status="APPROVED", draft_content="Approved text"))
    db.commit()
    db.close()

    # First submission succeeds
    res1 = client[0].post(
        "/orthopedic/study-duplicate/review",
        headers=ORTHO_HEADERS,
        json={"assessment": "First", "recommendation": "First plan"},
    )
    assert res1.status_code == 201

    # Second submission is rejected
    res2 = client[0].post(
        "/orthopedic/study-duplicate/review",
        headers=ORTHO_HEADERS,
        json={"assessment": "Second", "recommendation": "Second plan"},
    )
    assert res2.status_code == 409
    assert "already undergone orthopedic review" in res2.json()["detail"]


# Validation: whitespace-only / empty fields rejected
@pytest.mark.parametrize("payload", [
    {"assessment": "", "recommendation": "Rec"},
    {"assessment": "   ", "recommendation": "Rec"},
    {"assessment": "Assess", "recommendation": ""},
    {"assessment": "Assess", "recommendation": "   "},
])
def test_validation_whitespace_only_rejected(client, payload):
    res = client[0].post("/orthopedic/some-study/review", headers=ORTHO_HEADERS, json=payload)
    assert res.status_code == 422


# Missing study returns 404
def test_missing_study_returns_404(client):
    res_get = client[0].get("/orthopedic/studies/missing-study", headers=ORTHO_HEADERS)
    assert res_get.status_code == 404

    res_post = client[0].post(
        "/orthopedic/missing-study/review",
        headers=ORTHO_HEADERS,
        json={"assessment": "Assess", "recommendation": "Rec"},
    )
    assert res_post.status_code == 404


# Workflow transition legality tests
def test_workflow_transitions_from_non_approved_states_rejected():
    assert can_transition(WorkflowState.RADIOLOGIST_APPROVED, WorkflowState.ORTHOPEDIC_REVIEW)
    assert not can_transition(WorkflowState.AI_COMPLETE, WorkflowState.ORTHOPEDIC_REVIEW)
    assert not can_transition(WorkflowState.RADIOLOGIST_REVIEW, WorkflowState.ORTHOPEDIC_REVIEW)
    assert not can_transition(WorkflowState.REPORT_DRAFT, WorkflowState.ORTHOPEDIC_REVIEW)
    assert not can_transition(WorkflowState.ORTHOPEDIC_REVIEW, WorkflowState.ORTHOPEDIC_REVIEW)
