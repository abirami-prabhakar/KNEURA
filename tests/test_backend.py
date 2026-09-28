"""Workflow/authorization tests and real supplied-checkpoint integration test.
All DICOM input generated here is synthetic and never clinical validation.
"""
import io
import json
import zipfile
from pathlib import Path
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

from backend import app as service
from backend.inference import NAMES


def dicom_bytes(study, series, number, patient='SYNTHETIC-TEST'):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b'\0' * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
    ds.InstanceNumber, ds.Modality = number, 'MR'
    ds.PatientID, ds.PatientName = patient, 'SYNTHETIC^TEST'
    ds.StudyDescription, ds.SeriesDescription = 'Synthetic software test', 'PD FS'
    ds.StudyDate = '20260923'
    ds.Rows = ds.Columns = 32
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit, ds.PixelRepresentation = 15, 0
    ds.PixelData = np.random.default_rng(number).integers(0, 4096, (32, 32), dtype=np.uint16).tobytes()
    out = io.BytesIO()
    ds.save_as(out, enforce_file_format=True)
    return out.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'DATA', tmp_path)
    with TestClient(service.app) as test:
        with service.db() as conn:
            for role, patient in [('radiologist', ''), ('orthopedist', ''), ('patient', 'SYNTHETIC-TEST'), ('otherpatient', 'OTHER')]:
                salt = '01' * 16
                actual_role = 'patient' if role == 'otherpatient' else role
                conn.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', (role, role + '@test.local', role, actual_role, salt, service.password_hash('test-password-123', salt), patient))
        yield test


def login(client, role='radiologist'):
    actual = 'patient' if role == 'otherpatient' else role
    result = client.post('/api/auth/login', json={'email': role + '@test.local', 'password': 'test-password-123', 'role': actual})
    assert result.status_code == 200, result.text


def seeded_case(status='AI_READY'):
    return dict(id='KN-TEST', status=status, study=dict(id='study', patientId='SYNTHETIC-TEST', patientName='Synthetic test', description='Test', date=''),
                series=[], audit=[], updatedAt=service.now(), findings=[dict(id=str(i), name=name, status='PENDING', probability=.1) for i, name in enumerate(NAMES)])


def test_auth_and_origin(client):
    assert client.get('/api/cases').status_code == 401
    assert client.post('/api/auth/login', json={'email': 'patient@test.local', 'password': 'test-password-123', 'role': 'radiologist'}).status_code == 401
    login(client)
    assert client.post('/api/auth/logout', headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.post('/api/auth/logout').status_code == 204
    assert client.get('/api/auth/me').status_code == 401


def test_review_report_and_release_gates(client):
    service.save_case(seeded_case())
    login(client)
    route = '/api/cases/KN-TEST'
    assert client.post(route + '/report', json={'approvedFindingIds': []}).status_code == 409
    for i in range(12):
        response = client.post(route + f'/findings/{i}/decision', json={'status': 'APPROVED' if i == 2 else 'REJECTED'})
        assert response.status_code == 200
    assert client.post(route + '/report', json={'approvedFindingIds': ['2', '3']}).status_code == 422
    login(client, 'patient')
    assert client.get(route).status_code == 404
    assert client.post(route + '/report', json={'approvedFindingIds': ['2']}).status_code == 403
    login(client)
    draft = client.post(route + '/report', json={'approvedFindingIds': ['2']})
    assert draft.status_code == 200, draft.text
    report = draft.json()['report']
    assert 'Medial Meniscus' in report['findings'] and 'Lateral Meniscus' not in report['findings']
    assert report['statements'][0]['findingIds'] == ['2']
    assert client.post(route + '/findings/3/decision', json={'status': 'APPROVED'}).status_code == 409
    assert client.post(route + '/report/finalize').status_code == 422
    edit = client.patch(route + '/report', json={'findings': report['findings'], 'impression': 'Radiologist-authored interpretation of approved medial meniscal finding.'})
    assert edit.status_code == 200
    assert edit.json()['report']['statements'][-1]['source'] == 'radiologist-authored'
    assert edit.json()['report']['statements'][-1]['findingIds'] == []
    final = client.post(route + '/report/finalize')
    assert final.status_code == 200
    assert final.json()['report']['version'] == 2
    exported = client.get(route + '/export').json()
    assert len(exported['findings']) == 1 and exported['findings'][0]['status'] == 'APPROVED'
    assert 'revisions' not in exported['report']
    assert 'MVP demonstration' in exported['integration_mode']
    assert client.patch(route + '/report', json={'findings': 'change', 'impression': 'change'}).status_code == 409
    login(client, 'orthopedist')
    release = client.post(route + '/release-to-patient')
    assert release.status_code == 200
    login(client, 'patient')
    patient = client.get(route).json()
    assert len(patient['findings']) == 1 and 'probability' not in patient['findings'][0]
    assert patient['audit'] == [] and patient['series'] == []
    assert 'revisions' not in patient['report']
    assert client.get(route + '/export').json()['report_status'] == 'FINAL'
    login(client, 'otherpatient')
    assert client.get(route).status_code == 404 and client.get('/api/cases').json() == []
    login(client, 'orthopedist')
    assert client.get(route).status_code == 200
    assert client.post(route + '/report/finalize').status_code == 403


@pytest.mark.parametrize('case_status,report_status', [('AI_READY', None), ('DRAFT', 'UNDER_REVIEW'), ('FINAL', 'UNDER_REVIEW'), ('DRAFT', 'FINAL')])
def test_handoff_requires_both_final_states(client, case_status, report_status):
    case = seeded_case(case_status)
    if report_status:
        case['report'] = dict(status=report_status, approvedFindingIds=[], statements=[])
    service.save_case(case)
    login(client, 'orthopedist')
    assert client.get('/api/cases').json() == []
    assert client.get('/api/cases/KN-TEST').status_code == 404
    assert client.get('/api/cases/KN-TEST/export').status_code == 404
    assert client.post('/api/cases/KN-TEST/release-to-patient').status_code == 409
    assert not service.get_case('KN-TEST').get('releasedToPatient')


def test_handoff_release_persistence_and_identity(client):
    case = seeded_case('FINAL')
    case['report'] = dict(status='FINAL', approvedFindingIds=[], statements=[])
    service.save_case(case)
    route = '/api/cases/KN-TEST'
    for role in ('radiologist', 'patient', 'otherpatient'):
        login(client, role)
        assert client.post(route + '/release-to-patient').status_code == 403
    login(client, 'patient')
    assert client.get('/api/cases').json() == []
    assert client.get(route).status_code == 404
    login(client, 'orthopedist')
    assert [c['id'] for c in client.get('/api/cases').json()] == ['KN-TEST']
    assert client.get(route).status_code == 200
    released = client.post(route + '/release-to-patient')
    assert released.status_code == 200
    stored = service.get_case('KN-TEST')
    assert stored['releasedToPatient'] is True
    assert stored['releasedToPatientById'] == 'orthopedist'
    assert stored['releasedToPatientAt']
    assert stored['report'] == case['report']
    assert stored['findings'] == case['findings']
    assert stored['study'] == case['study']
    assert len(stored['audit']) == 1
    assert client.post(route + '/release-to-patient').status_code == 409
    assert len(service.get_case('KN-TEST')['audit']) == 1
    for role in ('patient', 'otherpatient', 'orthopedist', 'radiologist', 'patient'):
        assert client.post('/api/auth/logout').status_code == 204
        login(client, role)
        allowed = role != 'otherpatient'
        assert client.get(route).status_code == (200 if allowed else 404)
        assert client.get(route + '/export').status_code == (200 if allowed else 404)
        assert len(client.get('/api/cases').json()) == int(allowed)


def test_duplicate_canonical_and_all_rejected(client):
    login(client)
    case = seeded_case('REVIEWING')
    for finding in case['findings']:
        finding['status'] = 'REJECTED'
        finding['decision'] = dict(status='REJECTED', userId='radiologist', timestamp=service.now())
    case['findings'][-1]['name'] = 'ACL'
    service.save_case(case)
    assert client.post('/api/cases/KN-TEST/report', json={'approvedFindingIds': []}).status_code == 409
    case['findings'][-1]['name'] = NAMES[-1]
    service.save_case(case)
    result = client.post('/api/cases/KN-TEST/report', json={'approvedFindingIds': []})
    assert result.status_code == 200
    assert 'does not establish a normal examination' in result.json()['report']['findings']


def test_reject_invalid_and_mixed_study(client):
    login(client)
    assert client.post('/api/cases', files=[('files', ('bad.dcm', b'not DICOM'))]).status_code == 422
    series = generate_uid()
    files = [('files', ('1.dcm', dicom_bytes(generate_uid(), series, 1))), ('files', ('2.dcm', dicom_bytes(generate_uid(), series, 2)))]
    assert client.post('/api/cases', files=files).status_code == 422
    assert client.get('/api/cases').json() == []


def test_real_checkpoint_dicom_gradcam_and_frozen_mean(client):
    """Real model, six synthetic slices, two overlapping windows; no mocked inference."""
    from knee_ai_inference import analyze_study
    import pandas as pd
    from backend.inference import checkpoint_path
    login(client)
    study, series = generate_uid(), generate_uid()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for number in [6, 3, 1, 5, 2, 4]:
            archive.writestr(f'nested/{number}.dcm', dicom_bytes(study, series, number))
        archive.writestr('series.csv', f'StudyInstanceUID,SeriesInstanceUID,Fluid_Sensitive,Fat_Suppression\n{study},{series},1,1\n')
    response = client.post('/api/cases', files=[('files', ('test.zip', buffer.getvalue()))])
    assert response.status_code == 200, response.text
    case = response.json()
    assert [i['instanceNumber'] for i in case['series'][0]['images']] == [1, 2, 3, 4, 5, 6]
    route = '/api/cases/' + case['id']
    assert client.post(route + '/analysis').status_code == 200
    case = client.get(route).json()
    assert case['status'] == 'AI_READY', case.get('analysisError')
    assert len(case['findings']) == 12 and case['analysis']['windowsEvaluated'] == 2
    for finding in case['findings']:
        assert 0 <= finding['probability'] <= 1
        assert len(finding['evidence']['instanceNumbers']) == 5
        image = client.get(finding['evidence']['gradCamImageUrl'])
        assert image.status_code == 200 and image.content.startswith(b'\x89PNG')
    # Independent call to the untouched user-supplied study aggregation.
    root = service.DATA / 'frozen-comparison'
    target = root / series
    target.mkdir(parents=True)
    for number in range(1, 7):
        (target / f'{number}.dcm').write_bytes(dicom_bytes(study, series, number))
    frozen = analyze_study(study, str(root), pd.DataFrame([dict(StudyInstanceUID=study, SeriesInstanceUID=series, Fluid_Sensitive=1, Fat_Suppression=1)]), str(checkpoint_path(service.DATA / 'checkpoints')))
    assert np.allclose(list(frozen['probabilities'].values()), [f['probability'] for f in case['findings']], atol=1e-7)
    login(client, 'patient')
    assert client.get(case['findings'][0]['evidence']['mriImageUrl']).status_code == 404

def test_optional_llm_receives_only_approved_and_rejects_invented_ids(client, monkeypatch):
    from backend import narrative
    login(client)
    case = seeded_case('REVIEWING')
    for index, finding in enumerate(case['findings']):
        finding['status'] = 'APPROVED' if index < 5 else 'REJECTED'
        finding['decision'] = dict(status=finding['status'], userId='radiologist', timestamp=service.now())
    service.save_case(case)
    monkeypatch.setenv('KNEURA_LLM_URL', 'http://local-provider/chat/completions')
    monkeypatch.setenv('KNEURA_LLM_MODEL', 'contract-test')
    payloads = []
    def provider(request, timeout):
        payloads.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': '{"findingIds":["invented"]}'}}]}).encode())
    monkeypatch.setattr(narrative.urllib.request, 'urlopen', provider)
    result = client.post('/api/cases/KN-TEST/report-jobs', json={'approvedFindingIds': [str(i) for i in range(5)]})
    assert result.status_code == 202
    assert service.get_case('KN-TEST')['reportJob']['status'] == 'FAILED'
    supplied = json.loads(payloads[0]['messages'][1]['content'])
    assert supplied['approved_findings'] == [{'id': str(i), 'name': NAMES[i]} for i in range(5)]
    assert not any(name in json.dumps(supplied) for name in NAMES[5:])
    assert 'report' not in service.get_case('KN-TEST')


def test_analysis_failure_is_retryable_without_fake_results(client, monkeypatch):
    login(client)
    case = seeded_case('RECEIVED')
    case['findings'] = []
    case['series'] = [{'id': 'series', 'eligible': True, 'images': [dict(id=str(i), instanceNumber=i) for i in range(5)]}]
    service.save_case(case)
    def broken(*args):
        raise RuntimeError('Synthetic simulated failure')
    monkeypatch.setattr(service, 'analyze', broken)
    assert client.post('/api/cases/KN-TEST/analysis').status_code == 200
    failed = client.get('/api/cases/KN-TEST').json()
    assert failed['status'] == 'ERROR' and failed['findings'] == []
    assert failed['analysisError']


def test_decision_changes_and_report_revisions_record_identity(client):
    login(client)
    service.save_case(seeded_case())
    route = '/api/cases/KN-TEST'
    client.post(route + '/findings/0/decision', json={'status': 'REJECTED'})
    result = client.post(route + '/findings/0/decision', json={'status': 'APPROVED'}).json()
    event = result['audit'][-1]
    assert event['previous']['status'] == 'REJECTED'
    assert event['current']['status'] == 'APPROVED'
    assert event['actorId'] == 'radiologist' and event['objectId'] == '0' and event['caseId'] == 'KN-TEST'
    for i in range(1, 12):
        client.post(route + f'/findings/{i}/decision', json={'status': 'REJECTED'})
    draft = client.post(route + '/report', json={'approvedFindingIds': ['0']}).json()['report']
    edited = client.patch(route + '/report', json={'findings': draft['findings'], 'impression': 'Reviewed synthetic software test.'}).json()['report']
    assert edited['status'] == 'UNDER_REVIEW'
    assert edited['revisions'][0]['findings'] == draft['findings']
    assert edited['revisions'][0]['editorId'] == 'radiologist'
    assert edited['editedById'] == edited['reviewedById'] == 'radiologist'
    service.init_db()  # Existing storage survives initialization, not frontend memory.
    assert service.get_case('KN-TEST')['report']['version'] == 2
    assert client.post(route + '/report/finalize').status_code == 200
    assert client.post(route + '/analysis').status_code == 409
    assert client.post(route + '/findings/0/decision', json={'status': 'REJECTED'}).status_code == 409


def test_empty_selection_csv_does_not_fall_back_and_missing_identity_fails(client):
    login(client)
    study, series = generate_uid(), generate_uid()
    files = [('files', (f'{n}.dcm', dicom_bytes(study, series, n))) for n in range(1, 6)]
    files.append(('files', ('series.csv', b'StudyInstanceUID,SeriesInstanceUID,Fluid_Sensitive,Fat_Suppression\n')))
    result = client.post('/api/cases', files=files)
    assert result.status_code == 200
    case = result.json()
    assert case['series'][0]['eligible'] is False
    assert client.post('/api/cases/' + case['id'] + '/analysis').status_code == 422
    missing = client.post('/api/cases', files=[('files', ('missing.dcm', dicom_bytes(generate_uid(), generate_uid(), 1, patient='')))])
    assert missing.status_code == 422 and 'PatientID' in missing.json()['detail']


def test_failed_access_logged_and_login_rotates_session(client):
    assert client.get('/api/cases').status_code == 401
    login(client)
    old = client.cookies.get('kneura_session')
    login(client, 'patient')
    assert client.cookies.get('kneura_session') != old
    import hashlib
    with service.db() as conn:
        assert conn.execute('SELECT 1 FROM sessions WHERE token=?', (hashlib.sha256(old.encode()).hexdigest(),)).fetchone() is None
        assert conn.execute('SELECT 1 FROM access_log WHERE status=401').fetchone()


def narrative_result(payload):
    ids = [f['id'] for f in payload['approved_findings']]
    findings = 'Abnormalities involve ' + ', '.join(f['name'] for f in payload['approved_findings']) + '.'
    impression = 'Knee abnormalities as described.'
    return dict(report_type='DRAFT', findings=findings, impression=impression, source_finding_ids=ids,
        statements=[dict(text=findings, section='findings', finding_ids=ids), dict(text=impression, section='impression', finding_ids=ids)])


def reviewed_case(count=5):
    case = seeded_case('REVIEWING')
    for i, f in enumerate(case['findings']):
        f['status'] = 'APPROVED' if i < count else 'REJECTED'
        f['decision'] = dict(status=f['status'], userId='radiologist', userName='radiologist', timestamp=service.now())
    return case


def test_successful_narrative_contract_contains_five_approved_only(client, monkeypatch):
    from backend import narrative
    login(client)
    service.save_case(reviewed_case())
    monkeypatch.setenv('KNEURA_LLM_URL', 'http://test-provider/chat/completions')
    monkeypatch.setenv('KNEURA_LLM_MODEL', 'contract-test')
    def provider(request, timeout):
        payload = json.loads(json.loads(request.data)['messages'][1]['content'])
        assert payload['approved_findings'] == [{'id': str(i), 'name': NAMES[i]} for i in range(5)]
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(narrative_result(payload))}}]}).encode())
    monkeypatch.setattr(narrative.urllib.request, 'urlopen', provider)
    route = '/api/cases/KN-TEST/report-jobs'
    body = {'approvedFindingIds': [str(i) for i in range(5)], 'requestId': 'same-request-123'}
    result = client.post(route, json=body)
    assert result.status_code == 202
    case = service.get_case('KN-TEST')
    assert case['reportJob']['status'] == 'COMPLETED'
    report = case['report']
    assert report['status'] == 'DRAFT' and report['provider'].startswith('Live LLM narrative')
    assert report['approvedFindingIds'] == [str(i) for i in range(5)]
    assert client.post(route, json=body).json()['job_id'] == result.json()['job_id']
    assert client.post('/api/cases/KN-TEST/report/finalize').status_code == 422
    assert client.get(f"{route}/{result.json()['job_id']}").json()['status'] == 'COMPLETED'


def test_status_without_recorded_decision_cannot_generate(client):
    login(client)
    case = seeded_case('REVIEWING')
    for finding in case['findings']:
        finding['status'] = 'APPROVED'
    service.save_case(case)
    result = client.post('/api/cases/KN-TEST/report', json={'approvedFindingIds': [str(i) for i in range(12)]})
    assert result.status_code == 409
    assert 'persisted radiologist identity' in result.json()['detail']


def test_expired_session_and_tampered_report_review_gate(client):
    login(client)
    with service.db() as conn:
        conn.execute('UPDATE sessions SET expires=0')
    assert client.get('/api/auth/me').status_code == 401
    login(client)
    service.save_case(seeded_case())
    for i in range(12):
        client.post(f'/api/cases/KN-TEST/findings/{i}/decision', json={'status': 'REJECTED'})
    client.post('/api/cases/KN-TEST/report', json={'approvedFindingIds': []})
    case = service.get_case('KN-TEST')
    case['report']['impression'] = 'Text alone does not establish saved review.'
    service.save_case(case)
    result = client.post('/api/cases/KN-TEST/report/finalize')
    assert result.status_code == 422 and 'Review and save' in result.json()['detail']


def test_storage_rejects_orphaned_evidence_and_report_links(client):
    case = seeded_case()
    case['findings'][0]['evidence'] = dict(seriesId='missing', sliceStart=1, sliceEnd=5)
    with pytest.raises(ValueError, match='same case'):
        service.save_case(case)
    assert client.get('/api/cases').status_code == 401
    case = seeded_case()
    case['report'] = dict(approvedFindingIds=[], statements=[dict(findingIds=['0'])])
    with pytest.raises(ValueError, match='approved findings'):
        service.save_case(case)


def test_missing_checkpoint_has_meaningful_model_error(client, monkeypatch):
    login(client)
    monkeypatch.setenv('KNEURA_CHECKPOINT', str(service.DATA / 'missing.pt'))
    result = client.get('/api/model')
    assert result.status_code == 503 and 'KNEURA_CHECKPOINT' in result.json()['detail']


def test_audit_detects_mutation_reorder_and_truncation(client):
    from copy import deepcopy
    from backend.audit import event, verify
    case = seeded_case()
    event(case, 'First', 'System')
    event(case, 'Second', 'System')
    assert verify(case)['valid']
    for operation in ('mutate', 'reorder', 'truncate'):
        changed = deepcopy(case)
        if operation == 'mutate': changed['audit'][0]['action'] = 'Modified'
        if operation == 'reorder': changed['audit'].reverse()
        if operation == 'truncate': changed['audit'].pop()
        assert not verify(changed)['valid']
    service.save_case(case)
    login(client)
    assert client.get('/api/v1/audit/KN-TEST/verify').json()['valid']
    login(client, 'patient')
    assert client.get('/api/v1/audit/KN-TEST/verify').status_code == 403


def test_report_job_does_not_hold_workflow_lock(client, monkeypatch):
    import threading
    from fastapi import BackgroundTasks
    from backend import narrative, report_jobs
    login(client)
    service.save_case(reviewed_case())
    monkeypatch.setenv('KNEURA_LLM_URL', 'http://test-provider/chat/completions')
    monkeypatch.setenv('KNEURA_LLM_MODEL', 'test')
    started, release = threading.Event(), threading.Event()
    def slow(payload):
        started.set()
        assert release.wait(5)
        return narrative.Narrative.model_validate(narrative_result(payload)), dict(provider='explicit-test-double', model='test')
    monkeypatch.setattr(narrative, 'generate', slow)
    account = dict(id='radiologist', name='radiologist', role='radiologist')
    body = service.NarrativeRequest(approvedFindingIds=[str(i) for i in range(5)])
    queued = service.queue_report('KN-TEST', body, BackgroundTasks(), account)
    job = service.get_case('KN-TEST')['reportJob']
    worker = threading.Thread(target=report_jobs.run, args=(service, 'KN-TEST', queued['job_id'], job['input'], account))
    worker.start()
    try:
        assert started.wait(3)
        assert service.LOCK.acquire(timeout=.5)
        service.LOCK.release()
        assert client.get('/api/cases').status_code == 200
        assert client.post('/api/cases/KN-TEST/findings/0/decision', json={'status':'REJECTED'}).status_code == 409
    finally:
        release.set()
        worker.join(5)
    assert service.get_case('KN-TEST')['reportJob']['status'] == 'COMPLETED'


def test_native_viewer_dimensions_window_and_authorization(client):
    from PIL import Image
    login(client)
    study, series = generate_uid(), generate_uid()
    case = client.post('/api/cases', files=[('files', ('image.dcm', dicom_bytes(study, series, 1)))]).json()
    image = case['series'][0]['images'][0]
    assert image['width'] == image['height'] == 32
    first = client.get(image['sourceUrl'], params={'width':4000, 'center':2000})
    second = client.get(image['sourceUrl'], params={'width':500, 'center':2000})
    assert first.status_code == second.status_code == 200
    assert Image.open(io.BytesIO(first.content)).size == (32,32)
    assert first.content != second.content
    assert client.get(image['sourceUrl'], params={'width':0}).status_code == 422
    login(client, 'patient')
    assert client.get(image['sourceUrl']).status_code == 404


def test_manual_evidence_attachment_is_explicit_and_versioned(client):
    login(client)
    case = reviewed_case(1)
    case['series'] = [dict(id='s', images=[dict(id='i',instanceNumber=1)])]
    case['findings'][0]['evidence'] = dict(id='e',seriesId='s',sliceStart=1,sliceEnd=1,instanceNumbers=[1])
    service.save_case(case)
    route = '/api/cases/KN-TEST'
    report = client.post(route+'/report', json={'approvedFindingIds':['0']}).json()['report']
    edited = client.patch(route+'/report', json={'findings':report['findings'], 'impression':'Authored interpretation.'}).json()['report']
    statement = edited['statements'][-1]
    endpoint = route+'/report/statements/'+statement['id']+'/evidence'
    body = dict(findingId='0',evidenceId='e',version=edited['version'])
    assert client.post(endpoint, json={**body,'findingId':'1'}).status_code == 422
    attached = client.post(endpoint,json=body)
    assert attached.status_code == 200
    report = attached.json()['report']
    assert report['statements'][-1]['source'] == 'radiologist-linked'
    assert report['statements'][-1]['evidenceIds'] == ['e']
    assert client.post(endpoint,json=body).status_code == 409
    saved = client.patch(route+'/report',json={'findings':report['findings'],'impression':report['impression']}).json()['report']
    assert saved['statements'][-1]['evidenceIds'] == ['e']
    assert client.post(route+'/report/finalize').status_code == 200
    assert client.post(endpoint,json={**body,'version':saved['version']}).status_code == 409


def test_login_throttle_and_llm_unavailable(client, monkeypatch):
    monkeypatch.delenv('KNEURA_LLM_URL', raising=False)
    monkeypatch.delenv('LLM_URL', raising=False)
    login(client)
    assert client.get('/api/system/llm/health').json()['reachable'] is False
    service.save_case(reviewed_case())
    assert client.post('/api/cases/KN-TEST/report-jobs',json={'approvedFindingIds':[str(i) for i in range(5)]}).status_code == 503
    for _ in range(10):
        assert client.post('/api/auth/login',json={'email':'unknown@test.local','password':'incorrect','role':'radiologist'}).status_code == 401
    assert client.post('/api/auth/login',json={'email':'unknown@test.local','password':'incorrect','role':'radiologist'}).status_code == 429


def test_verified_backup_restore(client, tmp_path):
    from backend.recovery import backup, restore
    case = seeded_case()
    service.event(case, 'Test event', 'System')
    service.save_case(case)
    archive = tmp_path/'backup.zip'
    assert backup(service.DATA, archive)['verified']
    target = tmp_path/'restored'
    assert restore(archive,target)['verified']
    import sqlite3
    with sqlite3.connect(target/'kneura.sqlite') as conn:
        assert json.loads(conn.execute('SELECT document FROM cases').fetchone()[0])['id'] == 'KN-TEST'
        assert conn.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
    with pytest.raises(ValueError,match='new'):
        restore(archive,target)


def test_required_csv_and_integration_adapter(client, monkeypatch):
    login(client)
    monkeypatch.setenv('KNEURA_REQUIRE_SERIES_CSV','1')
    study, series = generate_uid(), generate_uid()
    files=[('files',('image.dcm',dicom_bytes(study,series,1)))]
    assert client.post('/api/integration/cases',files=files).status_code == 422
    files.append(('files',('series.csv',f'StudyInstanceUID,SeriesInstanceUID,Fluid_Sensitive,Fat_Suppression\n{study},{series},1,1\n'.encode())))
    result=client.post('/api/integration/cases',files=files)
    assert result.status_code == 200
    assert result.json()['series'][0]['eligibilityCsvSha256']
    assert client.get('/api/integration/cases/'+result.json()['id']+'/result').status_code == 409


def test_demo_verifier_does_not_claim_missing_or_synthetic_data_is_clinical(tmp_path):
    from backend.demo_validation import verify_study
    from backend.demo import create_demo_package
    assert not verify_study(tmp_path/'missing',tmp_path/'missing.csv')['ready']
    archive = create_demo_package(tmp_path/'synthetic.zip')
    folder = tmp_path/'demo'
    folder.mkdir()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            (folder/name).write_bytes(z.read(name))
    result = verify_study(folder,folder/'series.csv')
    assert result['synthetic'] is True and result['ready'] is False
    assert result['image_count'] == 6 and result['windows'] == 2
    assert any('attestation' in p for p in result['problems'])


def test_narrative_response_rejects_unapproved_claims_and_wrong_traces():
    from copy import deepcopy
    from backend import narrative
    payload = narrative.build_input(reviewed_case())
    valid = narrative_result(payload)
    assert narrative.validate_output(valid,payload).report_type == 'DRAFT'
    invented = deepcopy(valid)
    invented['findings'] += ' Fracture is identified.'
    invented['statements'][0]['text'] = invented['findings']
    with pytest.raises(ValueError,match='unapproved abnormality'):
        narrative.validate_output(invented,payload)
    wrong = deepcopy(valid)
    wrong['statements'][0]['finding_ids'] = ['unapproved']
    with pytest.raises(ValueError,match='unapproved finding'):
        narrative.validate_output(wrong,payload)
    wrong = deepcopy(valid)
    wrong['report_type'] = 'FINAL'
    with pytest.raises(ValueError):
        narrative.validate_output(wrong,payload)


def test_job_restart_recovery_preserves_findings(client):
    from fastapi.testclient import TestClient
    case = reviewed_case()
    case['reportJob'] = dict(id='interrupted',status='PROCESSING')
    service.save_case(case)
    with TestClient(service.app):
        recovered = service.get_case('KN-TEST')
        assert recovered['reportJob']['status'] == 'FAILED'
        assert len(recovered['findings']) == 12 and 'report' not in recovered
        assert 'restart' in recovered['reportJob']['error'].lower()


def test_upload_patient_details_persist(client):
    login(client)
    data = dicom_bytes(generate_uid(), generate_uid(), 1)
    fields = dict(patient_name='Radhika', patient_age='42', patient_gender='Female')
    result = client.post('/api/cases', files=[('files', ('image.dcm', data))], data=fields)
    assert result.status_code == 200
    case = client.get('/api/cases/' + result.json()['id']).json()
    assert case['study']['patientName'] == 'Radhika'
    assert case['patient']['age'] == 42 and case['patient']['gender'] == 'Female'
    assert case['study']['patientId'] == 'SYNTHETIC-TEST'
    for invalid in ({**fields, 'patient_age': '-1'}, {**fields, 'patient_name': '  '}, {**fields, 'patient_gender': 'invalid'}):
        assert client.post('/api/cases', files=[('files', ('image.dcm', data))], data=invalid).status_code == 422


@pytest.mark.parametrize('age', [0, 42])
def test_uploaded_demographics_persist_with_dicom_identity(client, age):
    login(client)
    study, series = generate_uid(), generate_uid()
    response = client.post('/api/cases', data={
        'patient_name': '  Entered patient  ', 'patient_age': str(age), 'patient_gender': 'Female',
    }, files=[('files', ('study.dcm', dicom_bytes(study, series, 1)))])
    assert response.status_code == 200, response.text
    created = response.json()
    route = '/api/cases/' + created['id']
    assert created['study']['patientName'] == 'Entered patient'
    assert created['study']['patientId'] == 'SYNTHETIC-TEST'
    assert created['patient']['name'] == 'Entered patient'
    assert created['patient']['age'] == age
    assert created['patient']['gender'] == 'Female'
    assert created['patient']['patient_id'] == 'SYNTHETIC-TEST'
    assert service.get_case(created['id'])['patient'] == created['patient']
    client.post('/api/auth/logout')
    login(client)
    assert client.get(route).json()['patient'] == created['patient']
    assert client.get('/api/cases').json()[0]['patient'] == created['patient']
