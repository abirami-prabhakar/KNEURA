from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.llm_adapter import (
    LLMIntegrationError,
    Member2ClinicalLLMAdapter,
    get_llm_adapter,
)
from app.main import app, get_db
from app.models.audit_log import AuditLog
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.report import Report
from app.models.study import Study


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    # 1. Fully reviewed study with validated findings
    db.add(Study(study_id="test-study", workflow_state="RADIOLOGIST_REVIEW"))
    db.add_all(
        [
            Prediction(study_id="test-study", label="ACL", confidence=0.17),
            Prediction(study_id="test-study", label="MCL", confidence=0.63),
            Prediction(study_id="test-study", label="Effusion", confidence=0.45),
        ]
    )
    review = RadiologistReview(
        study_id="test-study",
        reviewer_id="radiologist-42",
        decision="CONFIRMED",
        notes="Slight joint effusion noted.",
    )
    db.add(review)
    db.flush()
    db.add_all(
        [
            ValidatedFinding(
                review_id=review.id,
                finding="ACL tear",
                outcome="CONFIRMED",
                details="Complete tear of anterior cruciate ligament",
            ),
            ValidatedFinding(
                review_id=review.id,
                finding="Effusion",
                outcome="CONFIRMED",
                details="Moderate effusion",
            ),
        ]
    )

    # 2. Study with AI predictions but NO radiologist review
    db.add(Study(study_id="study-no-review", workflow_state="AI_COMPLETE"))
    db.add(Prediction(study_id="study-no-review", label="ACL", confidence=0.88))

    # 3. Study with review but NO validated findings
    db.add(Study(study_id="study-no-findings", workflow_state="RADIOLOGIST_REVIEW"))
    review_empty = RadiologistReview(
        study_id="study-no-findings",
        reviewer_id="radiologist-42",
        decision="CONFIRMED",
    )
    db.add(review_empty)

    db.commit()
    db.close()

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def mock_llm_fn(prompt: str) -> dict:
        return {
            "title": "Knee MRI Report",
            "study_id": "test-study",
            "status": "DRAFT",
            "findings": [
                "ACL tear detected.",
                "Effusion detected.",
            ],
            "impression": "ACL tear and Effusion.",
            "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
        }

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(generate_llm_fn=mock_llm_fn)
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()


RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "radiologist-42",
    "X-User-Role": "RADIOLOGIST",
}


def test_successful_draft_report_generation(client):
    response = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["study_id"] == "test-study"
    assert body["status"] == "DRAFT"
    assert "ACL tear" in body["draft_content"]
    assert "Effusion" in body["draft_content"]
    assert "DRAFT" in body["draft_content"]


def test_generated_report_persisted_as_draft_in_database(client):
    response = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    report_id = response.json()["report_id"]

    db = client[1]()
    report = db.execute(select(Report).filter_by(id=report_id)).scalar_one()
    db.close()

    assert report.study_id == "test-study"
    assert report.author_id == "radiologist-42"
    assert report.status == "DRAFT"
    assert "ACL tear" in report.draft_content


def test_no_report_generation_without_radiologist_review(client):
    response = client[0].post(
        "/studies/study-no-review/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "No radiologist review exists for this study."

    db = client[1]()
    reports = db.execute(select(Report).filter_by(study_id="study-no-review")).scalars().all()
    db.close()
    assert len(reports) == 0


def test_no_report_generation_without_validated_findings(client):
    response = client[0].post(
        "/studies/study-no-findings/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "No validated findings exist for this study."

    db = client[1]()
    reports = db.execute(select(Report).filter_by(study_id="study-no-findings")).scalars().all()
    db.close()
    assert len(reports) == 0


def test_nonexistent_study_returns_404(client):
    response = client[0].post(
        "/studies/missing-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Study was not found."


def test_non_radiologist_is_rejected(client):
    response = client[0].post(
        "/studies/test-study/generate-report",
        headers={"X-Authenticated-User-Id": "clinician-1", "X-User-Role": "CLINICIAN"},
    )
    assert response.status_code == 403


def test_unauthenticated_caller_is_rejected(client):
    response = client[0].post("/studies/test-study/generate-report")
    assert response.status_code == 401


def test_llm_receives_validated_findings_only_and_no_ai_probabilities(client):
    received_calls = []

    class SpyLLMAdapter(Member2ClinicalLLMAdapter):
        def generate_report(self, study_id, validated_findings, predictions, clinical_context=None, **boundary_context):
            received_calls.append({
                "study_id": study_id,
                "findings": [
                    {"finding": f.finding, "outcome": f.outcome, "details": f.details}
                    for f in validated_findings
                ],
                "predictions": [
                    {"label": p.label, "confidence": p.confidence}
                    for p in predictions
                ],
                "clinical_context": clinical_context,
            })
            return super().generate_report(study_id, validated_findings, predictions, clinical_context, **boundary_context)

    app.dependency_overrides[get_llm_adapter] = lambda: SpyLLMAdapter(
        generate_llm_fn=lambda _prompt: {
            "title": "Knee MRI Report",
            "study_id": "test-study",
            "status": "DRAFT",
            "findings": [
                "ACL tear detected.",
                "Effusion detected.",
            ],
            "impression": "ACL tear and Effusion.",
            "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
        }
    )

    response = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    assert len(received_calls) == 1

    call = received_calls[0]
    assert call["study_id"] == "test-study"
    assert call["clinical_context"] == "Slight joint effusion noted."
    findings = call["findings"]
    assert len(findings) == 2
    assert findings[0]["finding"] == "ACL tear"
    assert findings[0]["outcome"] == "CONFIRMED"
    assert findings[1]["finding"] == "Effusion"
    assert findings[1]["outcome"] == "CONFIRMED"


def test_original_prediction_rows_remain_immutable(client):
    db = client[1]()
    before = [
        (row.id, row.study_id, row.label, row.confidence)
        for row in db.execute(select(Prediction).order_by(Prediction.id)).scalars()
    ]
    db.close()

    response = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201

    db = client[1]()
    after = [
        (row.id, row.study_id, row.label, row.confidence)
        for row in db.execute(select(Prediction).order_by(Prediction.id)).scalars()
    ]
    db.close()

    assert after == before


def test_llm_failure_does_not_create_any_report(client):
    class FailingLLMAdapter(Member2ClinicalLLMAdapter):
        def generate_report(self, study_id, validated_findings, predictions, clinical_context=None, **boundary_context):
            raise LLMIntegrationError("LLM upstream provider timeout.")

    app.dependency_overrides[get_llm_adapter] = lambda: FailingLLMAdapter()

    response = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "LLM upstream provider timeout" in response.json()["detail"]

    # Verify no report was persisted in the database
    db = client[1]()
    reports = db.execute(select(Report)).scalars().all()
    db.close()
    assert len(reports) == 0


def test_audit_log_created_for_draft_report(client):
    response = client[0].post(
        "/studies/test-study/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    report_id = response.json()["report_id"]

    db = client[1]()
    audit = db.execute(
        select(AuditLog).filter_by(action="DRAFT_REPORT_GENERATED")
    ).scalar_one()
    db.close()

    assert audit.actor_id == "radiologist-42"
    assert audit.study_id == "test-study"
    assert f"report_id={report_id}" in audit.details
    assert "status=DRAFT" in audit.details
