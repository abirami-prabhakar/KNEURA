"""Read-only HTTP verification of the persisted case; never runs inference."""
import json
import time
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8000'
UID = '1.2.826.0.1.3680043.8.498.90283565381042081768587894596970552767'
evidence = {'checks': [], 'assets': []}
token = None


def request(path, body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request(BASE + path, data=json.dumps(body).encode() if body else None, headers=headers)
    with urlopen(req, timeout=30) as response:
        assert response.status == 200
        return response.read().decode()


def health(stage):
    result = json.loads(request('/health'))
    evidence['checks'].append({'stage': stage, 'time': time.time(), 'http_status': 200, 'body': result})
    print(f'Health after {stage}: HTTP 200', flush=True)
    (ROOT / 'verification/runtime_checks.json').write_text(json.dumps(evidence, indent=2))


subprocess.run([sys.executable, str(ROOT / 'scripts/check_environment.py'), '--skip-port'], check=True)
health('launch')
login = json.loads(request('/login', {'email': 'radiologist@kneura.local', 'password': 'Kneura-demo-74cP!2026'}))
token = login['access_token']
assert token
health('bearer login')
studies = json.loads(request('/studies'))
assert len(studies) == 10
assert any(study['study_id'] == UID for study in studies)
health('studies loaded')
html = request('/')
assert 'knee-ai-frontend-shell' in html and 'KNEE-AI' in html.upper()
health('frontend opened')
detail = json.loads(request('/studies/' + UID))
assert len(detail['ai_probabilities']) == 12
decisions = {item['finding']: item['outcome'] for item in detail['validated_findings']}
assert decisions['Effusion'] == 'CONFIRMED' and decisions['MCL'] == 'EDITED'
assert list(decisions.values()).count('REJECTED') == 10
report = detail['report']
assert report['report_id'] == 1 and report['status'] == 'DRAFT'
draft = json.loads(report['draft_content'])
assert draft['final_approval'] == 'PENDING' and 'MOCK PROVIDER' in draft['note']
health('persisted findings review and report retrieved')
assert 'location.origin' in html and 'Bearer ${session.accessToken}' in html
for route in ("api('/login'", "api('/studies'", 'api(`/studies/${studyId}`)'):
    assert route in html, route
for field in ('ai_probabilities', 'validated_findings', 'detail.report.draft_content'):
    assert field in html
routes = json.loads(request('/openapi.json'))['paths']
for path, method in (('/login', 'post'), ('/studies', 'get'), ('/studies/{study_id}', 'get'), ('/studies/{study_id}/review', 'post'), ('/studies/{study_id}/generate-report', 'post')):
    assert method in routes[path], path


class Assets(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        url = attrs.get('src') if tag == 'script' else attrs.get('href') if tag == 'link' and attrs.get('rel') == 'stylesheet' else None
        if url and url not in urls:
            urls.append(url)


urls = []
Assets().feed(html)
for url in urls:
    absolute = url if url.startswith('http') else BASE + '/' + url.lstrip('/')
    with urlopen(Request(absolute, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as response:
        assert response.status == 200 and response.read(), absolute
        evidence['assets'].append({'url': absolute, 'http_status': 200})
        print('Asset HTTP 200: ' + absolute, flush=True)
health('assets and frontend wiring verified')
evidence['result'] = 'PASS'
(ROOT / 'verification/runtime_checks.json').write_text(json.dumps(evidence, indent=2))
print('All persisted-case HTTP/API and frontend wiring checks PASS', flush=True)
