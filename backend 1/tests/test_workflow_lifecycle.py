from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.ai_adapter import AIIntegrationError, FrozenKneeAIAdapter
from app.database import Base
from app.llm_adapter import LLMIntegrationError, Member2ClinicalLLMAdapter, get_llm_adapter
from app.main import app, get_db
from app.models.audit_log import AuditLog
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.report import Report
from app.models.study import Study
from app.workflow import (
    INITIAL_WORKFLOW_STATE,
    LEGAL_TRANSITIONS,
    WorkflowState,
    can_transition,
    transition_workflow,
)

RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "radiologist-42",
    "X-User-Role": "RADIOLOGIST",
}

NON_RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "clinician-99",
    "X-User-Role": "CLINICIAN",
}

LABELS = [
    "ACL", "MCL", "Medial Meniscus", "Lateral Meniscus", "Medial OA",
    "Lateral OA", "PF OA", "Effusion", "Synovitis", "Baker's",
    "Contusion", "Fracture",
]


def _mock_ai_result():
    return {
        "study": {"study_id": "test-study", "series_evaluated": 3, "windows_evaluated": 44},
        "model": {"name": "KNEE-AI 3.3", "architecture": "StandaloneFiveSliceEfficientNet"},
        "probabilities": {label: index / 100.0 for index, label in enumerate(LABELS)},
    }


def _mock_llm_fn(_prompt):
    return {
        "title": "Knee MRI Report",
        "study_id": "test-study",
        "status": "DRAFT",
        "findings": ["ACL tear detected."],
        "impression": "ACL tear.",
        "note": "AI-generated draft.",
    }


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
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
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(
        generate_llm_fn=_mock_llm_fn
    )

    with TestClient(app) as test_client:
        yield test_client, session_factory

    app.dependency_overrides.clear()
    engine.dispose()


# 1. Initial valid workflow state is correct.
def test_1_initial_valid_workflow_state_is_correct(client):
    assert INITIAL_WORKFLOW_STATE == WorkflowState.AI_COMPLETE
    assert WorkflowState.AI_COMPLETE.value == "AI_COMPLETE"

    # A newly registered study without AI execution has no workflow state
    db = client[1]()
    db.add(Study(study_id="new-study"))
    db.commit()
    db.close()

    res = client[0].get("/studies/new-study/workflow")
    assert res.status_code == 200
    assert res.json() == {"study_id": "new-study", "state": None}


# 2. AI success -> AI_COMPLETE.
def test_2_ai_success_transitions_to_ai_complete(client, monkeypatch):
    monkeypatch.setattr(FrozenKneeAIAdapter, "analyze", lambda _self, _study: _mock_ai_result())

    db = client[1]()
    db.add(Study(study_id="test-study"))
    db.commit()
    db.close()

    res = client[0].post(
        "/api/v1/ai/analyze",
        json={"study_id": "test-study", "action": "ANALYZE_KNEE_MRI"},
    )
    assert res.status_code == 200

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "AI_COMPLETE"


# 3. Radiologist review success -> RADIOLOGIST_REVIEW.
def test_3_review_success_transitions_to_radiologist_review(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.AI_COMPLETE.value))
    db.add(Prediction(study_id="test-study", label="ACL", confidence=0.8))
    db.commit()
    db.close()

    res = client[0].post(
        "/studies/test-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Clinician confirms findings.",
            "validated_findings": [
                {"finding": "ACL tear", "outcome": "CONFIRMED", "details": "Verified"}
            ],
        },
    )
    assert res.status_code == 201

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "RADIOLOGIST_REVIEW"


# 4. Draft generation success -> REPORT_DRAFT.
def test_4_draft_generation_success_transitions_to_report_draft(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.RADIOLOGIST_REVIEW.value))
    db.add(Prediction(study_id="test-study", label="ACL", confidence=0.8))
    review = RadiologistReview(
        study_id="test-study",
        reviewer_id="radiologist-42",
        decision="CONFIRMED",
    )
    db.add(review)
    db.flush()
    db.add(ValidatedFinding(review_id=review.id, finding="ACL tear", outcome="CONFIRMED"))
    db.commit()
    db.close()

    res = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert res.status_code == 201

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "REPORT_DRAFT"


# 5. Report approval success -> RADIOLOGIST_APPROVED.
def test_5_report_approval_success_transitions_to_radiologist_approved(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.REPORT_DRAFT.value))
    report = Report(
        id=1,
        study_id="test-study",
        author_id="radiologist-42",
        status="DRAFT",
        draft_content="Report text",
    )
    db.add(report)
    db.commit()
    db.close()

    res = client[0].post("/reports/1/approve", headers=RADIOLOGIST_HEADERS)
    assert res.status_code == 200
    assert res.json()["status"] == "APPROVED"

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "RADIOLOGIST_APPROVED"


# 6. Report edit keeps REPORT_DRAFT.
def test_6_report_edit_keeps_report_draft(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.REPORT_DRAFT.value))
    report = Report(
        id=1,
        study_id="test-study",
        author_id="radiologist-42",
        status="DRAFT",
        draft_content="Initial draft",
    )
    db.add(report)
    db.commit()
    db.close()

    res = client[0].put(
        "/reports/1",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": "Edited draft"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "DRAFT"

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "REPORT_DRAFT"


# 7. Failed AI inference does not advance state.
def test_7_failed_ai_inference_does_not_advance_state(client, monkeypatch):
    monkeypatch.setattr(
        FrozenKneeAIAdapter,
        "analyze",
        lambda _self, _study: (_ for _ in ()).throw(AIIntegrationError("AI service error")),
    )

    db = client[1]()
    db.add(Study(study_id="test-study"))
    db.commit()
    db.close()

    res = client[0].post(
        "/api/v1/ai/analyze",
        json={"study_id": "test-study", "action": "ANALYZE_KNEE_MRI"},
    )
    assert res.status_code == 503

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] is None


# 8. Failed review does not advance state.
def test_8_failed_review_does_not_advance_state(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.AI_COMPLETE.value))
    db.add(Prediction(study_id="test-study", label="ACL", confidence=0.8))
    db.commit()
    db.close()

    # Mismatch in decision vs outcome causes 422
    res = client[0].post(
        "/studies/test-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "validated_findings": [
                {"finding": "ACL tear", "outcome": "REJECTED"}
            ],
        },
    )
    assert res.status_code == 422

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "AI_COMPLETE"


# 9. Failed report generation does not advance state.
def test_9_failed_report_generation_does_not_advance_state(client):
    class FailingLLMAdapter(Member2ClinicalLLMAdapter):
        def generate_report(self, study_id, validated_findings, predictions, clinical_context=None, **boundary_context):
            raise LLMIntegrationError("LLM failure")

    app.dependency_overrides[get_llm_adapter] = lambda: FailingLLMAdapter()

    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.RADIOLOGIST_REVIEW.value))
    db.add(Prediction(study_id="test-study", label="ACL", confidence=0.8))
    review = RadiologistReview(
        study_id="test-study",
        reviewer_id="radiologist-42",
        decision="CONFIRMED",
    )
    db.add(review)
    db.flush()
    db.add(ValidatedFinding(review_id=review.id, finding="ACL tear", outcome="CONFIRMED"))
    db.commit()
    db.close()

    res = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert res.status_code == 503

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "RADIOLOGIST_REVIEW"


# 10. Failed approval does not advance state.
def test_10_failed_approval_does_not_advance_state(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.REPORT_DRAFT.value))
    report = Report(
        id=1,
        study_id="test-study",
        author_id="radiologist-42",
        status="DRAFT",
        draft_content="Report text",
    )
    db.add(report)
    db.commit()
    db.close()

    # Unauthenticated approval fails with 401
    res = client[0].post("/reports/1/approve")
    assert res.status_code == 401

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "REPORT_DRAFT"


def test_10b_authorized_approval_failure_rolls_back_cleanly(client, monkeypatch):
    """Genuinely authorized radiologist approval fails during completion and rolls back cleanly."""
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.REPORT_DRAFT.value))
    report = Report(
        id=1,
        study_id="test-study",
        author_id="radiologist-42",
        status="DRAFT",
        draft_content="Report draft content",
    )
    db.add(report)
    db.commit()
    db.close()

    # Simulate an unexpected failure during workflow transition / persistence
    import app.main as main_mod

    def failing_transition(*args, **kwargs):
        raise RuntimeError("Simulated failure during approval workflow transition")

    monkeypatch.setattr(main_mod, "transition_workflow", failing_transition)

    # Call approval with genuinely authorized radiologist credentials
    with pytest.raises(RuntimeError, match="Simulated failure during approval workflow transition"):
        client[0].post("/reports/1/approve", headers=RADIOLOGIST_HEADERS)

    # Verify state in database after failure/rollback
    db = client[1]()
    persisted_report = db.get(Report, 1)
    assert persisted_report.status == "DRAFT"

    persisted_study = db.query(Study).filter_by(study_id="test-study").one()
    assert persisted_study.workflow_state == WorkflowState.REPORT_DRAFT.value

    # Verify no REPORT_APPROVED audit was persisted
    approved_audits = db.execute(
        select(AuditLog).filter_by(action="REPORT_APPROVED")
    ).scalars().all()
    assert approved_audits == []

    # Verify no WORKFLOW_TRANSITION to RADIOLOGIST_APPROVED was persisted
    transition_audits = db.execute(
        select(AuditLog).filter_by(action="WORKFLOW_TRANSITION")
    ).scalars().all()
    assert not any("RADIOLOGIST_APPROVED" in (a.details or "") for a in transition_audits)
    db.close()


def test_workflow_state_none_not_bypassed(client):
    """Review, report generation, edit, and approval must not silently bypass when workflow_state is None."""
    db = client[1]()
    db.add(Study(study_id="uninit-study", workflow_state=None))
    db.add(Prediction(study_id="uninit-study", label="ACL", confidence=0.8))
    review = RadiologistReview(
        study_id="uninit-study",
        reviewer_id="radiologist-42",
        decision="CONFIRMED",
    )
    db.add(review)
    db.flush()
    db.add(ValidatedFinding(review_id=review.id, finding="ACL tear", outcome="CONFIRMED"))
    report = Report(
        id=99,
        study_id="uninit-study",
        author_id="radiologist-42",
        status="DRAFT",
        draft_content="Draft text",
    )
    db.add(report)
    db.commit()
    db.close()

    # 1. Review on uninitialized study rejected with 409
    res_rev = client[0].post(
        "/studies/uninit-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={"decision": "CONFIRMED", "validated_findings": [{"finding": "ACL tear", "outcome": "CONFIRMED"}]},
    )
    assert res_rev.status_code == 409

    # 2. Report generation on uninitialized study rejected with 409
    res_gen = client[0].post("/studies/uninit-study/generate-report", headers=RADIOLOGIST_HEADERS)
    assert res_gen.status_code == 409

    # 3. Report edit on uninitialized study rejected with 409
    res_edit = client[0].put("/reports/99", headers=RADIOLOGIST_HEADERS, json={"draft_content": "Edit"})
    assert res_edit.status_code == 409

    # 4. Report approval on uninitialized study rejected with 409
    res_appr = client[0].post("/reports/99/approve", headers=RADIOLOGIST_HEADERS)
    assert res_appr.status_code == 409


# 11. Invalid transition is rejected.
@pytest.mark.parametrize(
    "from_state,next_state",
    [
        (WorkflowState.AI_COMPLETE, WorkflowState.REPORT_DRAFT),
        (WorkflowState.AI_COMPLETE, WorkflowState.RADIOLOGIST_APPROVED),
        (WorkflowState.RADIOLOGIST_REVIEW, WorkflowState.RADIOLOGIST_APPROVED),
        (WorkflowState.REPORT_DRAFT, WorkflowState.PATIENT_RELEASED),
        (WorkflowState.RADIOLOGIST_APPROVED, WorkflowState.REPORT_DRAFT),
        (WorkflowState.RADIOLOGIST_APPROVED, WorkflowState.AI_COMPLETE),
        (WorkflowState.PATIENT_RELEASED, WorkflowState.AI_COMPLETE),
    ],
)
def test_11_invalid_transition_is_rejected(client, from_state, next_state):
    assert not can_transition(from_state, next_state)

    db = client[1]()
    study = Study(study_id="test-study", workflow_state=from_state.value)
    db.add(study)
    db.commit()

    with pytest.raises(Exception) as exc_info:
        transition_workflow(db, study, next_state, actor_id="test-actor")
    assert "409" in str(exc_info.value)
    db.close()


# 12. APPROVED report cannot move back to DRAFT workflow.
def test_12_approved_report_cannot_move_back_to_draft_workflow(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.RADIOLOGIST_APPROVED.value))
    db.add(Prediction(study_id="test-study", label="ACL", confidence=0.8))
    review = RadiologistReview(
        study_id="test-study",
        reviewer_id="radiologist-42",
        decision="CONFIRMED",
    )
    db.add(review)
    db.flush()
    db.add(ValidatedFinding(review_id=review.id, finding="ACL tear", outcome="CONFIRMED"))
    report = Report(
        id=1,
        study_id="test-study",
        author_id="radiologist-42",
        status="APPROVED",
        draft_content="Report text",
    )
    db.add(report)
    db.commit()
    db.close()

    # Attempting to generate a report again returns 409
    res = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert res.status_code == 409

    # Attempting to edit report returns 409
    edit_res = client[0].put(
        "/reports/1",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": "New edit"},
    )
    assert edit_res.status_code == 409


# 13. Workflow transition creates audit entry.
def test_13_workflow_transition_creates_audit_entry(client):
    db = client[1]()
    study = Study(study_id="test-study", workflow_state=WorkflowState.AI_COMPLETE.value)
    db.add(study)
    db.commit()

    transition_workflow(
        db=db,
        study=study,
        next_state=WorkflowState.RADIOLOGIST_REVIEW,
        actor_id="clinician-test",
    )
    db.commit()

    audit = db.execute(
        select(AuditLog).filter_by(action="WORKFLOW_TRANSITION")
    ).scalar_one()
    db.close()

    assert audit.action == "WORKFLOW_TRANSITION"
    assert audit.actor_id == "clinician-test"
    assert audit.study_id == "test-study"
    assert "from_state=AI_COMPLETE" in audit.details
    assert "to_state=RADIOLOGIST_REVIEW" in audit.details


# 14. Non-authorized user cannot trigger clinical transition.
def test_14_non_authorized_user_cannot_trigger_clinical_transition(client):
    db = client[1]()
    db.add(Study(study_id="test-study", workflow_state=WorkflowState.AI_COMPLETE.value))
    db.add(Prediction(study_id="test-study", label="ACL", confidence=0.8))
    db.commit()
    db.close()

    res = client[0].post(
        "/studies/test-study/review",
        headers=NON_RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "validated_findings": [{"finding": "ACL tear", "outcome": "CONFIRMED"}],
        },
    )
    assert res.status_code == 403

    workflow_res = client[0].get("/studies/test-study/workflow")
    assert workflow_res.status_code == 200
    assert workflow_res.json()["state"] == "AI_COMPLETE"


# 15. Missing study returns 404 where applicable.
def test_15_missing_study_returns_404(client):
    res = client[0].get("/studies/nonexistent-study/workflow")
    assert res.status_code == 404
    assert res.json()["detail"] == "Study was not found."


# 16. State cannot be arbitrarily set by a client.
def test_16_state_cannot_be_arbitrarily_set_by_client(client):
    # No POST/PUT to /studies/{study_id}/workflow exists
    post_res = client[0].post(
        "/studies/test-study/workflow",
        json={"state": "PATIENT_RELEASED"},
    )
    assert post_res.status_code in (404, 405)

    put_res = client[0].put(
        "/studies/test-study/workflow",
        json={"state": "PATIENT_RELEASED"},
    )
    assert put_res.status_code in (404, 405)


# 17. Orthopedic/patient states cannot be reached through Sprint 4 endpoints.
def test_17_orthopedic_and_patient_states_cannot_be_reached(client):
    for endpoint in ["/orthopedic-review", "/patient-release", "/studies/test-study/orthopedic-review", "/studies/test-study/release"]:
        res = client[0].post(endpoint)
        assert res.status_code in (404, 405)

    # In the legal transitions table, states exist as placeholders but cannot be triggered via main app endpoints
    assert WorkflowState.ORTHOPEDIC_REVIEW in LEGAL_TRANSITIONS[WorkflowState.RADIOLOGIST_APPROVED]
    assert WorkflowState.PATIENT_RELEASED in LEGAL_TRANSITIONS[WorkflowState.ORTHOPEDIC_REVIEW]
