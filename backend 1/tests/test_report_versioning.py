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
from app.models.report import Report, ReportVersion
from app.models.study import Study

RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "rad-doctor-1",
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
    db.add(Study(study_id="study-version-test", workflow_state="AI_COMPLETE", study_root=str(tmp_path)))
    db.add(Prediction(study_id="study-version-test", label="ACL", confidence=0.88))
    db.commit()
    db.close()

    def mock_llm_fn(prompt: str) -> dict:
        return {
            "title": "Knee MRI Report",
            "study_id": "study-version-test",
            "status": "DRAFT",
            "findings": ["ACL tear identified."],
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


def test_draft_generates_version_one(client):
    test_client, session_factory = client

    test_client.post(
        "/studies/study-version-test/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Confirmed.",
            "validated_findings": [
                {"finding": "ACL", "outcome": "CONFIRMED", "details": "ok"}
            ],
        },
    )

    res = test_client.post(
        "/studies/study-version-test/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["current_version"] == 1
    report_id = data["report_id"]

    db = session_factory()
    versions = db.query(ReportVersion).filter_by(report_id=report_id).all()
    assert len(versions) == 1
    assert versions[0].version_number == 1
    assert "ACL tear" in versions[0].content
    assert versions[0].status == "DRAFT"
    db.close()


def test_edit_creates_immutable_new_version(client):
    test_client, session_factory = client

    # Step 1: Create Review & Initial Report (v1)
    test_client.post(
        "/studies/study-version-test/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Confirmed.",
            "validated_findings": [
                {"finding": "ACL", "outcome": "CONFIRMED", "details": "ok"}
            ],
        },
    )
    res1 = test_client.post(
        "/studies/study-version-test/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    report_id = res1.json()["report_id"]
    original_v1_content = res1.json()["draft_content"]

    # Step 2: Edit report to produce v2
    res2 = test_client.put(
        f"/reports/{report_id}",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": "Version 2 edited content"},
    )
    assert res2.status_code == 200
    assert res2.json()["current_version"] == 2

    # Step 3: Edit report to produce v3
    res3 = test_client.put(
        f"/reports/{report_id}",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": "Version 3 finalized content"},
    )
    assert res3.status_code == 200
    assert res3.json()["current_version"] == 3

    # Step 4: Verify in database that all three versions exist and v1/v2 are intact
    db = session_factory()
    v1 = db.query(ReportVersion).filter_by(report_id=report_id, version_number=1).first()
    v2 = db.query(ReportVersion).filter_by(report_id=report_id, version_number=2).first()
    v3 = db.query(ReportVersion).filter_by(report_id=report_id, version_number=3).first()

    assert v1 is not None and v1.content == original_v1_content
    assert v2 is not None and v2.content == "Version 2 edited content"
    assert v3 is not None and v3.content == "Version 3 finalized content"
    assert v1.status == "DRAFT"
    assert v2.status == "DRAFT"
    assert v3.status == "DRAFT"
    db.close()


def test_approve_tracks_approved_version_number(client):
    test_client, session_factory = client

    test_client.post(
        "/studies/study-version-test/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Confirmed.",
            "validated_findings": [
                {"finding": "ACL", "outcome": "CONFIRMED", "details": "ok"}
            ],
        },
    )
    res1 = test_client.post(
        "/studies/study-version-test/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    report_id = res1.json()["report_id"]

    test_client.put(
        f"/reports/{report_id}",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": "V2 Content for approval"},
    )

    app_res = test_client.post(
        f"/reports/{report_id}/approve",
        headers=RADIOLOGIST_HEADERS,
    )
    assert app_res.status_code == 200
    app_data = app_res.json()
    assert app_data["status"] == "APPROVED"
    assert app_data["current_version"] == 2
    assert app_data["approved_version"] == 2

    # Verify versions table reflects approval
    db = session_factory()
    v1 = db.query(ReportVersion).filter_by(report_id=report_id, version_number=1).first()
    v2 = db.query(ReportVersion).filter_by(report_id=report_id, version_number=2).first()
    assert v1.status == "DRAFT"
    assert v2.status == "APPROVED"
    db.close()


def test_get_report_versions_endpoint(client):
    test_client, _ = client

    test_client.post(
        "/studies/study-version-test/review",
        headers=RADIOLOGIST_HEADERS,
        json={
            "decision": "CONFIRMED",
            "notes": "Confirmed.",
            "validated_findings": [
                {"finding": "ACL", "outcome": "CONFIRMED", "details": "ok"}
            ],
        },
    )
    res = test_client.post(
        "/studies/study-version-test/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    report_id = res.json()["report_id"]

    test_client.put(
        f"/reports/{report_id}",
        headers=RADIOLOGIST_HEADERS,
        json={"draft_content": "Second iteration"},
    )

    # Fetch version history
    v_res = test_client.get(
        f"/reports/{report_id}/versions",
        headers=RADIOLOGIST_HEADERS,
    )
    assert v_res.status_code == 200
    versions = v_res.json()
    assert len(versions) == 2
    assert versions[0]["version_number"] == 1
    assert versions[1]["version_number"] == 2
    assert versions[1]["content"] == "Second iteration"

    # 404 for unknown report
    v_404 = test_client.get("/reports/999999/versions", headers=RADIOLOGIST_HEADERS)
    assert v_404.status_code == 404
