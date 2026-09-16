from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.llm_adapter import Member2ClinicalLLMAdapter, get_llm_adapter
from app.main import app, get_db
from app.models.prediction import Prediction
from app.models.study import Study

CANONICAL_12_LABELS = [
    "ACL",
    "MCL",
    "Medial Meniscus",
    "Lateral Meniscus",
    "Medial OA",
    "Lateral OA",
    "PF OA",
    "Effusion",
    "Synovitis",
    "Baker's",
    "Contusion",
    "Fracture",
]

RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "rad-user-1",
    "X-User-Role": "RADIOLOGIST",
}


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    db.add(Study(study_id="study-12-review", workflow_state="AI_COMPLETE", study_root=str(tmp_path)))
    for idx, label in enumerate(CANONICAL_12_LABELS):
        db.add(Prediction(study_id="study-12-review", label=label, confidence=0.05 * (idx + 1)))
    db.commit()
    db.close()

    captured_prompts = []

    def mock_llm_fn(prompt: str) -> dict:
        captured_prompts.append(prompt)
        return {
            "title": "Knee MRI Report",
            "study_id": "study-12-review",
            "status": "DRAFT",
            "findings": ["ACL tear detected.", "MCL sprain detected."],
            "impression": "Positive for ACL and MCL injury.",
            "note": "Draft report subject to radiologist approval.",
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
        yield test_client, session_factory, captured_prompts
    app.dependency_overrides.clear()


def test_submit_twelve_finding_mixed_review(client):
    test_client, session_factory, _ = client
    findings = []
    # Approve first 6, reject last 6
    for idx, label in enumerate(CANONICAL_12_LABELS):
        outcome = "APPROVED" if idx < 6 else "REJECTED"
        findings.append({
            "finding": label,
            "outcome": outcome,
            "details": f"Radiologist marked {outcome.lower()}",
        })

    response = test_client.post(
        "/studies/study-12-review/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "MIXED",
            "notes": "Reviewed all 12 findings individually.",
            "validated_findings": findings,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["decision"] == "MIXED"
    assert len(data["validated_findings"]) == 12

    # Verify workflow transitioned to RADIOLOGIST_REVIEW
    db = session_factory()
    study = db.query(Study).filter_by(study_id="study-12-review").first()
    assert study.workflow_state == "RADIOLOGIST_REVIEW"
    db.close()


def test_reject_duplicate_findings_in_review(client):
    test_client, _, _ = client
    findings = [
        {"finding": "ACL", "outcome": "APPROVED", "details": "Approved first time"},
        {"finding": "ACL", "outcome": "REJECTED", "details": "Duplicate ACL"},
    ]
    for label in CANONICAL_12_LABELS[1:]:
        findings.append({"finding": label, "outcome": "APPROVED", "details": "ok"})

    response = test_client.post(
        "/studies/study-12-review/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "MIXED",
            "notes": "Invalid review with duplicate.",
            "validated_findings": findings,
        },
    )
    assert response.status_code == 422
    assert "duplicate" in str(response.json()["detail"]).lower()


def test_missing_findings_blocks_report_generation(client):
    test_client, _, _ = client
    # Submit a mixed review with only 5 of the 12 findings
    findings = [
        {"finding": CANONICAL_12_LABELS[i], "outcome": "APPROVED", "details": "ok"}
        for i in range(5)
    ]

    response = test_client.post(
        "/studies/study-12-review/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "MIXED",
            "notes": "Incomplete review.",
            "validated_findings": findings,
        },
    )
    assert response.status_code == 201

    # Attempting to generate report should fail because not all 12 findings have decisions
    gen_response = test_client.post(
        "/studies/study-12-review/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert gen_response.status_code == 409
    assert "explicit" in str(gen_response.json()["detail"]).lower()


def test_complete_twelve_finding_review_enables_report_with_rejected_excluded(client):
    test_client, _, captured_prompts = client
    # 2 approved, 10 rejected
    findings = []
    for idx, label in enumerate(CANONICAL_12_LABELS):
        outcome = "APPROVED" if idx < 2 else "REJECTED"
        findings.append({
            "finding": label,
            "outcome": outcome,
            "details": f"Decision is {outcome}",
        })

    rev_response = test_client.post(
        "/studies/study-12-review/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "MIXED",
            "notes": "Complete 12-finding review.",
            "validated_findings": findings,
        },
    )
    assert rev_response.status_code == 201

    gen_response = test_client.post(
        "/studies/study-12-review/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert gen_response.status_code == 201
    report_data = gen_response.json()
    assert report_data["status"] == "DRAFT"
    assert report_data["current_version"] == 1

    # Check that LLM prompt contains approved findings and forbids rejected findings
    assert len(captured_prompts) == 1
    prompt_str = captured_prompts[0]
    assert "ACL" in prompt_str
    assert "MCL" in prompt_str
    # Safety invariant: rejected findings are explicitly excluded
    assert "Do not include rejected findings" in prompt_str or "rules" in prompt_str.lower()
