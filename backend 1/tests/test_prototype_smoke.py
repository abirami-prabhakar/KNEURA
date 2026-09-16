"""Real DICOM/checkpoint end-to-end smoke; only the external Gemini SDK is mocked."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.authentication import hash_password
from app.database import Base
from app.main import app, get_db
from app.security import get_db as security_db
from app.models.user import User
from app.models.study import Study
from app.models.prediction import Prediction
from app.models.report import Report
from app.llm_adapter import CANONICAL_ABNORMALITIES

ROOT = Path(__file__).resolve().parents[2]


def test_real_prototype_workflow(tmp_path, monkeypatch):
    import torch
    from google import genai
    torch.set_num_threads(2)
    engine = create_engine(f"sqlite:///{tmp_path / 'kneura_demo.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    password = 'smoke-test-password-only'
    with factory() as db:
        for email, role in [('radiologist@kneura.local', 'RADIOLOGIST'), ('orthopedic@kneura.local', 'ORTHOPEDIC_SURGEON'), ('patient@kneura.local', 'PATIENT')]:
            db.add(User(email=email, role=role, password_hash=hash_password(password)))
        db.commit()

    sys.path.insert(0, str(ROOT / 'backend 1/scripts'))
    import load_demo_study
    monkeypatch.setattr(load_demo_study, 'engine', engine)
    monkeypatch.setattr(load_demo_study, 'SessionLocal', factory)
    load_demo_study.load_demo_studies(ROOT / 'demo_inputs', case=7)
    with factory() as db:
        uid = db.execute(select(Study.study_id)).scalar_one()
        assert not list(db.execute(select(Prediction)).scalars())

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[security_db] = database
    captured = []
    unsafe = [True]

    def generate_content(**kwargs):
        prompt = kwargs['contents']
        study_id = prompt.split('STUDY ID:\n', 1)[1].splitlines()[0]
        findings = ast.literal_eval(prompt.split('RADIOLOGIST-APPROVED FINDINGS:\n', 1)[1].splitlines()[0])
        captured.append(findings)
        assert {f['abnormality'] for f in findings} == {'Effusion', 'MCL'}
        assert all(f['status'] == 'APPROVED' for f in findings)
        assert uid not in prompt
        if 'patient-friendly explanation assistant' in prompt:
            result = {'title': 'Patient-Friendly MRI Explanation', 'study_id': study_id,
                      'approved_findings': 'Effusion and MCL changes.', 'what_this_means': 'Explanation of clinician-approved information.',
                      'important_note': 'Discuss your results with your doctor.'}
        else:
            result = {'title': 'Knee MRI Report', 'study_id': study_id, 'status': 'DRAFT',
                      'findings': ['Effusion.', 'MCL changes.'], 'impression': 'Effusion and MCL changes.',
                      'note': 'Requires radiologist review and final approval.'}
        if unsafe[0]:
            result['extra'] = 'ACL tear.'
        return SimpleNamespace(text=json.dumps(result))

    monkeypatch.setenv('GEMINI_API_KEY', 'test-sdk-key-never-sent')
    monkeypatch.setattr(genai, 'Client', lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    try:
        with TestClient(app) as client:
            assert client.get('/health').status_code == 200
            page = client.get('/')
            assert page.status_code == 200 and 'text/html' in page.headers['content-type']
            assert 'data-patient-explanation' in page.text
            assert client.get('/studies').status_code == 401
            assert client.post('/login', json={'email': 'radiologist@kneura.local', 'password': 'wrong'}).status_code == 401
            def login(email):
                response = client.post('/login', json={'email': email, 'password': password})
                assert response.status_code == 200
                return {'Authorization': f"Bearer {response.json()['access_token']}"}
            radio, ortho, patient = [login(f'{role}@kneura.local') for role in ('radiologist', 'orthopedic', 'patient')]
            assert client.get('/studies', headers=radio).status_code == 200
            assert client.post(f'/studies/{uid}/generate-report', headers=patient).status_code == 403
            assert client.post(f'/studies/{uid}/generate-report', headers=radio).status_code == 409
            response = client.post('/api/v1/ai/analyze', headers=radio, json={'study_id': uid, 'action': 'ANALYZE_KNEE_MRI'})
            assert response.status_code == 200, response.text
            ai = response.json()
            assert list(ai['probabilities']) == CANONICAL_ABNORMALITIES
            ref = pd.read_csv(ROOT / 'demo_inputs/REFERENCE_AI_INFERENCE.csv', float_precision='round_trip').set_index('StudyInstanceUID').loc[uid]
            assert ai['windows_evaluated'] == int(ref.windows_evaluated)
            assert max(abs(ai['probabilities'][label] - float(ref[label])) for label in CANONICAL_ABNORMALITIES) <= 1e-6
            with factory() as db:
                assert {p.label: p.confidence for p in db.execute(select(Prediction)).scalars()} == ai['probabilities']
            decisions = [{'finding': label, 'outcome': 'CONFIRMED' if label == 'Effusion' else 'EDITED' if label == 'MCL' else 'REJECTED',
                          'details': 'MCL changes reviewed for this software demonstration.' if label == 'MCL' else None}
                         for label in CANONICAL_ABNORMALITIES]
            # Test decisions are explicit software fixtures, never inferred from probabilities or ground truth.
            review = {'decision': 'MIXED', 'validated_findings': decisions}
            assert client.post(f'/studies/{uid}/review', headers=radio, json=dict(review, validated_findings=decisions[:1])).status_code == 422
            assert client.post(f'/studies/{uid}/review', headers=radio, json=review).status_code == 201
            assert client.post(f'/studies/{uid}/generate-report', headers=radio).status_code == 503
            with factory() as db:
                assert not list(db.execute(select(Report)).scalars())
            unsafe[0] = False
            response = client.post(f'/studies/{uid}/generate-report', headers=radio)
            assert response.status_code == 201, response.text
            report_id = response.json()['report_id']
            draft = json.loads(response.json()['draft_content'])
            assert draft['status'] == 'DRAFT' and draft['final_approval'] == 'PENDING'
            explanation = client.post(f'/studies/{uid}/patient-explanation', headers=radio)
            assert explanation.status_code == 200, explanation.text
            detail = client.get(f'/studies/{uid}', headers=radio).json()
            assert detail['report']['patient_explanation']
            assert detail['report']['status'] == 'DRAFT'
            assert client.get(f'/patient/reports/{uid}', headers=patient).status_code == 403
            assert client.post(f'/reports/{report_id}/approve', headers=radio, json={}).status_code == 200
            assert client.post(f'/studies/{uid}/patient-release', headers=ortho, json={}).status_code == 409
            response = client.post(f'/orthopedic/{uid}/review', headers=ortho, json={
                'assessment': 'Software demonstration review.', 'recommendation': 'Discuss with your doctor.',
                'patient_information_approved': True, 'approved_followup_info': 'Clinician-approved demonstration information.'})
            assert response.status_code == 201, response.text
            assert client.post(f'/studies/{uid}/patient-release', headers=ortho, json={}).status_code == 200
            released = client.get(f'/patient/reports/{uid}', headers=patient)
            assert released.status_code == 200 and released.json()['patient_explanation']
            assert len(captured) == 3
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
