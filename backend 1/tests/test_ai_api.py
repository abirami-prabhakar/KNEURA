from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.ai_adapter import FrozenKneeAIAdapter
from app.database import Base
from app.main import app, get_db
from app.models.prediction import Prediction
from app.models.study import Study


LABELS = [
    "ACL", "MCL", "Medial Meniscus", "Lateral Meniscus", "Medial OA",
    "Lateral OA", "PF OA", "Effusion", "Synovitis", "Baker's",
    "Contusion", "Fracture",
]


@pytest.fixture()
def client(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    db.add(Study(study_id="test-study"))
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


def _frozen_result() -> dict:
    return {
        "study": {"study_id": "test-study", "series_evaluated": 3, "windows_evaluated": 44},
        "model": {"name": "KNEE-AI 3.3", "architecture": "StandaloneFiveSliceEfficientNet"},
        "probabilities": {label: index / 100.0 for index, label in enumerate(LABELS)},
    }


def test_openapi_is_available(client):
    response = client[0].get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/ai/analyze" in response.json()["paths"]


def test_analyze_requires_known_study(client):
    response = client[0].post("/api/v1/ai/analyze", json={"study_id": "missing", "action": "ANALYZE_KNEE_MRI"})
    assert response.status_code == 404


def test_analyze_rejects_invalid_action(client):
    response = client[0].post("/api/v1/ai/analyze", json={"study_id": "test-study", "action": "DIAGNOSE"})
    assert response.status_code == 422


def test_analyze_preserves_all_frozen_outputs_and_persists_them(client, monkeypatch):
    monkeypatch.setattr(FrozenKneeAIAdapter, "analyze", lambda _self, _study: _frozen_result())
    response = client[0].post("/api/v1/ai/analyze", json={"study_id": "test-study", "action": "ANALYZE_KNEE_MRI"})
    assert response.status_code == 200
    body = response.json()
    assert list(body["probabilities"]) == LABELS
    assert len(body["probabilities"]) == 12
    assert body["windows_evaluated"] == 44
    assert body["requires_radiologist_review"] is True
    assert "diagnosis" not in body

    db = client[1]()
    rows = db.execute(select(Prediction).order_by(Prediction.id)).scalars().all()
    db.close()
    assert [row.label for row in rows] == LABELS
    assert [row.confidence for row in rows] == [index / 100.0 for index in range(12)]


def test_missing_ai_assets_return_controlled_error(client, monkeypatch):
    from app.ai_adapter import AIIntegrationError
    monkeypatch.setattr(FrozenKneeAIAdapter, "analyze", lambda _self, _study: (_ for _ in ()).throw(AIIntegrationError("MRI study root is not configured or unavailable.")))
    response = client[0].post("/api/v1/ai/analyze", json={"study_id": "test-study", "action": "ANALYZE_KNEE_MRI"})
    assert response.status_code == 503
    assert response.json()["detail"] == "MRI study root is not configured or unavailable."


def test_invalid_frozen_probability_result_returns_controlled_error(client, monkeypatch):
    from app.ai_adapter import AIIntegrationError

    monkeypatch.setattr(
        FrozenKneeAIAdapter,
        "analyze",
        lambda _self, _study: (_ for _ in ()).throw(
            AIIntegrationError("Frozen KNEE-AI returned probabilities outside the valid range.")
        ),
    )
    response = client[0].post(
        "/api/v1/ai/analyze",
        json={"study_id": "test-study", "action": "ANALYZE_KNEE_MRI"},
    )
    assert response.status_code == 503
    assert "outside the valid range" in response.json()["detail"]
