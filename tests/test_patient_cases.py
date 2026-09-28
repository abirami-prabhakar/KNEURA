import json
import pytest
from fastapi.testclient import TestClient
from patient_test_server import backend, seed_users
from backend.demo import create_demo_package

VALID = {'patientName': "  Demo O'Neil-Patient  ", 'patientAge': 42, 'patientGender': 'Female'}

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    seed_users()
    with TestClient(backend.app) as client:
        response = client.post('/api/auth/login', json={'email': 'radiologist@example.test', 'password': 'test-password', 'role': 'radiologist'})
        assert response.status_code == 200
        yield client


def create(client, **changes):
    return client.post('/api/cases', json=VALID | changes)


def test_persistence_and_audit(client):
    response = create(client)
    assert response.status_code == 201, response.text
    case = response.json()
    assert case['id'].startswith('KN-')
    assert case['patient']['name'] == "Demo O'Neil-Patient"
    assert case['patient']['age'] == 42
    assert case['patient']['gender'] == 'Female'
    with backend.db() as conn:
        stored = json.loads(conn.execute('SELECT document FROM cases WHERE id=?', (case['id'],)).fetchone()[0])
    assert stored == case
    assert client.get('/api/cases/' + case['id']).json()['patient'] == case['patient']
    assert client.get('/api/cases').json()[0]['patient'] == case['patient']
    assert "O'Neil" not in json.dumps(case['audit'])
    assert backend.verify_audit(case)

@pytest.mark.parametrize('field', ['patientName', 'patientAge', 'patientGender'])
def test_required(client, field):
    data = VALID.copy(); del data[field]
    assert client.post('/api/cases', json=data).status_code == 422
    assert client.get('/api/cases').json() == []

@pytest.mark.parametrize('age', [-1, 12.5, 121, '42', True, None])
def test_invalid_age(client, age):
    assert create(client, patientAge=age).status_code == 422

@pytest.mark.parametrize('name', ['', '   ', 'x' * 101, None])
def test_invalid_name(client, name):
    assert create(client, patientName=name).status_code == 422

@pytest.mark.parametrize('gender', ['', 'Unknown', None])
def test_invalid_gender(client, gender):
    assert create(client, patientGender=gender).status_code == 422

@pytest.mark.parametrize('age', [0, 120])
def test_age_boundaries(client, age):
    assert create(client, patientAge=age).status_code == 201


def test_idempotent_retry(client):
    headers = {'Idempotency-Key': 'same-submission'}
    first = client.post('/api/cases', json=VALID, headers=headers)
    second = client.post('/api/cases', json=VALID, headers=headers)
    assert first.json()['id'] == second.json()['id']
    assert len(client.get('/api/cases').json()) == 1
    assert client.post('/api/cases', json=VALID | {'patientAge': 43}, headers=headers).status_code == 409


def test_access_and_legacy(client):
    case = create(client).json()
    legacy = dict(case); legacy['id'] = 'KN-LEGACY'; legacy.pop('patient')
    legacy['audit'] = []; legacy.pop('auditChain', None)
    backend.save_case(legacy)
    assert client.get('/api/cases/KN-LEGACY').status_code == 200
    client.post('/api/auth/logout')
    assert create(client).status_code == 401
    for role in ['orthopedist', 'patient']:
        assert client.post('/api/auth/login', json={'email': role+'@example.test', 'password': 'test-password', 'role': role}).status_code == 200
        assert create(client).status_code == 403
        assert client.get('/api/cases/' + case['id']).status_code == 404
        assert client.post('/api/cases/' + case['id'] + '/study', files={'files': ('bad.dcm', b'bad')}).status_code == 403


def test_dicom_attachment_preserves_demographics(client, tmp_path):
    case = create(client).json()
    package = tmp_path / 'synthetic.zip'
    create_demo_package(package)
    with package.open('rb') as file:
        response = client.post('/api/cases/' + case['id'] + '/study', files={'files': ('synthetic.zip', file, 'application/zip')})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['id'] == case['id']
    for field in ['name', 'age', 'gender', 'patient_id']:
        assert updated['patient'][field] == case['patient'][field]
    assert updated['study']['patientName'] == case['patient']['name']
    assert updated['series']
    assert client.get('/api/cases/' + case['id']).json()['patient'] == updated['patient']
    assert client.post('/api/cases/' + case['id'] + '/study', files={'files': ('bad.dcm', b'bad')}).status_code == 409
    image_url = updated['series'][0]['images'][0]['url']
    assert client.get(image_url).status_code == 200


def test_failed_upload_can_retry(client):
    case = create(client).json()
    response = client.post('/api/cases/' + case['id'] + '/study', files={'files': ('bad.dcm', b'invalid')})
    assert response.status_code == 422
    assert client.get('/api/cases/' + case['id']).json()['patient'] == case['patient']
    assert not (backend.DATA / 'studies' / case['id']).exists()
