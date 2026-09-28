"""Local Technova MVP API. Run: python -m uvicorn backend.app:app --port 8000."""
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
import sys

from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, BackgroundTasks, Query, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .relationships import validate_case_links
from .auth import identity_provider, password_hash
from .audit import now, event, verify as verify_audit
from .inference import metadata, analyze
from .ingestion import ingest, MAX_BYTES
from .reporting import approved_findings, compose, edited_statements
from . import narrative, report_jobs

DATA = Path(os.getenv('KNEURA_DATA_DIR', Path(__file__).resolve().parents[1] / '.kneura'))
LOCK = threading.RLock()
LOG = logging.getLogger('kneura')


@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / 'kneura.sqlite', timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT UNIQUE, name TEXT, role TEXT, salt TEXT, password TEXT, patient_id TEXT);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, document TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS grants (case_id TEXT, user_id TEXT, PRIMARY KEY(case_id,user_id));
        CREATE TABLE IF NOT EXISTS login_attempts (identity TEXT, timestamp REAL);
        CREATE INDEX IF NOT EXISTS login_attempt_identity ON login_attempts(identity, timestamp);
        CREATE TABLE IF NOT EXISTS access_log (timestamp TEXT, user_id TEXT, method TEXT, path TEXT, status INTEGER);
        ''')


def save_case(case):
    validate_case_links(case)
    with db() as conn:
        conn.execute('INSERT OR REPLACE INTO cases VALUES (?,?)', (case['id'], json.dumps(case)))


def get_case(case_id):
    with db() as conn:
        row = conn.execute('SELECT document FROM cases WHERE id=?', (case_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Case unavailable.')
    return json.loads(row['document'])


@asynccontextmanager
async def lifespan(_app):
    init_db()
    # Interrupted background work is retryable after a restart.
    with db() as conn:
        rows = conn.execute('SELECT document FROM cases').fetchall()
    for row in rows:
        case = json.loads(row['document'])
        if case.get('reportJob', {}).get('status') in report_jobs.ACTIVE:
            case['reportJob'].update(status='FAILED', error='Server restarted during report generation. Retry safely; no draft was published.', updatedAt=now())
            event(case, 'Interrupted report job marked failed', 'System')
            save_case(case)
        if case['status'] == 'PROCESSING':
            case['status'] = 'ERROR'
            case['analysisError'] = 'Analysis was interrupted by a server restart. Start analysis again.'
            event(case, 'Interrupted analysis reset for retry', 'System')
            save_case(case)
    _app.state.worker_ready = True
    yield
    _app.state.worker_ready = False


app = FastAPI(title='KNEURA', version='1.0.0', lifespan=lifespan)


@app.middleware('http')
async def request_guard(request, call_next):
    # Same-origin API via Vite/reverse proxy. Reject cross-origin mutations.
    origin = request.headers.get('origin')
    allowed = os.getenv('KNEURA_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000').split(',')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin not in allowed:
        with db() as conn:
            conn.execute('INSERT INTO access_log VALUES (?,?,?,?,?)', (now(), None, request.method, request.url.path, 403))
        return Response('Origin not permitted', status_code=403, headers={'Cache-Control': 'no-store'})
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    with db() as conn:
        conn.execute('INSERT INTO access_log VALUES (?,?,?,?,?)', (now(), getattr(request.state, 'user_id', None), request.method, request.url.path, response.status_code))
    return response


def user(request: Request):
    token = request.cookies.get('kneura_session', '')
    with db() as conn:
        row = identity_provider.resolve_session(conn, token)
    if not row or row['role'] not in ('radiologist', 'orthopedist', 'patient'):
        raise HTTPException(401, 'Sign in to your KNEURA workspace.')
    request.state.user_id = row['id']
    return dict(row)


def radiologist(account=Depends(user)):
    if account['role'] != 'radiologist':
        raise HTTPException(403, 'A radiologist account is required.')
    return account


def public_user(account):
    return {key: account[key] for key in ('id', 'name', 'role')}


def authorized(case, account):
    if account['role'] == 'radiologist':
        return True
    if case['status'] != 'FINAL' or case.get('report', {}).get('status') != 'FINAL':
        return False
    if account['role'] == 'orthopedist':
        return True
    if account['role'] == 'patient':
        return bool(case.get('releasedToPatient')) and bool(account['patient_id']) and account['patient_id'] == case['study']['patientId']
    return False


def visible(case, account):
    if not authorized(case, account):
        raise HTTPException(404, 'Case unavailable.')
    result = deepcopy(case)
    if account['role'] != 'radiologist':
        result['findings'] = [f for f in result['findings'] if f['status'] == 'APPROVED']
        for finding in result['findings']:
            finding.pop('probability', None)
            if finding.get('evidence'):
                finding['evidence'].pop('windowProbability', None)
            if account['role'] == 'patient':
                finding.pop('evidence', None)
        result['audit'] = []
        result.pop('auditChain', None)
        result.pop('reportJob', None)
        result.pop('reportJobHistory', None)
        result['report'].pop('revisions', None)
        result.pop('analysis', None)
        if account['role'] == 'patient':
            result['series'] = []
    return result


class Login(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)
    role: str


@app.post('/api/auth/login')
def login(body: Login, response: Response, request: Request):
    identity = hashlib.sha256(body.email.strip().lower().encode()).hexdigest()
    with db() as conn:
        conn.execute('DELETE FROM login_attempts WHERE timestamp<?', (time.time()-900,))
        attempts = conn.execute('SELECT count(*) FROM login_attempts WHERE identity=?', (identity,)).fetchone()[0]
        if attempts >= 10:
            raise HTTPException(429, 'Too many failed sign-in attempts. Retry after 15 minutes.')
        # Reserve this attempt before password verification so failed exceptions do not roll it back.
        conn.execute('INSERT INTO login_attempts VALUES (?,?)', (identity, time.time()))
        conn.commit()
        row = identity_provider.authenticate(conn, body.email, body.password, body.role)
        if not row:
            raise HTTPException(401, 'Email, password or workspace role is incorrect.')
        conn.execute('DELETE FROM login_attempts WHERE identity=?', (identity,))
        request.state.user_id = row['id']
        conn.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.cookies.get('kneura_session', '').encode()).hexdigest(),))
        token = secrets.token_urlsafe(32)
        conn.execute('DELETE FROM sessions WHERE expires<=?', (time.time(),))
        conn.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), row['id'], time.time() + 28800))
    response.set_cookie('kneura_session', token, httponly=True, samesite='strict', secure=os.getenv('KNEURA_SECURE_COOKIE') == '1', max_age=28800, path='/api')
    return public_user(row)


@app.get('/api/auth/me')
def me(account=Depends(user)):
    return public_user(account)


@app.post('/api/auth/logout', status_code=204)
def logout(request: Request, response: Response):
    with db() as conn:
        conn.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(request.cookies.get('kneura_session', '').encode()).hexdigest(),))
    response.delete_cookie('kneura_session', path='/api')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'KNEURA', 'mode': 'research-mvp', 'worker_ready': bool(getattr(app.state, 'worker_ready', False))}


@app.get('/api/cases')
def list_cases(account=Depends(user)):
    with db() as conn:
        items = [json.loads(row['document']) for row in conn.execute('SELECT document FROM cases')]
    return [visible(case, account) for case in items if authorized(case, account)]


@app.get('/api/cases/{case_id}')
def case_detail(case_id: str, account=Depends(user)):
    return visible(get_case(case_id), account)


@app.post('/api/integration/cases', tags=['Hospital Integration Adapter Demo'])
@app.post('/api/cases')
def upload(files: list[UploadFile] = File(...), patient_name: str | None = Form(None, max_length=120), patient_age: int | None = Form(None, ge=0, le=130), patient_gender: str | None = Form(None), account=Depends(radiologist)):
    supplied = any(value is not None for value in (patient_name, patient_age, patient_gender))
    if supplied and (not patient_name or not patient_name.strip() or patient_age is None or patient_gender not in ('Female', 'Male', 'Non-binary', 'Other', 'Prefer not to say')):
        raise HTTPException(422, 'Provide patient name, age (0-130), and gender.')
    if len(files) > 5000:
        raise HTTPException(413, 'Too many files.')
    payloads, size = [], 0
    for file in files:
        data = file.file.read(MAX_BYTES - size + 1)
        size += len(data)
        if size > MAX_BYTES:
            raise HTTPException(413, 'Study uploads are limited to 512 MB.')
        payloads.append((file.filename or 'image.dcm', data))
    case_id = 'KN-' + uuid.uuid4().hex[:12].upper()
    directory = DATA / 'studies' / case_id
    try:
        study, series = ingest(payloads, case_id, directory)
        patient = dict(patient_id=study['patientId'], display_id=study['patientId'], sex=study.pop('patientSex', ''))
        age = study.pop('patientAge', '')
        if len(age) == 4 and age.endswith('Y') and age[:3].isdigit():
            patient['age'] = int(age[:3])
        if supplied:
            study['patientName'] = patient_name.strip()
            patient.update(name=patient_name.strip(), age=patient_age, gender=patient_gender,
                           demographicsSource='Entered at upload', enteredBy=account['id'], enteredAt=now())
        case = dict(id=case_id, study=study, patient=patient, series=series, findings=[], audit=[], status='RECEIVED', createdAt=now(), updatedAt=now())
        event(case, 'MRI received and DICOM images validated', account['name'], actor_id=account['id'], current='RECEIVED')
        event(case, f"Series selection: {sum(s['eligible'] for s in series)} eligible of {len(series)} series", 'KNEE-AI ingestion')
        save_case(case)
    except Exception as exc:
        # Directory is an internally generated case UUID under the data root.
        if directory.exists():
            shutil.rmtree(directory)
        if isinstance(exc, ValueError):
            raise HTTPException(422, str(exc)) from exc
        LOG.exception('DICOM ingestion failed')
        raise HTTPException(422, 'Study ingestion failed. Check the DICOM package and server log.') from exc
    return case


def run_analysis(case_id):
    try:
        case = get_case(case_id)
        findings, summary = analyze(case, DATA / 'studies' / case_id, DATA / 'checkpoints')
        with LOCK:
            case = get_case(case_id)
            case['findings'], case['analysis'], case['status'] = findings, summary, 'AI_READY'
            case.pop('analysisError', None)
            event(case, f"AI analysis completed: {summary['windowsEvaluated']} windows, 12 findings and Grad-CAM evidence", 'KNEE-AI 3.3')
            event(case, 'AI findings generated: 12 canonical outputs', 'KNEE-AI 3.3', object_id=summary['id'], current='AI_READY')
            save_case(case)
    except Exception:
        LOG.exception('Analysis failed for %s', case_id)
        with LOCK:
            case = get_case(case_id)
            case['status'] = 'ERROR'
            case['analysisError'] = 'Analysis failed. Check eligible series, checkpoint compatibility and the server log, then retry.'
            event(case, 'AI analysis failed; no predictions published', 'KNEE-AI 3.3')
            save_case(case)


@app.post('/api/cases/{case_id}/analysis')
def start_analysis(case_id: str, tasks: BackgroundTasks, account=Depends(radiologist)):
    with LOCK:
        case = get_case(case_id)
        if case['status'] not in ('RECEIVED', 'ERROR'):
            raise HTTPException(409, 'Analysis can start only for a received or failed study.')
        if not any(s['eligible'] and len(s['images']) >= 5 for s in case['series']):
            raise HTTPException(422, 'No eligible series with at least five slices. Upload a package with series.csv eligibility flags.')
        case['status'] = 'PROCESSING'
        case.pop('analysisError', None)
        event(case, 'AI analysis started', account['name'], actor_id=account['id'], current='PROCESSING')
        save_case(case)
        tasks.add_task(run_analysis, case_id)
        return case


class Decision(BaseModel):
    status: str


@app.post('/api/cases/{case_id}/findings/{finding_id}/decision')
def decide(case_id: str, finding_id: str, body: Decision, account=Depends(radiologist)):
    with LOCK:
        case = get_case(case_id)
        if case.get('report') or case.get('reportJob', {}).get('status') in report_jobs.ACTIVE or case['status'] not in ('AI_READY', 'REVIEWING'):
            raise HTTPException(409, 'Finding decisions are unavailable or locked after draft generation.')
        finding = next((f for f in case['findings'] if f['id'] == finding_id), None)
        if not finding:
            raise HTTPException(404, 'Finding unavailable.')
        if body.status not in ('APPROVED', 'REJECTED'):
            raise HTTPException(422, 'Decision must be APPROVED or REJECTED.')
        previous = dict(status=finding['status'], decision=deepcopy(finding.get('decision')))
        finding['status'] = body.status
        finding['decision'] = dict(status=body.status, userName=account['name'], userId=account['id'], timestamp=now())
        case['status'] = 'REVIEWING'
        event(case, finding['name'] + ': ' + body.status, account['name'], actor_id=account['id'], object_id=finding_id, previous=previous, current=finding['decision'])
        save_case(case)
        return case


class Generate(BaseModel):
    approvedFindingIds: list[str]


@app.post('/api/cases/{case_id}/report')
def generate(case_id: str, body: Generate, account=Depends(radiologist)):
    with LOCK:
        case = get_case(case_id)
        if case.get('report') or case.get('reportJob', {}).get('status') in report_jobs.ACTIVE:
            raise HTTPException(409, 'A report or active report job already exists.')
        try:
            approved = approved_findings(case)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        ids = [f['id'] for f in approved]
        if len(body.approvedFindingIds) != len(ids) or set(body.approvedFindingIds) != set(ids):
            raise HTTPException(422, 'Report input must contain exactly the server-approved finding IDs.')
        try:
            text, statements, provider = compose(approved)
        except Exception as exc:
            LOG.exception('Report provider failed')
            event(case, 'Draft generation failed; no draft saved', account['name'], actor_id=account['id'])
            save_case(case)
            raise HTTPException(502, 'Report provider failed validation. No draft was saved.') from exc
        case['report'] = dict(id=uuid.uuid4().hex, status='DRAFT', findings=text,
            impression='Radiologist interpretation required before final approval.', updatedAt=now(), statements=statements,
            provider=provider, version=1, approvedFindingIds=ids, revisions=[],
            createdBy=account['name'], createdById=account['id'], createdAt=now())
        case['status'] = 'DRAFT'
        event(case, 'Draft generated from approved findings only · ' + provider, account['name'], actor_id=account['id'], object_id=case['report']['id'], current='DRAFT')
        save_case(case)
        return case


class Edit(BaseModel):
    findings: str = Field(min_length=1, max_length=20000)
    impression: str = Field(min_length=1, max_length=10000)


@app.patch('/api/cases/{case_id}/report')
def edit(case_id: str, body: Edit, account=Depends(radiologist)):
    with LOCK:
        case = get_case(case_id)
        report = case.get('report')
        if not report or report['status'] not in ('DRAFT', 'UNDER_REVIEW'):
            raise HTTPException(409, 'Only a draft can be edited.')
        if not body.findings.strip() or not body.impression.strip():
            raise HTTPException(422, 'Findings and impression cannot be blank.')
        report['revisions'].append({key: deepcopy(report[key]) for key in ('version', 'findings', 'impression', 'statements', 'updatedAt', 'status')})
        report['revisions'][-1].update(editor=report.get('editedBy', report.get('createdBy')), editorId=report.get('editedById', report.get('createdById')))
        report['statements'] = edited_statements(body.findings, body.impression, approved_findings(case), report['statements'])
        report.update(findings=body.findings, impression=body.impression, updatedAt=now(), version=report['version'] + 1,
                      editedBy=account['name'], editedById=account['id'], reviewedAt=now(), reviewedById=account['id'], status='UNDER_REVIEW')
        event(case, f"Draft edited · revision {report['version']} · authored statements require final review", account['name'], actor_id=account['id'], object_id=report['id'], previous=report['version'] - 1, current=report['version'])
        save_case(case)
        return case


@app.post('/api/cases/{case_id}/report/finalize')
def finalize(case_id: str, account=Depends(radiologist)):
    with LOCK:
        case = get_case(case_id)
        report = case.get('report')
        if not report or report['status'] not in ('DRAFT', 'UNDER_REVIEW'):
            raise HTTPException(409, 'Only a draft can be finalized.')
        try:
            approved_findings(case)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if report['status'] != 'UNDER_REVIEW' or not report.get('reviewedAt'):
            raise HTTPException(422, 'Review and save the report before final approval.')
        if report['impression'] == 'Radiologist interpretation required before final approval.':
            raise HTTPException(422, 'Write and save the radiologist impression before final approval.')
        report.update(status='FINAL', approvedBy=account['name'], approvedById=account['id'], approvedAt=now(), updatedAt=now())
        case['status'] = 'FINAL'
        event(case, 'Final report approved and released to authorized clinical users', account['name'], actor_id=account['id'], object_id=report['id'], previous='UNDER_REVIEW', current='FINAL')
        save_case(case)
        return visible(get_case(case_id), account)


@app.get('/api/cases/{case_id}/images/{filename}')
def image(case_id: str, filename: str, account=Depends(user)):
    case = get_case(case_id)
    if not authorized(case, account) or account['role'] == 'patient':
        raise HTTPException(404, 'Image unavailable.')
    allowed = {image['id'] + '.png' for series in case['series'] for image in series['images']}
    allowed.update(f['id'] + '.png' for f in case['findings'] if account['role'] == 'radiologist' or f['status'] == 'APPROVED')
    if filename not in allowed:
        raise HTTPException(404, 'Image unavailable.')
    path = DATA / 'studies' / case_id / 'images' / filename
    if not path.is_file():
        raise HTTPException(404, 'Image unavailable.')
    return FileResponse(path, media_type='image/png')


@app.get('/api/model')
def model_info(account=Depends(radiologist)):
    try:
        return metadata(DATA / 'checkpoints')
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get('/api/validation')
def validation(account=Depends(radiologist)):
    root = Path(__file__).resolve().parents[1]
    performance = json.loads((root / '02_PERFORMANCE/KNEE_AI_3_3_PERFORMANCE_EVIDENCE.json').read_text())
    lock = json.loads((root / '01_MODEL/KNEE_AI_3_3_MODEL_REPRODUCIBILITY_LOCK.json').read_text())
    return dict(studies=performance['validation_studies'], windows=performance['validation_windows'],
                series=lock['performance']['validation_series'], macroAuroc=performance['macro_auroc'], evaluatedAt='Date not supplied',
                source='Supplied model performance evidence; not independently reproduced',
                limitations='Small internal evaluation, not clinical diagnostic accuracy or external validation.')


@app.get('/api/integration/cases/{case_id}/result', tags=['Hospital Integration Adapter Demo'])
@app.get('/api/cases/{case_id}/export')
def export(case_id: str, account=Depends(user)):
    case = visible(get_case(case_id), account)
    if case['status'] != 'FINAL':
        raise HTTPException(409, 'Only finalized reports can be exported.')
    case['findings'] = [f for f in case['findings'] if f['status'] == 'APPROVED']
    case['report'].pop('revisions', None)
    return dict(integration_mode='MVP demonstration adapter; no PACS/RIS/EHR transport', schema_version='kneura.integration.v1', case_id=case['id'], study=case['study'], findings=case['findings'],
                radiologist_status='APPROVED', report_status='FINAL', report=case['report'])


@app.get('/api/system/llm/health')
@app.get('/api/v1/system/llm/health')
def llm_health(account=Depends(radiologist)):
    return narrative.health()


class PermittedContext(BaseModel):
    age: int | None = Field(default=None, ge=0, le=120)
    sex: str = Field(default='', max_length=30)
    laterality: str = Field(default='', max_length=30)
    indication: str = Field(default='', max_length=2000)


class NarrativeRequest(Generate):
    requestId: str | None = Field(default=None, min_length=8, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    clinical_context: PermittedContext = Field(default_factory=PermittedContext)


def narrative_request_fingerprint(body):
    from .audit import digest
    return digest(dict(ids=sorted(body.approvedFindingIds), context=body.clinical_context.model_dump()))


@app.post('/api/cases/{case_id}/report-jobs', status_code=202)
def queue_report(case_id: str, body: NarrativeRequest, tasks: BackgroundTasks, account=Depends(radiologist)):
    with LOCK:
        case = get_case(case_id)
        previous_job = case.get('reportJob', {})
        if body.requestId and previous_job.get('idempotencyKey') == body.requestId:
            if previous_job.get('requestFingerprint') != narrative_request_fingerprint(body):
                raise HTTPException(409, 'Idempotency key was already used with different input.')
            return dict(job_id=previous_job['id'], status=previous_job['status'])
        if case.get('report') or case.get('reportJob', {}).get('status') in report_jobs.ACTIVE:
            raise HTTPException(409, 'A report or active generation job already exists.')
        try:
            payload = narrative.build_input(case, body.clinical_context.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        ids = [f['id'] for f in payload['approved_findings']]
        if len(ids) != len(body.approvedFindingIds) or set(ids) != set(body.approvedFindingIds):
            raise HTTPException(422, 'Report input must exactly match server-approved findings.')
        try:
            if not narrative.configuration()['configured']:
                raise ValueError('LLM unavailable. Configure endpoint and model before starting a narrative job.')
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
        if case.get('reportJob'):
            case.setdefault('reportJobHistory', []).append(deepcopy(case['reportJob']))
        job = dict(id=uuid.uuid4().hex, status='QUEUED', createdAt=now(), updatedAt=now(),
                   actorId=account['id'], idempotencyKey=body.requestId, requestFingerprint=narrative_request_fingerprint(body), decisionFingerprint=report_jobs.fingerprint(case), input=payload)
        case['reportJob'] = job
        event(case, 'LLM narrative report job queued', account['name'], actor_id=account['id'], object_id=job['id'], current='QUEUED')
        save_case(case)
        tasks.add_task(report_jobs.run, sys.modules[__name__], case_id, job['id'], payload, account)
        return dict(job_id=job['id'], status='QUEUED')


@app.get('/api/cases/{case_id}/report-jobs/{job_id}')
def report_job(case_id: str, job_id: str, account=Depends(radiologist)):
    job = get_case(case_id).get('reportJob', {})
    if job.get('id') != job_id:
        raise HTTPException(404, 'Report job unavailable.')
    return job


@app.get('/api/v1/audit/{case_id}/verify')
def audit_integrity(case_id: str, account=Depends(radiologist)):
    return verify_audit(get_case(case_id))


class AttachEvidence(BaseModel):
    findingId: str
    evidenceId: str
    version: int


@app.post('/api/cases/{case_id}/report/statements/{statement_id}/evidence')
def attach_evidence(case_id: str, statement_id: str, body: AttachEvidence, account=Depends(radiologist)):
    with LOCK:
        case = get_case(case_id)
        report = case.get('report')
        if not report or report['status'] == 'FINAL' or report['version'] != body.version:
            raise HTTPException(409, 'Only the current non-final report revision can receive evidence.')
        statement = next((s for s in report['statements'] if s['id'] == statement_id), None)
        finding = next((f for f in case['findings'] if f['id'] == body.findingId and f['status'] == 'APPROVED'), None)
        if not statement or statement.get('source') not in ('radiologist-authored', 'radiologist-linked'):
            raise HTTPException(422, 'Select a radiologist-authored statement.')
        if not finding or not finding.get('evidence') or finding['evidence'].get('id') != body.evidenceId:
            raise HTTPException(422, 'Select existing evidence from an approved finding in this case.')
        report['revisions'].append({k: deepcopy(v) for k, v in report.items() if k != 'revisions'})
        statement.update(source='radiologist-linked', findingIds=sorted(set(statement['findingIds'] + [finding['id']])),
                         evidenceIds=sorted(set(statement.get('evidenceIds', []) + [body.evidenceId])),
                         attachedById=account['id'], attachedBy=account['name'], attachedAt=now())
        report.update(version=report['version']+1, updatedAt=now(), editedBy=account['name'], editedById=account['id'], status='UNDER_REVIEW', reviewedAt=now(), reviewedById=account['id'])
        event(case, 'Radiologist explicitly attached statement evidence', account['name'], actor_id=account['id'], object_id=statement_id, current=dict(findingId=body.findingId, evidenceId=body.evidenceId, version=report['version']))
        save_case(case)
        return case


@app.get('/api/cases/{case_id}/source-images/{image_id}')
def source_image(case_id: str, image_id: str, width: float | None = Query(default=None, ge=1, le=1e9),
                 center: float | None = Query(default=None, ge=-1e9, le=1e9),
                 finding: str | None = None, opacity: float = Query(default=.45, ge=0, le=1), account=Depends(user)):
    case = get_case(case_id)
    if not authorized(case, account) or account['role'] == 'patient':
        raise HTTPException(404, 'Image unavailable.')
    source = next(((s, i) for s in case['series'] for i in s['images'] if i['id'] == image_id), None)
    if not source:
        raise HTTPException(404, 'Image unavailable.')
    cam_path = None
    if finding:
        f = next((f for f in case['findings'] if f['id'] == finding), None)
        if not f or (account['role'] != 'radiologist' and f['status'] != 'APPROVED'):
            raise HTTPException(404, 'Evidence unavailable.')
        e = f.get('evidence', {})
        if e.get('seriesId') != source[0]['id'] or e.get('sliceStart') != source[1]['instanceNumber']:
            raise HTTPException(422, 'Grad-CAM can only overlay the first slice of its actual input window.')
        cam_path = DATA / 'studies' / case_id / 'images' / (f['id'] + '.npy')
        if not cam_path.is_file():
            raise HTTPException(404, 'Adjustable heatmap unavailable for this older analysis. Use its saved Grad-CAM evidence.')
    path = DATA / 'studies' / case_id / 'dicom' / (image_id + '.dcm')
    try:
        from .viewer import render
        return Response(render(path, width, center, cam_path, opacity), media_type='image/png')
    except Exception as exc:
        raise HTTPException(422, 'Source DICOM pixels could not be rendered.') from exc


@app.post('/api/cases/{case_id}/release-to-patient')
def release_to_patient(case_id: str, account=Depends(user)):
    if account['role'] != 'orthopedist':
        raise HTTPException(403, 'Only an orthopedist can release a case to a patient.')
    with LOCK:
        case = get_case(case_id)
        if case['status'] != 'FINAL' or case.get('report', {}).get('status') != 'FINAL':
            raise HTTPException(409, 'Case must be finalized by a radiologist first.')
        if case.get('releasedToPatient'):
            raise HTTPException(409, 'Case is already released to the patient.')
        case['releasedToPatient'] = True
        case['releasedToPatientAt'] = now()
        case['releasedToPatientBy'] = account['name']
        case['releasedToPatientById'] = account['id']
        event(case, 'Case approved and released to patient', account['name'], actor_id=account['id'], current='RELEASED_TO_PATIENT')
        save_case(case)
        return visible(case, account)


@app.get('/api/system/readiness')
def system_readiness(execute_model: bool = False, account=Depends(radiologist)):
    from .readiness import check
    return check(sys.modules[__name__], execute_model)
