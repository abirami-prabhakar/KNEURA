"""Current one-step multipart upload contract, using synthetic DICOM only."""
import json
import pytest
from fastapi.testclient import TestClient
from patient_test_server import backend, seed_users
from backend.demo import create_demo_package

VALID = {'patient_name': "  Demo O'Neil-Patient  ", 'patient_age': '42', 'patient_gender': 'Female'}

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    seed_users()
    with TestClient(backend.app) as client:
        assert client.post('/api/auth/login', json={'email': 'radiologist@example.test', 'password': 'test-password', 'role': 'radiologist'}).status_code == 200
        yield client

@pytest.fixture
def package(tmp_path):
    path = tmp_path / 'synthetic.zip'
    create_demo_package(path)
    return path.read_bytes()

def upload(client, package, data=None):
    return client.post('/api/cases', data=VALID if data is None else data,
                       files={'files': ('synthetic.zip', package, 'application/zip')})

def test_persistence_demographics_and_audit(client, package):
    response = upload(client, package)
    assert response.status_code == 200, response.text
    case = response.json()
    assert case['patient']['name'] == "Demo O'Neil-Patient"
    assert case['patient']['age'] == 42
    assert case['patient']['gender'] == 'Female'
    assert case['study']['patientName'] == case['patient']['name']
    assert case['patient']['patient_id'] == case['study']['patientId']
    assert case['series']
    with backend.db() as conn:
        stored = json.loads(conn.execute('SELECT document FROM cases WHERE id=?', (case['id'],)).fetchone()[0])
    assert stored == case
    assert client.get('/api/cases/' + case['id']).json()['patient'] == case['patient']
    assert client.get('/api/cases').json()[0]['patient'] == case['patient']
    assert "O'Neil" not in json.dumps(case['audit'])
    assert backend.verify_audit(case)['valid']
    assert client.get(case['series'][0]['images'][0]['url']).status_code == 200

@pytest.mark.parametrize('field', list(VALID))
def test_partial_demographics_rejected(client, package, field):
    data = VALID.copy(); del data[field]
    assert upload(client, package, data).status_code == 422
    assert client.get('/api/cases').json() == []

@pytest.mark.parametrize('age', ['-1', '12.5', '131', 'true', 'invalid'])
def test_invalid_age(client, package, age):
    assert upload(client, package, VALID | {'patient_age': age}).status_code == 422

@pytest.mark.parametrize('name', ['', '   ', 'x' * 121])
def test_invalid_name(client, package, name):
    assert upload(client, package, VALID | {'patient_name': name}).status_code == 422

@pytest.mark.parametrize('gender', ['', 'Unknown'])
def test_invalid_gender(client, package, gender):
    assert upload(client, package, VALID | {'patient_gender': gender}).status_code == 422

@pytest.mark.parametrize('age', ['0', '130'])
def test_age_boundaries(client, package, age):
    response = upload(client, package, VALID | {'patient_age': age})
    assert response.status_code == 200, response.text
    assert response.json()['patient']['age'] == int(age)

def test_dicom_only_integration_upload(client, package):
    response = client.post('/api/integration/cases', files={'files': ('synthetic.zip', package)})
    assert response.status_code == 200, response.text
    assert response.json()['patient']['patient_id'] == response.json()['study']['patientId']

def test_json_only_creation_is_not_supported(client):
    assert client.post('/api/cases', json={'patientName': 'Test', 'patientAge': 42, 'patientGender': 'Female'}).status_code == 422
    assert client.get('/api/cases').json() == []

def test_access_and_legacy(client, package):
    case = upload(client, package).json()
    legacy = dict(case); legacy['id'] = 'KN-LEGACY'; legacy.pop('patient')
    legacy['audit'] = []; legacy.pop('auditChain', None)
    backend.save_case(legacy)
    assert client.get('/api/cases/KN-LEGACY').status_code == 200
    client.post('/api/auth/logout')
    assert upload(client, package).status_code == 401
    for role in ['orthopedist', 'patient']:
        assert client.post('/api/auth/login', json={'email': role+'@example.test', 'password': 'test-password', 'role': role}).status_code == 200
        assert upload(client, package).status_code == 403
        assert client.get('/api/cases/' + case['id']).status_code == 404

def test_failed_upload_can_retry(client, package):
    assert upload(client, b'invalid').status_code == 422
    assert client.get('/api/cases').json() == []
    assert not list((backend.DATA / 'studies').glob('KN-*'))
    assert upload(client, package).status_code == 200
