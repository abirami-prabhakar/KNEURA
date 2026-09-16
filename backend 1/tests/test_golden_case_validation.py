import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.llm_adapter import Member2ClinicalLLMAdapter, get_llm_adapter
from app.main import app, get_db
from app.models.prediction import Prediction
from app.models.report import Report, ReportVersion
from app.models.study import Study

GOLDEN_CASE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "KNEE_AI_COMPLETE_BACKEND_PACKAGE"
    / "04_GOLDEN_CASE"
    / "KNEE_AI_GOLDEN_CASE.json"
)

RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "radiologist-golden",
    "X-User-Role": "RADIOLOGIST",
}

ORTHOPEDIC_HEADERS = {
    "X-Authenticated-User-Id": "orthopedic-golden",
    "X-User-Role": "ORTHOPEDIC_SURGEON",
}

RELEASE_HEADERS = {
    "X-Authenticated-User-Id": "orthopedic-golden",
    "X-User-Role": "ORTHOPEDIC_SURGEON",
}

PATIENT_HEADERS = {
    "X-Authenticated-User-Id": "DEMO-PATIENT-001",
    "X-User-Role": "PATIENT",
}


@pytest.fixture()
def golden_case_data():
    with open(GOLDEN_CASE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def client(tmp_path: Path, golden_case_data):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'golden_test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    study_id = "golden-study-demo-001"
    db.add(
        Study(
            study_id=study_id,
            patient_id=golden_case_data["patient"]["patient_id"],
            workflow_state="AI_COMPLETE",
            data_mode="DEMO",
            study_root=str(tmp_path),
        )
    )

    # Insert 12 Golden Case probabilities
    for label, prob in golden_case_data["ai"]["probabilities"].items():
        db.add(Prediction(study_id=study_id, label=label, confidence=float(prob)))

    db.commit()
    db.close()

    captured_prompts = []

    def mock_llm_fn(prompt: str) -> dict:
        captured_prompts.append(prompt)
        return {
            "title": "Knee MRI Report",
            "study_id": study_id,
            "status": "DRAFT",
            "findings": [
                "Medial meniscus abnormality detected.",
                "Lateral meniscus abnormality detected.",
                "Medial OA osteoarthritic changes identified.",
                "Lateral OA osteoarthritic changes identified.",
                "PF OA osteoarthritic changes identified.",
                "Synovitis identified.",
            ],
            "impression": "The approved findings demonstrate medial meniscus and lateral meniscus changes, medial OA, lateral OA, PF OA, and synovitis.",
            "note": golden_case_data["draft_report"]["limitations"],
        }

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(generate_llm_fn=mock_llm_fn)
    with TestClient(app) as test_client:
        yield test_client, session_factory, study_id, captured_prompts
    app.dependency_overrides.clear()


def test_golden_case_end_to_end_lifecycle(client, golden_case_data):
    test_client, session_factory, study_id, captured_prompts = client

    # 1. Verify Study Mode
    mode_res = test_client.get(f"/studies/{study_id}/mode")
    assert mode_res.status_code == 200
    assert mode_res.json()["data_mode"] == "DEMO"

    # 2. Submit Radiologist Mixed Review (6 approved, 6 rejected)
    approved_findings = set(golden_case_data["radiologist_review"]["approved_findings"])
    rejected_findings = set(golden_case_data["radiologist_review"]["rejected_findings"])
    assert len(approved_findings) == 6
    assert len(rejected_findings) == 6

    findings_payload = []
    for label in golden_case_data["ai"]["probabilities"].keys():
        outcome = "APPROVED" if label in approved_findings else "REJECTED"
        findings_payload.append({
            "finding": label,
            "outcome": outcome,
            "details": f"Radiologist marked {outcome}",
        })

    rev_res = test_client.post(
        f"/studies/{study_id}/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "MIXED",
            "notes": "Reviewed against MRI series. 6 approved, 6 rejected.",
            "validated_findings": findings_payload,
        },
    )
    assert rev_res.status_code == 201
    assert rev_res.json()["decision"] == "MIXED"

    # 3. Generate Draft Report & Verify LLM Safe Input Invariants
    gen_res = test_client.post(
        f"/studies/{study_id}/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert gen_res.status_code == 201
    rep_data = gen_res.json()
    report_id = rep_data["report_id"]
    assert rep_data["current_version"] == 1
    assert rep_data["status"] == "DRAFT"

    # Check safety invariants: LLM receives only approved findings
    assert len(captured_prompts) == 1
    prompt_str = captured_prompts[0]
    for app_finding in approved_findings:
        assert app_finding in prompt_str
    assert "Do not include rejected findings" in prompt_str or "rules" in prompt_str.lower()

    # 4. Edit Report (Version 2)
    edited_draft = rep_data["draft_content"] + "\nAdditional clinical note added by radiologist."
    edit_res = test_client.put(
        f"/reports/{report_id}",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": edited_draft},
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["current_version"] == 2

    # 5. Approve Report
    app_res = test_client.post(
        f"/reports/{report_id}/approve",
        headers=RADIOLOGIST_HEADERS,
    )
    assert app_res.status_code == 200
    assert app_res.json()["status"] == "APPROVED"
    assert app_res.json()["approved_version"] == 2

    # Verify version history via endpoint
    vers_res = test_client.get(
        f"/reports/{report_id}/versions",
        headers=RADIOLOGIST_HEADERS,
    )
    assert vers_res.status_code == 200
    assert len(vers_res.json()) == 2
    assert vers_res.json()[0]["version_number"] == 1
    assert vers_res.json()[1]["version_number"] == 2
    assert vers_res.json()[1]["status"] == "APPROVED"

    # 6. Generate Patient Explanation
    patient_exp = {
        "summary": "Your MRI shows signs of wear (osteoarthritis) in multiple compartments and meniscal changes.",
        "findings_explained": [
            {"finding": "Meniscal abnormality", "plain_english": "Cushioning cartilage wear"},
            {"finding": "Osteoarthritis", "plain_english": "Joint surface cartilage thinning"},
        ],
        "next_steps": "Discuss joint preservation strategies and physical therapy with your orthopedic physician.",
    }
    with patch("app.llm_adapter.Member2ClinicalLLMAdapter.generate_patient_explanation", return_value=patient_exp):
        pe_res = test_client.post(
            f"/studies/{study_id}/patient-explanation",
            headers=RADIOLOGIST_HEADERS,
        )
        assert pe_res.status_code == 200

    # 7. Submit Orthopedic Review with Patient Info Approved
    ortho_res = test_client.post(
        f"/orthopedic/{study_id}/review",
        headers=ORTHOPEDIC_HEADERS,
        json={
            "assessment": "Multicompartmental knee OA with meniscal degeneration.",
            "recommendation": "Conservative management: physical therapy, NSAIDs, unloader brace trial.",
            "patient_information_approved": True,
            "approved_followup_info": "Follow-up in clinic in 6 weeks with physical therapy progress report.",
        },
    )
    assert ortho_res.status_code == 201
    assert ortho_res.json()["workflow_state"] == "ORTHOPEDIC_REVIEW"

    # 8. Release to Patient
    rel_res = test_client.post(
        f"/studies/{study_id}/patient-release",
        headers=RELEASE_HEADERS,
        json={"patient_information_approved": True},
    )
    assert rel_res.status_code == 200
    assert rel_res.json()["workflow_state"] == "PATIENT_RELEASED"

    # 9. Patient Access & Verification
    pat_res = test_client.get(
        f"/patient/reports/{study_id}",
        headers=PATIENT_HEADERS,
    )
    assert pat_res.status_code == 200
    p_data = pat_res.json()
    assert p_data["study_id"] == study_id
    assert p_data["status"] == "RELEASED"
    assert p_data["data_mode"] == "DEMO"
    assert p_data["patient_explanation"]["summary"] == patient_exp["summary"]
    assert "Follow-up in clinic in 6 weeks" in p_data["approved_followup_info"]
