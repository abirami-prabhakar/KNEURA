from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app, get_db
from app.models.audit_log import AuditLog
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.study import Study


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    db.add(Study(study_id="test-study", workflow_state="AI_COMPLETE"))
    db.add_all(
        [
            Prediction(study_id="test-study", label="ACL", confidence=0.17),
            Prediction(study_id="test-study", label="MCL", confidence=0.63),
        ]
    )
    db.commit()
    db.close()

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


RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "radiologist-42",
    "X-User-Role": "RADIOLOGIST",
}


@pytest.mark.parametrize("decision", ["CONFIRMED", "REJECTED", "EDITED"])
def test_radiologist_can_submit_each_valid_review_decision(client, decision):
    response = client[0].post(
        "/studies/test-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": decision,
            "notes": "Reviewed against images.",
            "validated_findings": [
                {"finding": "ACL tear", "outcome": decision, "details": "Radiologist finding"}
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["study_id"] == "test-study"
    assert body["reviewer_id"] == "radiologist-42"
    assert body["decision"] == decision
    assert body["validated_findings"] == [
        {"finding": "ACL tear", "outcome": decision, "details": "Radiologist finding"}
    ]


def test_review_persists_validated_findings_and_does_not_change_ai_result(client):
    db = client[1]()
    before = [(row.label, row.confidence) for row in db.execute(
        select(Prediction).order_by(Prediction.id)
    ).scalars()]
    db.close()

    response = client[0].post(
        "/studies/test-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "EDITED",
            "validated_findings": [
                {"finding": "Complex medial meniscal tear", "outcome": "EDITED", "details": "Posterior horn"},
                {"finding": "Joint effusion", "outcome": "EDITED", "details": "Small"},
            ],
        },
    )
    assert response.status_code == 201

    db = client[1]()
    after = [(row.label, row.confidence) for row in db.execute(
        select(Prediction).order_by(Prediction.id)
    ).scalars()]
    review = db.execute(select(RadiologistReview)).scalar_one()
    findings = db.execute(select(ValidatedFinding).order_by(ValidatedFinding.id)).scalars().all()
    audit = db.execute(select(AuditLog).filter_by(action="RADIOLOGIST_REVIEW_SUBMITTED")).scalar_one()
    db.close()

    assert after == before
    assert review.study_id == "test-study"
    assert [(row.finding, row.outcome, row.details) for row in findings] == [
        ("Complex medial meniscal tear", "EDITED", "Posterior horn"),
        ("Joint effusion", "EDITED", "Small"),
    ]
    assert audit.action == "RADIOLOGIST_REVIEW_SUBMITTED"
    assert audit.actor_id == "radiologist-42"


def test_non_radiologist_is_rejected(client):
    response = client[0].post(
        "/studies/test-study/review",
        headers={"X-Authenticated-User-Id": "clinician-1", "X-User-Role": "CLINICIAN"},
        json={"decision": "CONFIRMED", "validated_findings": [{"finding": "ACL tear", "outcome": "CONFIRMED"}]},
    )
    assert response.status_code == 403


def test_unauthenticated_caller_is_rejected(client):
    response = client[0].post(
        "/studies/test-study/review",
        json={"decision": "CONFIRMED", "validated_findings": [{"finding": "ACL tear", "outcome": "CONFIRMED"}]},
    )
    assert response.status_code == 401


def test_nonexistent_study_is_rejected(client):
    response = client[0].post(
        "/studies/missing/review",
        headers=RADIOLOGIST_HEADERS,
        json={"decision": "CONFIRMED", "validated_findings": [{"finding": "ACL tear", "outcome": "CONFIRMED"}]},
    )
    assert response.status_code == 404


def test_invalid_review_decision_is_rejected(client):
    response = client[0].post(
        "/studies/test-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={"decision": "DIAGNOSED", "validated_findings": [{"finding": "ACL tear", "outcome": "DIAGNOSED"}]},
    )
    assert response.status_code == 422


def test_review_without_ai_predictions_is_rejected(client):
    db = client[1]()
    db.add(Study(study_id="study-without-predictions"))
    db.commit()
    db.close()

    response = client[0].post(
        "/studies/study-without-predictions/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "validated_findings": [
                {"finding": "ACL tear", "outcome": "CONFIRMED"}
            ],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "No AI result exists for this study."

    db = client[1]()
    reviews = db.execute(select(RadiologistReview).filter_by(study_id="study-without-predictions")).scalars().all()
    db.close()
    assert len(reviews) == 0


def test_decision_outcome_mismatch_is_rejected(client):
    db = client[1]()
    reviews_before = len(db.execute(select(RadiologistReview)).scalars().all())
    findings_before = len(db.execute(select(ValidatedFinding)).scalars().all())
    db.close()

    response = client[0].post(
        "/studies/test-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "validated_findings": [
                {
                    "finding": "ACL tear",
                    "outcome": "REJECTED",
                }
            ],
        },
    )
    assert response.status_code == 422

    db = client[1]()
    reviews_after = len(db.execute(select(RadiologistReview)).scalars().all())
    findings_after = len(db.execute(select(ValidatedFinding)).scalars().all())
    db.close()
    assert reviews_after == reviews_before
    assert findings_after == findings_before


def test_empty_validated_findings_is_rejected(client):
    db = client[1]()
    reviews_before = len(db.execute(select(RadiologistReview)).scalars().all())
    db.close()

    response = client[0].post(
        "/studies/test-study/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "validated_findings": [],
        },
    )
    assert response.status_code == 422

    db = client[1]()
    reviews_after = len(db.execute(select(RadiologistReview)).scalars().all())
    db.close()
    assert reviews_after == reviews_before

