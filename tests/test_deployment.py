"""Source-based deployment regressions; no interpreter-specific bytecode required."""
import pytest
from fastapi.testclient import TestClient
from backend import app as service
from test_backend import seeded_case, client

@pytest.mark.parametrize('status', ['PROCESSING', 'REVIEWING'])
def test_restart_recovers_interrupted_work(tmp_path, monkeypatch, status):
    monkeypatch.setattr(service, 'DATA', tmp_path)
    service.init_db()
    case = seeded_case(status)
    if status == 'REVIEWING':
        case['reportJob'] = {'status': 'PROCESSING', 'id': 'interrupted'}
    service.save_case(case)
    with TestClient(service.app) as api:
        assert api.get('/api/health').json()['worker_ready'] is True
        recovered = service.get_case(case['id'])
        if status == 'PROCESSING':
            assert recovered['status'] == 'ERROR'
            assert 'interrupted' in recovered['analysisError']
        else:
            assert recovered['reportJob']['status'] == 'FAILED'
            assert 'report' not in recovered
        assert service.verify_audit(recovered)['valid']

def test_secure_session_cookie(client, monkeypatch):
    monkeypatch.setenv('KNEURA_SECURE_COOKIE', '1')
    result = client.post('/api/auth/login', json={'email': 'radiologist@test.local', 'password': 'test-password-123', 'role': 'radiologist'})
    assert result.status_code == 200
    cookie = result.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
