from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
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
    "X-Authenticated-User-Id": "radiologist-1",
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
    db.add(Study(study_id="study-gradcam-test", workflow_state="AI_COMPLETE", study_root=str(tmp_path)))
    for idx, label in enumerate(CANONICAL_12_LABELS):
        db.add(Prediction(study_id="study-gradcam-test", label=label, confidence=0.1 * (idx + 1)))
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


def test_gradcam_route_exists(client):
    response = client[0].get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/ai/gradcam" in response.json()["paths"]


def test_gradcam_unauthenticated_rejected(client):
    test_client, _ = client
    response = test_client.post(
        "/api/v1/ai/gradcam",
        json={"study_id": "study-gradcam-test", "abnormality": "ACL"},
    )
    assert response.status_code == 401
    assert "authentication is required" in response.json()["detail"].lower()


@pytest.mark.parametrize("role", ["PATIENT", "ORTHOPEDIC", "ORTHOPEDIC_SURGEON", "NURSE", "CLINICIAN", "ADMIN"])
def test_gradcam_unauthorized_role_rejected(client, role):
    test_client, _ = client
    headers = {
        "X-Authenticated-User-Id": "user-other",
        "X-User-Role": role,
    }
    response = test_client.post(
        "/api/v1/ai/gradcam",
        headers=headers,
        json={"study_id": "study-gradcam-test", "abnormality": "ACL"},
    )
    assert response.status_code == 403
    assert "radiologist role is required" in response.json()["detail"].lower()


def test_gradcam_requires_known_study(client):
    response = client[0].post(
        "/api/v1/ai/gradcam",
        headers=RADIOLOGIST_HEADERS,
        json={"study_id": "nonexistent-study", "abnormality": "ACL"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.parametrize("label", CANONICAL_12_LABELS)
def test_gradcam_accepts_all_12_canonical_labels(client, label):
    test_client, session_factory = client
    
    mock_result = {
        "model_version": "KNEE-AI 3.3",
        "abnormality": label,
        "class_index": CANONICAL_12_LABELS.index(label),
        "probability": 0.85,
        "plane": "CORONAL",
        "series_instance_uid": "1.2.3.4",
        "window_index": 2,
        "instance_numbers": [1, 2, 3, 4, 5],
        "heatmap": [[0.1, 0.2], [0.3, 0.4]],
    }

    with patch("app.main.FrozenKneeAIAdapter.generate_gradcam", return_value=mock_result) as mock_gen:
        response = test_client.post(
            "/api/v1/ai/gradcam",
            headers=RADIOLOGIST_HEADERS,
            json={"study_id": "study-gradcam-test", "abnormality": label},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["abnormality"] == label
        assert data["model_version"] == "KNEE-AI 3.3"
        assert data["heatmap"] == [[0.1, 0.2], [0.3, 0.4]]
        assert data["class_index"] == CANONICAL_12_LABELS.index(label)
        assert data["probability"] == 0.85
        assert data["plane"] == "CORONAL"
        assert data["series_instance_uid"] == "1.2.3.4"
        assert data["window_index"] == 2
        assert data["instance_numbers"] == [1, 2, 3, 4, 5]
        mock_gen.assert_called_once()


def test_gradcam_rejects_invalid_class(client):
    test_client, _ = client
    response = test_client.post(
        "/api/v1/ai/gradcam",
        headers=RADIOLOGIST_HEADERS,
        json={"study_id": "study-gradcam-test", "abnormality": "Brain_Tumor"},
    )
    assert response.status_code == 422


def test_gradcam_preserves_prediction_probabilities(client):
    test_client, session_factory = client

    # Record initial predictions
    db = session_factory()
    initial_preds = {p.label: p.confidence for p in db.query(Prediction).filter_by(study_id="study-gradcam-test").all()}
    db.close()

    mock_result = {
        "model_version": "KNEE-AI 3.3",
        "abnormality": "ACL",
        "class_index": 0,
        "probability": 0.1,
        "plane": "CORONAL",
        "series_instance_uid": "1.2.3.4",
        "window_index": 0,
        "instance_numbers": [1, 2, 3, 4, 5],
        "heatmap": [],
    }

    with patch("app.main.FrozenKneeAIAdapter.generate_gradcam", return_value=mock_result):
        response = test_client.post(
            "/api/v1/ai/gradcam",
            headers=RADIOLOGIST_HEADERS,
            json={"study_id": "study-gradcam-test", "abnormality": "ACL"},
        )
        assert response.status_code == 200

    # Verify predictions in database are completely unchanged
    db = session_factory()
    final_preds = {p.label: p.confidence for p in db.query(Prediction).filter_by(study_id="study-gradcam-test").all()}
    db.close()

    assert initial_preds == final_preds
