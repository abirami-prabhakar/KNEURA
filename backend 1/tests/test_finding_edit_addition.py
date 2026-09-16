from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.llm_adapter import Member2ClinicalLLMAdapter, get_llm_adapter
from app.main import app, get_db
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.study import Study

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
    db.add(Study(study_id="study-edit-add", workflow_state="AI_COMPLETE", study_root=str(tmp_path)))
    db.add(Prediction(study_id="study-edit-add", label="ACL", confidence=0.25))
    db.commit()
    db.close()

    captured_prompts = []

    def mock_llm_fn(prompt: str) -> dict:
        captured_prompts.append(prompt)
        return {
            "title": "Knee MRI Report",
            "study_id": "study-edit-add",
            "status": "DRAFT",
            "findings": ["Incidental pes anserine bursitis."],
            "impression": "Pes anserine bursitis.",
            "note": "Draft.",
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


def test_edited_finding_preserves_underlying_ai_prediction(client):
    test_client, session_factory, _ = client

    # Radiologist edits the ACL finding
    response = test_client.post(
        "/studies/study-edit-add/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "EDITED",
            "notes": "Edited ACL to partial tear based on coronal view.",
            "validated_findings": [
                {
                    "finding": "ACL",
                    "outcome": "EDITED",
                    "details": "Partial thickness tear, low grade.",
                }
            ],
        },
    )
    assert response.status_code == 201

    # Verify predictions table remains completely unchanged
    db = session_factory()
    pred = db.query(Prediction).filter_by(study_id="study-edit-add", label="ACL").first()
    assert pred is not None
    assert pred.confidence == 0.25
    assert pred.label == "ACL"
    db.close()


def test_radiologist_added_finding_creates_no_fake_ai_probability(client):
    test_client, session_factory, _ = client

    # Radiologist adds an incidental finding: "Pes anserine bursitis"
    response = test_client.post(
        "/studies/study-edit-add/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Added incidental finding.",
            "validated_findings": [
                {
                    "finding": "Pes anserine bursitis",
                    "outcome": "CONFIRMED",
                    "details": "Mild fluid collection at pes anserine insertion.",
                    "is_radiologist_added": True,
                }
            ],
        },
    )
    assert response.status_code == 201

    db = session_factory()
    # Check ValidatedFinding has is_radiologist_added True
    vf = db.query(ValidatedFinding).filter_by(finding="Pes anserine bursitis").first()
    assert vf is not None
    assert vf.is_radiologist_added is True

    # Check predictions table has NO entry for "Pes anserine bursitis"
    fake_pred = db.query(Prediction).filter_by(study_id="study-edit-add", label="Pes anserine bursitis").first()
    assert fake_pred is None

    # Verify only original ACL prediction exists
    preds = db.query(Prediction).filter_by(study_id="study-edit-add").all()
    assert len(preds) == 1
    assert preds[0].label == "ACL"
    db.close()


def test_report_generation_with_radiologist_added_finding(client):
    test_client, _, captured_prompts = client

    test_client.post(
        "/studies/study-edit-add/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Incidental finding noted.",
            "validated_findings": [
                {
                    "finding": "Pes anserine bursitis",
                    "outcome": "CONFIRMED",
                    "details": "Fluid accumulation at tendon insertion.",
                    "is_radiologist_added": True,
                }
            ],
        },
    )

    gen_res = test_client.post(
        "/studies/study-edit-add/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert gen_res.status_code == 201
    assert gen_res.json()["status"] == "DRAFT"

    # Verify that the radiologist-added finding is included in clinical context
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "Pes anserine bursitis" in prompt
    assert "Fluid accumulation" in prompt
