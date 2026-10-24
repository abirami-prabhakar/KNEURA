"""Clinical report preservation, clinician review and patient-summary publication."""
from copy import deepcopy

import pytest

from test_backend import client, login, seeded_case, service
from backend.patient_summary import draft


def final_case(released=False):
    case = seeded_case('FINAL')
    for finding in case['findings']:
        finding['status'] = 'APPROVED' if finding['name'] == 'ACL' else 'REJECTED'
    case['report'] = dict(id='R-TEST', version=2, status='FINAL', approvedFindingIds=['0'],
                          findings='ACL abnormality. Severity cannot be established.',
                          impression='Correlate with examination; tear grade is not established.',
                          statements=[], revisions=[])
    case['releasedToPatient'] = released
    service.save_case(case)
    return case


def review_body(summary):
    return dict(findings=summary['findings'], meaning='The scan shows a change in a stabilizing band. It does not establish how severe it is.',
                nextSteps='Discuss these findings at your planned appointment.', confirmed=True,
                version=summary['version'], sourceFingerprint=summary['sourceFingerprint'])


def test_summary_review_release_and_export_preserve_clinical_report(client):
    original = final_case()
    route = '/api/cases/KN-TEST'
    login(client, 'orthopedist')
    assert client.post(route + '/release-to-patient').status_code == 409
    prepared = client.post(route + '/patient-summary')
    assert prepared.status_code == 200
    summary = prepared.json()['patientSummary']
    assert summary['status'] == 'DRAFT'
    assert 'band of tissue' in summary['findings']
    assert 'Fracture' not in summary['findings'] and '90%' not in summary['findings']
    assert not summary['meaning'] and not summary['nextSteps']
    assert client.get(route + '/patient-summary/export').status_code == 409
    body = review_body(summary)
    assert client.patch(route + '/patient-summary', json={**body, 'confirmed': False}).status_code == 422
    assert client.patch(route + '/patient-summary', json={**body, 'meaning': '   '}).status_code == 422
    reviewed = client.patch(route + '/patient-summary', json=body)
    assert reviewed.status_code == 200
    assert reviewed.json()['patientSummary']['status'] == 'REVIEWED'
    assert client.patch(route + '/patient-summary', json=body).status_code == 409  # stale editor
    assert client.get(route + '/patient-summary/export').status_code == 409
    assert client.post(route + '/release-to-patient').status_code == 200
    stored = service.get_case('KN-TEST')
    assert stored['report'] == original['report']
    assert stored['patientSummary']['status'] == 'RELEASED'
    assert stored['patientSummary']['reviewedById'] == 'orthopedist'
    login(client, 'patient')
    visible = client.get(route).json()
    assert visible['patientSummary']['meaning'] == body['meaning']
    assert 'revisions' not in visible['patientSummary']
    exported = client.get(route + '/patient-summary/export')
    assert exported.status_code == 200
    assert 'attachment' in exported.headers['content-disposition']
    assert 'What was found' in exported.text and body['nextSteps'] in exported.text
    assert 'probability' not in exported.text and 'sourceFingerprint' not in exported.text
    assert service.get_case('KN-TEST')['audit'][-1]['action'] == 'Released patient summary exported'
    assert client.get(route + '/export').json()['report']['impression'] == original['report']['impression']


@pytest.mark.parametrize('role', ['radiologist', 'patient', 'otherpatient'])
def test_only_orthopedist_can_prepare_or_review_summary(client, role):
    case = final_case()
    login(client, role)
    assert client.post('/api/cases/KN-TEST/patient-summary').status_code == 403
    assert client.patch('/api/cases/KN-TEST/patient-summary', json=review_body(draft(case))).status_code == 403


def test_existing_released_case_never_exposes_unreviewed_summary(client):
    final_case(released=True)
    route = '/api/cases/KN-TEST'
    login(client, 'patient')
    assert client.get(route).status_code == 200
    assert client.get(route + '/patient-summary/export').status_code == 409
    login(client, 'orthopedist')
    summary = client.post(route + '/patient-summary').json()['patientSummary']
    login(client, 'patient')
    assert 'patientSummary' not in client.get(route).json()
    assert 'patientSummary' not in client.get('/api/cases').json()[0]
    login(client, 'orthopedist')
    assert client.patch(route + '/patient-summary', json=review_body(summary)).status_code == 200
    login(client, 'patient')
    assert client.get(route).json()['patientSummary']['status'] == 'RELEASED'
    assert client.get(route + '/patient-summary/export').status_code == 200


def test_changed_clinical_report_invalidates_review_and_export(client):
    final_case(released=True)
    route = '/api/cases/KN-TEST'
    login(client, 'orthopedist')
    summary = client.post(route + '/patient-summary').json()['patientSummary']
    assert client.patch(route + '/patient-summary', json=review_body(summary)).status_code == 200
    case = service.get_case('KN-TEST')
    case['report']['impression'] = 'Updated clinical uncertainty.'
    service.save_case(case)
    login(client, 'patient')
    assert 'patientSummary' not in client.get(route).json()
    assert client.get(route + '/patient-summary/export').status_code == 409
    login(client, 'orthopedist')
    fresh = client.post(route + '/patient-summary').json()['patientSummary']
    assert fresh['status'] == 'DRAFT' and fresh['sourceFingerprint'] != summary['sourceFingerprint']
    assert len(fresh['revisions']) == 2


def test_no_approved_findings_does_not_claim_a_normal_scan():
    case = seeded_case('FINAL')
    case['report'] = {'status': 'FINAL'}
    before = deepcopy(case)
    summary = draft(case)
    assert 'does not mean the whole scan is normal' in summary['findings']
    assert summary['approvedFindingIds'] == [] and summary['nextSteps'] == ''
    assert case == before


def test_summary_cannot_be_prepared_before_radiologist_finalization(client):
    case = seeded_case('DRAFT')
    service.save_case(case)
    login(client, 'orthopedist')
    assert client.post('/api/cases/KN-TEST/patient-summary').status_code == 409
