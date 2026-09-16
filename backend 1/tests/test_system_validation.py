import os
from pathlib import Path
import pytest
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.llm_adapter import Member2ClinicalLLMAdapter, get_llm_adapter
from app.main import app, get_db
from app.models.audit_log import AuditLog
from app.models.orthopedic_review import OrthopedicReview
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.report import Report
from app.models.study import Study
from app.workflow import WorkflowState, LEGAL_TRANSITIONS, can_transition

DEMO_ROOT = Path("c:/Users/praka/Downloads/KNEE_AI_10_REAL_DEMO_INPUTS")
REAL_STUDY_ID = "1.2.826.0.1.3680043.8.498.90283565381042081768587894596970552767"

CANONICAL_LABELS = [
    "ACL", "MCL", "Medial Meniscus", "Lateral Meniscus", "Medial OA",
    "Lateral OA", "PF OA", "Effusion", "Synovitis", "Baker's",
    "Contusion", "Fracture",
]

RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "radiologist-42",
    "X-User-Role": "RADIOLOGIST",
}

ORTHO_HEADERS = {
    "X-Authenticated-User-Id": "surgeon-77",
    "X-User-Role": "ORTHOPEDIC",
}

PATIENT_HEADERS = {
    "X-Authenticated-User-Id": "patient-rsna-001",
    "X-User-Role": "PATIENT",
}

INTRUDER_PATIENT_HEADERS = {
    "X-Authenticated-User-Id": "patient-intruder-999",
    "X-User-Role": "PATIENT",
}


def _mock_member2_llm_generator(prompt: str) -> dict:
    """Deterministic Member 2 test generator producing compliant schema and safety contract."""
    assert REAL_STUDY_ID not in prompt
    provider_study_id = prompt.split("STUDY ID:\n", 1)[1].splitlines()[0]
    assert provider_study_id.startswith("study-")
    return {
        "title": "Knee MRI Report",
        "study_id": provider_study_id,
        "status": "DRAFT",
        "findings": [
            "Complete tear of the lateral meniscus noted.",
            "Medial compartment osteoarthritis with cartilage loss.",
            "Significant patellofemoral osteoarthritis.",
            "Joint synovitis.",
        ],
        "impression": "Lateral Meniscus tear, Medial OA, PF OA, and Synovitis.",
        "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
    }


@pytest.fixture()
def system_client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'system_validation.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_llm_adapter():
        return Member2ClinicalLLMAdapter(generate_llm_fn=_mock_member2_llm_generator)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm_adapter] = override_llm_adapter

    # Configure environment for real demo study inference
    prev_root = os.getenv("KNEE_AI_STUDY_ROOT")
    prev_meta = os.getenv("KNEE_AI_SERIES_METADATA_PATH")
    os.environ["KNEE_AI_STUDY_ROOT"] = str(DEMO_ROOT / "DICOM")
    os.environ["KNEE_AI_SERIES_METADATA_PATH"] = str(DEMO_ROOT / "ELIGIBLE_SERIES_MANIFEST.csv")

    with TestClient(app) as test_client:
        yield test_client, session_factory

    app.dependency_overrides.clear()
    if prev_root is not None:
        os.environ["KNEE_AI_STUDY_ROOT"] = prev_root
    else:
        os.environ.pop("KNEE_AI_STUDY_ROOT", None)
    if prev_meta is not None:
        os.environ["KNEE_AI_SERIES_METADATA_PATH"] = prev_meta
    else:
        os.environ.pop("KNEE_AI_SERIES_METADATA_PATH", None)
    engine.dispose()


@pytest.mark.skipif(not DEMO_ROOT.is_dir(), reason="Real RSNA demo inputs directory not found.")
def test_complete_vertical_clinical_lifecycle(system_client):
    """Executes and verifies the single unbroken chain for study 1.2.826...970552767.

    Chain:
    Real RSNA DICOM -> Model 1 AI -> Persistence -> Radiologist Review ->
    Member 2 LLM Draft -> Radiologist Edit -> Radiologist Approval ->
    Orthopedic Review -> Server-Side Patient Linkage -> Patient Release ->
    Patient Portal -> Patient-Safe Approved Report
    """
    client, session_factory = system_client

    # =========================================================================
    # STEP 1: AI INFERENCE (REAL RSNA DICOM STUDY)
    # =========================================================================
    db = session_factory()
    db.add(Study(study_id=REAL_STUDY_ID))
    db.commit()
    db.close()

    ai_res = client.post(
        "/api/v1/ai/analyze",
        json={"study_id": REAL_STUDY_ID, "action": "ANALYZE_KNEE_MRI"},
    )
    assert ai_res.status_code == 200, f"AI analysis failed: {ai_res.text}"
    ai_data = ai_res.json()

    assert ai_data["model_version"] == "KNEE-AI 3.3"
    assert ai_data["architecture"] == "StandaloneFiveSliceEfficientNet"
    assert ai_data["series_evaluated"] == 4
    assert ai_data["windows_evaluated"] == 58
    assert ai_data["requires_radiologist_review"] is True
    assert list(ai_data["probabilities"].keys()) == CANONICAL_LABELS
    assert len(ai_data["probabilities"]) == 12

    # Compare against ground reference CSV
    ref_df = pd.read_csv(DEMO_ROOT / "REFERENCE_AI_INFERENCE.csv")
    ref_row = ref_df.loc[ref_df["StudyInstanceUID"] == REAL_STUDY_ID].iloc[0]
    for label in CANONICAL_LABELS:
        pred_val = ai_data["probabilities"][label]
        ref_val = float(ref_row[label])
        assert abs(pred_val - ref_val) < 1e-4, f"Probability mismatch for {label}: {pred_val} vs {ref_val}"

    # Database Persistence Verification
    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    assert study.workflow_state == WorkflowState.AI_COMPLETE.value

    preds = db.query(Prediction).filter(Prediction.study_id == REAL_STUDY_ID).all()
    assert len(preds) == 12
    assert [p.label for p in preds] == CANONICAL_LABELS
    for p in preds:
        assert isinstance(p.confidence, float)
        assert 0.0 <= p.confidence <= 1.0
    db.close()

    # =========================================================================
    # STEP 2: RADIOLOGIST REVIEW (EDITED DECISION)
    # =========================================================================
    review_payload = {
        "decision": "MIXED",
        "notes": "Patient presents with lateral joint tenderness following acute pivoting injury.",
        "validated_findings": [
            {"finding": "lateral meniscus", "outcome": "EDITED", "details": "Definite complex tear."},
            {"finding": "medial oa", "outcome": "EDITED", "details": "Mild-to-moderate joint space narrowing."},
            {"finding": "pf oa", "outcome": "EDITED", "details": "Patellofemoral articular cartilage wear."},
            {"finding": "synovitis", "outcome": "EDITED", "details": "Mild synovial thickening."},
        ],
    }
    # Explicitly reject the remaining eight predictions; none are implicitly reviewed.
    reviewed_labels = {"Lateral Meniscus", "Medial OA", "PF OA", "Synovitis"}
    review_payload["validated_findings"].extend(
        {"finding": label, "outcome": "REJECTED"}
        for label in CANONICAL_LABELS if label not in reviewed_labels
    )
    review_res = client.post(
        f"/studies/{REAL_STUDY_ID}/review",
        headers=RADIOLOGIST_HEADERS,
        json=review_payload,
    )
    assert review_res.status_code == 201, f"Radiologist review failed: {review_res.text}"
    review_data = review_res.json()
    assert review_data["decision"] == "MIXED"
    assert len(review_data["validated_findings"]) == 12

    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    assert study.workflow_state == WorkflowState.RADIOLOGIST_REVIEW.value
    db.close()

    # =========================================================================
    # STEP 3: MEMBER 2 LLM DRAFT REPORT GENERATION
    # =========================================================================
    gen_res = client.post(
        f"/studies/{REAL_STUDY_ID}/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert gen_res.status_code == 201, f"Report generation failed: {gen_res.text}"
    report_data = gen_res.json()
    report_id = report_data["report_id"]
    assert report_data["status"] == "DRAFT"
    assert "findings" in report_data["draft_content"]

    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    assert study.workflow_state == WorkflowState.REPORT_DRAFT.value
    report_row = db.query(Report).filter(Report.id == report_id).one()
    assert report_row.status == "DRAFT"
    db.close()

    # =========================================================================
    # STEP 4: RADIOLOGIST EDIT DRAFT REPORT
    # =========================================================================
    updated_draft = (
        report_data["draft_content"]
        + "\nADDENDUM: Conservative management recommended initially before surgical arthroscopy."
    )
    edit_res = client.put(
        f"/reports/{report_id}",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": updated_draft},
    )
    assert edit_res.status_code == 200, f"Report edit failed: {edit_res.text}"
    assert edit_res.json()["status"] == "DRAFT"

    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    assert study.workflow_state == WorkflowState.REPORT_DRAFT.value
    report_row = db.query(Report).filter(Report.id == report_id).one()
    assert "ADDENDUM" in report_row.draft_content
    assert report_row.status == "DRAFT"
    db.close()

    # =========================================================================
    # STEP 5: RADIOLOGIST APPROVAL
    # =========================================================================
    approve_res = client.post(
        f"/reports/{report_id}/approve",
        headers=RADIOLOGIST_HEADERS,
    )
    assert approve_res.status_code == 200, f"Approval failed: {approve_res.text}"
    assert approve_res.json()["status"] == "APPROVED"

    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    assert study.workflow_state == WorkflowState.RADIOLOGIST_APPROVED.value
    report_row = db.query(Report).filter(Report.id == report_id).one()
    assert report_row.status == "APPROVED"
    db.close()

    # Verify duplicate approval is rejected
    dup_approve = client.post(f"/reports/{report_id}/approve", headers=RADIOLOGIST_HEADERS)
    assert dup_approve.status_code == 409

    # =========================================================================
    # STEP 6: ORTHOPEDIC CLINICIAN REVIEW
    # =========================================================================
    ortho_list = client.get("/orthopedic/studies", headers=ORTHO_HEADERS)
    assert ortho_list.status_code == 200
    assert any(s["study_id"] == REAL_STUDY_ID for s in ortho_list.json())

    ortho_study = client.get(f"/orthopedic/studies/{REAL_STUDY_ID}", headers=ORTHO_HEADERS)
    assert ortho_study.status_code == 200
    assert ortho_study.json()["study_id"] == REAL_STUDY_ID

    ortho_review_payload = {
        "assessment": "High-grade lateral meniscus tear confirmed on approved radiology report.",
        "recommendation": "Prescribe physical therapy; evaluate for arthroscopic repair if symptoms persist.",
        "notes": "Patient scheduled for follow-up in 4 weeks.",
    }
    ortho_res = client.post(
        f"/orthopedic/{REAL_STUDY_ID}/review",
        headers=ORTHO_HEADERS,
        json=ortho_review_payload,
    )
    assert ortho_res.status_code == 201, f"Orthopedic review submission failed: {ortho_res.text}"

    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    assert study.workflow_state == WorkflowState.ORTHOPEDIC_REVIEW.value
    ortho_rows = db.query(OrthopedicReview).filter(OrthopedicReview.study_id == REAL_STUDY_ID).all()
    assert len(ortho_rows) == 1
    assert ortho_rows[0].reviewer_id == "surgeon-77"
    db.close()

    # =========================================================================
    # STEP 7: TRUSTED SERVER-SIDE PATIENT ASSOCIATION & RELEASE
    # =========================================================================
    # 7A. Release without server-side patient_id must FAIL (409)
    unassigned_release = client.post(
        f"/studies/{REAL_STUDY_ID}/patient-release",
        headers=ORTHO_HEADERS,
    )
    assert unassigned_release.status_code == 409
    assert "no associated patient id" in unassigned_release.json()["detail"].lower()

    # 7B. Establish trusted server-side association
    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    study.patient_id = "patient-rsna-001"
    db.commit()
    db.close()

    # 7C. Attempting to hijack or supply arbitrary patient_id in release request is ignored
    client_supplied_hijack = client.post(
        f"/studies/{REAL_STUDY_ID}/patient-release",
        headers=ORTHO_HEADERS,
        json={"patient_id": "malicious-patient-666"},
    )
    # The release succeeds on the trusted association, but retains patient-rsna-001
    assert client_supplied_hijack.status_code == 200

    db = session_factory()
    study = db.query(Study).filter(Study.study_id == REAL_STUDY_ID).one()
    assert study.workflow_state == WorkflowState.PATIENT_RELEASED.value
    assert study.patient_id == "patient-rsna-001", "Patient ID was improperly modified by request!"
    db.close()

    # 7D. Duplicate release is rejected
    dup_release = client.post(f"/studies/{REAL_STUDY_ID}/patient-release", headers=ORTHO_HEADERS)
    assert dup_release.status_code == 409

    # =========================================================================
    # STEP 8: PATIENT PORTAL ACCESS & STRICT CLINICAL DATA BOUNDARY
    # =========================================================================
    # 8A. List reports for patient
    pat_list = client.get("/patient/reports", headers=PATIENT_HEADERS)
    assert pat_list.status_code == 200
    pat_studies = pat_list.json()
    assert len(pat_studies) == 1
    assert pat_studies[0]["study_id"] == REAL_STUDY_ID
    assert pat_studies[0]["status"] == "RELEASED"

    # 8B. Single study access
    pat_report_res = client.get(f"/patient/reports/{REAL_STUDY_ID}", headers=PATIENT_HEADERS)
    assert pat_report_res.status_code == 200
    pat_report = pat_report_res.json()
    assert pat_report["study_id"] == REAL_STUDY_ID
    assert pat_report["status"] == "RELEASED"
    assert "ADDENDUM" in pat_report["approved_report"]

    # 8C. Cross-patient isolation: intruder is strictly rejected
    intruder_res = client.get(f"/patient/reports/{REAL_STUDY_ID}", headers=INTRUDER_PATIENT_HEADERS)
    assert intruder_res.status_code == 403
    assert "Access forbidden" in intruder_res.json()["detail"]

    # 8D. Strict Clinical Data Boundary Verification
    raw_response_str = str(pat_report)
    assert "probabilities" not in pat_report
    assert "0.203452" not in raw_response_str
    assert "rejected_findings" not in pat_report
    assert "ACL is intact despite slight signal" not in raw_response_str  # Radiologist internal note
    assert "Patient presents with lateral joint tenderness" not in raw_response_str  # Radiologist review note
    assert "Prescribe physical therapy" not in raw_response_str  # Orthopedic clinical recommendation
    assert "notes" not in pat_report
    assert "assessment" not in pat_report
    assert "recommendation" not in pat_report
    assert "DICOM" not in raw_response_str
    assert "study_root" not in pat_report
    assert "series_metadata_path" not in pat_report

    # =========================================================================
    # STEP 9: END-TO-END AUDIT LOG TRACEABILITY
    # =========================================================================
    db = session_factory()
    audits = db.query(AuditLog).filter(AuditLog.study_id == REAL_STUDY_ID).order_by(AuditLog.id).all()
    actions = [a.action for a in audits]

    expected_sequence = [
        "RADIOLOGIST_REVIEW_SUBMITTED",
        "WORKFLOW_TRANSITION",           # to RADIOLOGIST_REVIEW
        "DRAFT_REPORT_GENERATED",
        "WORKFLOW_TRANSITION",           # to REPORT_DRAFT
        "REPORT_EDITED",
        "REPORT_APPROVED",
        "WORKFLOW_TRANSITION",           # to RADIOLOGIST_APPROVED
        "ORTHOPEDIC_REVIEW_SUBMITTED",
        "WORKFLOW_TRANSITION",           # to ORTHOPEDIC_REVIEW
        "WORKFLOW_TRANSITION",           # to PATIENT_RELEASED
        "PATIENT_RELEASED",
    ]
    for expected_action in expected_sequence:
        assert expected_action in actions, f"Missing audit action {expected_action} in {actions}"

    # Verify actors and study_id consistency across all audits
    for a in audits:
        assert a.study_id == REAL_STUDY_ID
        assert a.actor_id in ("system", "radiologist-42", "surgeon-77")
    db.close()


def test_illegal_workflow_transitions_comprehensive_matrix():
    """Validates that all illegal state transitions are blocked by the state machine."""
    all_states = list(WorkflowState)
    for current in all_states:
        allowed = LEGAL_TRANSITIONS.get(current, [])
        for target in all_states:
            if target in allowed:
                assert can_transition(current, target) is True
            elif current == WorkflowState.AI_COMPLETE and target == WorkflowState.AI_COMPLETE:
                assert can_transition(current, target) is True  # Idempotent re-run
            else:
                assert can_transition(current, target) is False, f"Transition from {current} to {target} should be illegal!"


def test_uninitialized_study_cannot_bypass_workflow(system_client):
    """Studies with workflow_state=None can only transition to AI_COMPLETE."""
    client, session_factory = system_client
    db = session_factory()
    db.add(Study(study_id="uninitialized-study", workflow_state=None))
    db.commit()
    db.close()

    assert can_transition(None, WorkflowState.AI_COMPLETE) is True
    assert can_transition(None, WorkflowState.RADIOLOGIST_REVIEW) is False
    assert can_transition(None, WorkflowState.REPORT_DRAFT) is False
    assert can_transition(None, WorkflowState.RADIOLOGIST_APPROVED) is False
    assert can_transition(None, WorkflowState.ORTHOPEDIC_REVIEW) is False
    assert can_transition(None, WorkflowState.PATIENT_RELEASED) is False

    # Endpoint enforcement
    rev_res = client.post(
        "/studies/uninitialized-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={"decision": "CONFIRMED", "validated_findings": [{"finding": "acl", "outcome": "CONFIRMED"}]},
    )
    assert rev_res.status_code == 409
