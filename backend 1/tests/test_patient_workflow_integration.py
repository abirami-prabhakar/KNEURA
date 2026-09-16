import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.llm_adapter import LLMIntegrationError, Member2ClinicalLLMAdapter, get_llm_adapter
from app.main import app, get_db
from app.models.orthopedic_review import OrthopedicReview
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview
from app.models.report import Report
from app.models.study import Study

RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "rad-dr-smith",
    "X-User-Role": "RADIOLOGIST",
}

ORTHOPEDIC_HEADERS = {
    "X-Authenticated-User-Id": "ortho-dr-jones",
    "X-User-Role": "ORTHOPEDIC_SURGEON",
}

RELEASE_HEADERS = {
    "X-Authenticated-User-Id": "ortho-dr-jones",
    "X-User-Role": "ORTHOPEDIC_SURGEON",
}

PATIENT_HEADERS = {
    "X-Authenticated-User-Id": "patient-101",
    "X-User-Role": "PATIENT",
}


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    db.add(
        Study(
            study_id="study-patient-flow",
            patient_id="patient-101",
            workflow_state="AI_COMPLETE",
            data_mode="CLINICAL",
            study_root=str(tmp_path),
        )
    )
    db.add(Prediction(study_id="study-patient-flow", label="ACL", confidence=0.82))
    db.commit()
    db.close()

    def mock_llm_fn(prompt: str) -> dict:
        return {
            "title": "Knee MRI Report",
            "study_id": "study-patient-flow",
            "status": "DRAFT",
            "findings": ["Complete ACL tear."],
            "impression": "ACL tear.",
            "note": "Initial draft.",
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
        yield test_client, session_factory
    app.dependency_overrides.clear()


def _setup_approved_study(test_client):
    test_client.post(
        "/studies/study-patient-flow/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Confirmed ACL tear.",
            "validated_findings": [
                {"finding": "ACL", "outcome": "CONFIRMED", "details": "Confirmed ACL tear."}
            ],
        },
    )
    rep_res = test_client.post(
        "/studies/study-patient-flow/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    report_id = rep_res.json()["report_id"]
    test_client.post(f"/reports/{report_id}/approve", headers=RADIOLOGIST_HEADERS)
    return report_id


def test_study_mode_endpoint(client):
    test_client, _ = client
    res = test_client.get("/studies/study-patient-flow/mode")
    assert res.status_code == 200
    data = res.json()
    assert data["study_id"] == "study-patient-flow"
    assert data["data_mode"] == "CLINICAL"


def test_patient_explanation_generation_and_safety_validator(client):
    test_client, session_factory = client
    report_id = _setup_approved_study(test_client)

    valid_explanation = {
        "summary": "Your MRI shows a tear in the anterior cruciate ligament (ACL), a key stabilizing ligament in your knee.",
        "findings_explained": [
            {
                "finding": "ACL tear",
                "plain_english": "The main ligament in the center of your knee is torn.",
                "what_it_means": "This may cause knee instability or swelling.",
            }
        ],
        "next_steps": "Please discuss these results with your orthopedic doctor to review treatment options.",
        "disclaimer": "This summary is for informational purposes only. Please consult your physician.",
    }

    with patch("app.llm_adapter.Member2ClinicalLLMAdapter.generate_patient_explanation", return_value=valid_explanation) as mock_pe:
        res = test_client.post(
            "/studies/study-patient-flow/patient-explanation",
            headers=RADIOLOGIST_HEADERS,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["study_id"] == "study-patient-flow"
        assert "summary" in data["patient_explanation"]
        mock_pe.assert_called_once()

    # Verify saved on report in database
    db = session_factory()
    rep = db.query(Report).filter_by(id=report_id).first()
    assert rep.patient_explanation is not None
    saved = json.loads(rep.patient_explanation)
    assert saved["summary"] == valid_explanation["summary"]
    db.close()


def test_patient_explanation_fails_safely_when_llm_unavailable(client):
    test_client, _ = client
    _setup_approved_study(test_client)

    with patch("app.llm_adapter.Member2ClinicalLLMAdapter.generate_patient_explanation", side_effect=LLMIntegrationError("Gemini API service unavailable")):
        res = test_client.post(
            "/studies/study-patient-flow/patient-explanation",
            headers=RADIOLOGIST_HEADERS,
        )
        assert res.status_code == 503
        assert "unavailable" in res.json()["detail"].lower()


def test_orthopedic_review_records_patient_approval(client):
    test_client, session_factory = client
    _setup_approved_study(test_client)

    ortho_res = test_client.post(
        "/orthopedic/study-patient-flow/review",
        headers=ORTHOPEDIC_HEADERS,
        json={
            "assessment": "Right knee ACL tear, indicated for reconstructive surgery.",
            "recommendation": "Surgical reconstruction with hamstring autograft.",
            "notes": "Patient advised on prehab.",
            "patient_information_approved": True,
            "approved_followup_info": "Follow-up in orthopedic clinic in 2 weeks with prehab completed.",
        },
    )
    assert ortho_res.status_code == 201
    data = ortho_res.json()
    assert data["patient_information_approved"] is True
    assert "prehab" in data["approved_followup_info"]

    db = session_factory()
    orev = db.query(OrthopedicReview).filter_by(study_id="study-patient-flow").first()
    assert orev.patient_information_approved is True
    assert orev.approved_followup_info == "Follow-up in orthopedic clinic in 2 weeks with prehab completed."
    db.close()


def test_release_blocked_when_patient_info_not_approved(client):
    test_client, session_factory = client
    _setup_approved_study(test_client)

    # Orthopedic marks patient info NOT approved
    test_client.post(
        "/orthopedic/study-patient-flow/review",
        headers=ORTHOPEDIC_HEADERS,
        json={
            "assessment": "Complex injury needing further MDT review.",
            "recommendation": "Hold patient release pending MDT discussion.",
            "patient_information_approved": False,
        },
    )

    # Attempt patient release with payload saying false
    rel_res = test_client.post(
        "/studies/study-patient-flow/patient-release",
        headers=RELEASE_HEADERS,
        json={"patient_information_approved": False},
    )
    assert rel_res.status_code == 409
    assert "approval" in rel_res.json()["detail"].lower()


def test_payload_cannot_override_persisted_false_to_true(client):
    test_client, session_factory = client
    _setup_approved_study(test_client)

    # Persisted orthopedic review has patient_information_approved = False
    test_client.post(
        "/orthopedic/study-patient-flow/review",
        headers=ORTHOPEDIC_HEADERS,
        json={
            "assessment": "High risk findings.",
            "recommendation": "Do not release to patient directly.",
            "patient_information_approved": False,
        },
    )

    # Malicious or erroneous release request attempts to override by sending True
    rel_res = test_client.post(
        "/studies/study-patient-flow/patient-release",
        headers=RELEASE_HEADERS,
        json={"patient_information_approved": True},
    )
    # MUST STILL BE REJECTED with 409
    assert rel_res.status_code == 409
    assert "approval" in rel_res.json()["detail"].lower()


def test_release_blocked_when_persisted_approval_absent(client):
    test_client, session_factory = client
    _setup_approved_study(test_client)

    # Manually set patient_information_approved = None in the database to simulate absent/corrupt approval
    test_client.post(
        "/orthopedic/study-patient-flow/review",
        headers=ORTHOPEDIC_HEADERS,
        json={
            "assessment": "Pending evaluation.",
            "recommendation": "Follow up.",
            "patient_information_approved": True,
        },
    )
    db = session_factory()
    orev = db.query(OrthopedicReview).filter_by(study_id="study-patient-flow").first()
    orev.patient_information_approved = None
    db.commit()
    db.close()

    # Attempt patient release
    rel_res = test_client.post(
        "/studies/study-patient-flow/patient-release",
        headers=RELEASE_HEADERS,
    )
    assert rel_res.status_code == 409
    assert "approval" in rel_res.json()["detail"].lower()


def test_end_to_end_patient_release_and_consumption(client):
    test_client, session_factory = client
    report_id = _setup_approved_study(test_client)

    # 1. Generate patient explanation
    explanation = {
        "summary": "Your right knee shows an ACL tear.",
        "findings_explained": [{"finding": "ACL tear", "plain_english": "Torn ligament"}],
        "next_steps": "Follow up with ortho.",
    }
    with patch("app.llm_adapter.Member2ClinicalLLMAdapter.generate_patient_explanation", return_value=explanation):
        test_client.post(
            "/studies/study-patient-flow/patient-explanation",
            headers=RADIOLOGIST_HEADERS,
        )

    # 2. Orthopedic review with patient approval
    test_client.post(
        "/orthopedic/study-patient-flow/review",
        headers=ORTHOPEDIC_HEADERS,
        json={
            "assessment": "Surgical candidate.",
            "recommendation": "ACL reconstruction.",
            "patient_information_approved": True,
            "approved_followup_info": "Keep knee immobilized, ice 20 min TID.",
        },
    )

    # 3. Release to patient
    rel_res = test_client.post(
        "/studies/study-patient-flow/patient-release",
        headers=RELEASE_HEADERS,
        json={"patient_information_approved": True},
    )
    assert rel_res.status_code == 200
    assert rel_res.json()["workflow_state"] == "PATIENT_RELEASED"

    # 4. Patient fetches release reports
    pat_res = test_client.get(
        "/patient/reports",
        headers=PATIENT_HEADERS,
    )
    assert pat_res.status_code == 200
    reports = pat_res.json()
    assert len(reports) == 1
    report = reports[0]
    assert report["study_id"] == "study-patient-flow"
    assert report["status"] == "RELEASED"
    assert report["data_mode"] == "CLINICAL"
    assert report["approved_followup_info"] == "Keep knee immobilized, ice 20 min TID."
    assert report["patient_explanation"]["summary"] == "Your right knee shows an ACL tear."

    # Verify data minimization: patient report does not include internal prediction probabilities
    assert "probabilities" not in report
    assert "confidence" not in report


def test_patient_ownership_isolation_preserved(client):
    test_client, session_factory = client
    report_id = _setup_approved_study(test_client)

    # Complete orthopedic review with approval
    test_client.post(
        "/orthopedic/study-patient-flow/review",
        headers=ORTHOPEDIC_HEADERS,
        json={
            "assessment": "OK",
            "recommendation": "OK",
            "patient_information_approved": True,
        },
    )
    # Release to patient
    test_client.post(
        "/studies/study-patient-flow/patient-release",
        headers=RELEASE_HEADERS,
    )

    # Patient B attempts to access Patient A's released report
    patient_b_headers = {
        "X-Authenticated-User-Id": "patient-999-intruder",
        "X-User-Role": "PATIENT",
    }
    unauthorized_res = test_client.get(
        "/patient/reports/study-patient-flow",
        headers=patient_b_headers,
    )
    assert unauthorized_res.status_code == 403
    assert "forbidden" in unauthorized_res.json()["detail"].lower()

