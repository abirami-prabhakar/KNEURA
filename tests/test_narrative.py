"""Focused offline contract tests. Provider doubles are NOT live Gemini evidence."""
import io
import json
from copy import deepcopy

import pytest

from backend import narrative
from backend import app as service
from test_backend import client, login, reviewed_case, narrative_result


@pytest.fixture(autouse=True)
def isolated_provider(monkeypatch):
    monkeypatch.setenv('KNEURA_LLM_URL', 'http://unit-test.invalid/chat/completions')
    monkeypatch.setenv('KNEURA_LLM_MODEL', 'unit-test-model')
    monkeypatch.setenv('KNEURA_LLM_KEY', 'unit-test-key')
    monkeypatch.setenv('LLM_MAX_RETRIES', '0')


def envelope(content):
    return json.dumps({'choices': [{'message': {'content': content}}]}).encode()


def test_api_key_alias_preserves_existing_key_precedence(monkeypatch):
    monkeypatch.setenv('KNEURA_LLM_API_KEY', 'alias-unit-test-key')
    assert narrative.configuration()['key'] == 'unit-test-key'
    monkeypatch.delenv('KNEURA_LLM_KEY')
    assert narrative.configuration()['key'] == 'alias-unit-test-key'


def test_wire_contract_and_approved_only_allowlist(monkeypatch):
    case = reviewed_case(2)
    case['patientId'] = 'PRIVATE-PATIENT'
    for finding in case['findings']:
        finding['evidence'] = {'id': 'evidence-' + finding['id'], 'rawMRI': 'PRIVATE-IMAGE'}
    payload = narrative.build_input(case, {'patientName': 'PRIVATE-NAME', 'laterality': 'left'})
    assert payload == {
        'approved_findings': [{'id': f['id'], 'name': f['name']} for f in case['findings'][:2]],
        'clinical_context': {'laterality': 'left'},
        'study': {'modality': 'MR', 'body_part': 'knee'},
    }
    def provider(request, timeout):
        body = json.loads(request.data)
        assert request.method == 'POST'
        assert request.get_header('Authorization') == 'Bearer unit-test-key'
        assert body['model'] == 'unit-test-model'
        assert body['temperature'] == 0 and body['max_tokens'] == 3000
        assert body['response_format'] == {'type': 'json_object'}
        assert 'stream' not in body
        assert json.loads(body['messages'][1]['content']) == payload
        assert 'PRIVATE-' not in request.data.decode()
        return io.BytesIO(envelope(json.dumps(narrative_result(payload))))
    monkeypatch.setattr(narrative.urllib.request, 'urlopen', provider)
    result, _ = narrative.generate(payload)
    assert result.report_type == 'DRAFT'
    assert result.source_finding_ids == ['0', '1']


@pytest.mark.parametrize('mutation', ['pending', 'missing', 'mismatch'])
def test_persisted_decisions_required(mutation):
    case = reviewed_case(2)
    finding = case['findings'][0]
    if mutation == 'pending':
        finding['status'] = 'PENDING'
    elif mutation == 'missing':
        finding.pop('decision')
    else:
        finding['decision']['status'] = 'REJECTED'
    with pytest.raises(ValueError):
        narrative.build_input(case)


@pytest.mark.parametrize('ids', [['0', '1', '2'], ['0'], ['0', '0']])
def test_frontend_ids_cannot_override_persisted_approvals(client, monkeypatch, ids):
    login(client)
    case = reviewed_case(2)
    service.save_case(case)
    def no_request(*args, **kwargs):
        pytest.fail('Invalid frontend IDs must be rejected before a provider call.')
    monkeypatch.setattr(narrative.urllib.request, 'urlopen', no_request)
    response = client.post(f"/api/cases/{case['id']}/report-jobs", json={'approvedFindingIds': ids})
    assert response.status_code == 422
    assert 'report' not in service.get_case(case['id'])


@pytest.mark.parametrize('body', [
    b'not-json',
    envelope('not-json'),
    envelope('{}'),
    b'{"choices":[]}',
    envelope(json.dumps({'report_type': 'FINAL'})),
])
def test_invalid_provider_response_never_persists_draft(client, monkeypatch, body):
    login(client)
    case = reviewed_case(2)
    service.save_case(case)
    monkeypatch.setattr(narrative.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(body))
    response = client.post(f"/api/cases/{case['id']}/report-jobs", json={'approvedFindingIds': ['0', '1']})
    assert response.status_code == 202
    saved = service.get_case(case['id'])
    assert saved['reportJob']['status'] == 'FAILED'
    assert 'No draft was saved' in saved['reportJob']['error']
    assert 'report' not in saved
    assert saved['findings'] == case['findings']


def test_all_rejected_sends_empty_findings_and_persists_only_limitations(client, monkeypatch):
    login(client)
    case = reviewed_case(0)
    service.save_case(case)
    def provider(request, timeout):
        payload = json.loads(json.loads(request.data)['messages'][1]['content'])
        assert payload['approved_findings'] == []
        assert all(f['name'] not in json.dumps(payload) for f in case['findings'])
        # Explicit unit-test fixture; never used as application fallback content.
        result = dict(report_type='DRAFT', source_finding_ids=[],
                      findings='No reportable findings were supplied.',
                      impression='This does not establish a normal examination.')
        result['statements'] = [dict(text=result[section], section=section, finding_ids=[])
                                for section in ('findings', 'impression')]
        return io.BytesIO(envelope(json.dumps(result)))
    monkeypatch.setattr(narrative.urllib.request, 'urlopen', provider)
    response = client.post(f"/api/cases/{case['id']}/report-jobs", json={'approvedFindingIds': []})
    assert response.status_code == 202
    report = service.get_case(case['id'])['report']
    assert report['status'] == 'DRAFT'
    assert report['approvedFindingIds'] == []
    assert all(s['findingIds'] == [] for s in report['statements'])


@pytest.mark.parametrize('claim', [
    'ACL fiber discontinuity is present.', 'ACL retraction is present.',
    'ACL abnormality is chronic.', 'Marrow edema is present.',
    'ACL abnormality was approved by the radiologist.',
    'AI probabilities indicate an ACL abnormality.',
])
def test_unsupported_details_and_workflow_prose_rejected(claim):
    payload = narrative.build_input(reviewed_case(1))
    raw = deepcopy(narrative_result(payload))
    raw['findings'] = raw['statements'][0]['text'] = claim
    with pytest.raises(ValueError):
        narrative.validate_output(raw, payload)


def test_actual_evidence_remains_linked_through_existing_finding_ids(client, monkeypatch):
    login(client)
    case = reviewed_case(2)
    case['series'] = [{'id': 'unit-series', 'images': [{'id': 'unit-image', 'instanceNumber': 1}]}]
    for f in case['findings']:
        f['evidence'] = {'id': 'unit-evidence-' + f['id'], 'seriesId': 'unit-series',
                         'sliceStart': 1, 'sliceEnd': 1, 'instanceNumbers': [1]}
    before = deepcopy(case['findings'])
    service.save_case(case)
    def provider(request, timeout):
        payload = json.loads(json.loads(request.data)['messages'][1]['content'])
        return io.BytesIO(envelope(json.dumps(narrative_result(payload))))
    monkeypatch.setattr(narrative.urllib.request, 'urlopen', provider)
    response = client.post(f"/api/cases/{case['id']}/report-jobs", json={'approvedFindingIds': ['0', '1']})
    assert response.status_code == 202
    saved = service.get_case(case['id'])
    assert saved['findings'] == before
    for statement in saved['report']['statements']:
        assert 'evidenceIds' not in statement
        for source_id in statement['findingIds']:
            finding = next(f for f in saved['findings'] if f['id'] == source_id)
            assert finding['status'] == 'APPROVED'
            assert finding['evidence'] == next(f['evidence'] for f in before if f['id'] == source_id)


def test_provider_paragraph_whitespace_preserves_statement_content():
    payload = narrative.build_input(reviewed_case(3))
    raw = narrative_result(payload)
    raw['findings'] = ' '.join(s['text'] for s in raw['statements'] if s['section'] == 'findings')
    raw['impression'] = ' '.join(s['text'] for s in raw['statements'] if s['section'] == 'impression')
    result = narrative.validate_output(raw, payload)
    assert result.findings == '\n'.join(s['text'] for s in raw['statements'] if s['section'] == 'findings')
    assert result.findings.split() == raw['findings'].split()
    raw['findings'] += ' Additional unsupported statement.'
    with pytest.raises(ValueError, match='Narrative and traceable statements disagree'):
        narrative.validate_output(raw, payload)
