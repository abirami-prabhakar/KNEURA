import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import app, get_db
from app.llm_adapter import Member2ClinicalLLMAdapter, get_llm_adapter
from app.models.report import Report
from app.models.audit_log import AuditLog
from app.models.study import Study
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding

HEADERS = {'X-Authenticated-User-Id': 'radiologist-editor', 'X-User-Role': 'RADIOLOGIST'}
ORIGINAL = '  {"status":"DRAFT","final_approval":"PENDING","findings":["ACL"]}\n'


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'reports.db'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Study(study_id='study', workflow_state='REPORT_DRAFT'))
        db.add(Prediction(study_id='study', label='ACL', confidence=0.201472851))
        review = RadiologistReview(study_id='study', reviewer_id='reviewer', decision='CONFIRMED')
        db.add(review)
        db.flush()
        db.add(ValidatedFinding(review_id=review.id, finding='ACL', outcome='CONFIRMED', details='Reviewed'))
        db.add(Report(id=1, study_id='study', author_id='original-author', status='DRAFT', draft_content=ORIGINAL))
        db.commit()

    def forbidden_llm():
        pytest.fail('Edit/approval must not request an LLM dependency')

    def forbidden_report(self, study_id, validated_findings, predictions, clinical_context=None):
        pytest.fail('Edit/approval must not generate an LLM report')

    monkeypatch.setattr(Member2ClinicalLLMAdapter, 'generate_report', forbidden_report)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_llm_adapter] = forbidden_llm
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def snapshot(factory):
    with factory() as db:
        return {
            model.__tablename__: [tuple(getattr(row, c.name) for c in model.__table__.columns)
                                  for row in db.execute(select(model).order_by(model.id)).scalars()]
            for model in (Prediction, RadiologistReview, ValidatedFinding)
        }


def test_edit_then_approve_preserves_data_and_audits(reports):
    client, factory = reports
    before = snapshot(factory)
    with factory() as db:
        created = db.get(Report, 1).created_at
    edited = '  Radiologist edited report.\nExact spacing preserved.  '
    response = client.put('/reports/1', headers=HEADERS, json={'draft_content': edited})
    assert response.status_code == 200
    assert response.json()['status'] == 'DRAFT'
    assert response.json()['draft_content'] == edited
    with factory() as db:
        row = db.get(Report, 1)
        assert row.status == 'DRAFT' and row.draft_content == edited
        assert row.author_id == 'original-author' and row.study_id == 'study'
        assert row.created_at == created
        assert len(db.execute(select(Report)).scalars().all()) == 1
    response = client.post('/reports/1/approve', headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['status'] == 'APPROVED'
    assert response.json()['draft_content'] == edited
    assert response.json()['study_id'] == 'study'
    with factory() as db:
        row = db.get(Report, 1)
        assert row.status == 'APPROVED' and row.draft_content == edited
        assert row.author_id == 'original-author' and row.created_at == created
        logs = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
        assert [(a.action, a.actor_id, a.study_id, a.details) for a in logs] == [
            ('REPORT_EDITED', 'radiologist-editor', 'study', 'report_id=1'),
            ('REPORT_APPROVED', 'radiologist-editor', 'study', 'report_id=1'),
            ('WORKFLOW_TRANSITION', 'radiologist-editor', 'study', 'from_state=REPORT_DRAFT; to_state=RADIOLOGIST_APPROVED'),
        ]
        assert len(db.execute(select(Report)).scalars().all()) == 1
    assert snapshot(factory) == before


def test_approval_preserves_structured_content_exactly(reports):
    client, factory = reports
    assert client.post('/reports/1/approve', headers=HEADERS).json()['draft_content'] == ORIGINAL
    with factory() as db:
        assert db.get(Report, 1).draft_content == ORIGINAL


@pytest.mark.parametrize('method,path', [('put', '/reports/1'), ('post', '/reports/1/approve')])
@pytest.mark.parametrize('headers,expected', [({}, 401), ({'X-Authenticated-User-Id': 'other', 'X-User-Role': 'CLINICIAN'}, 403)])
def test_unauthorized_mutations_rejected(reports, method, path, headers, expected):
    client, factory = reports
    response = client.request(method, path, headers=headers, json={'draft_content': 'change'})
    assert response.status_code == expected
    assert_unchanged(factory)


def assert_unchanged(factory):
    with factory() as db:
        row = db.get(Report, 1)
        assert row.status == 'DRAFT' and row.draft_content == ORIGINAL
        assert db.execute(select(AuditLog)).scalars().all() == []


@pytest.mark.parametrize('method,path', [('put', '/reports/999'), ('post', '/reports/999/approve')])
def test_missing_report(reports, method, path):
    client, factory = reports
    assert client.request(method, path, headers=HEADERS, json={'draft_content': 'change'}).status_code == 404
    assert_unchanged(factory)


@pytest.mark.parametrize('content', ['', '   ', '\n\t', None])
def test_empty_edit_rejected(reports, content):
    client, factory = reports
    assert client.put('/reports/1', headers=HEADERS, json={'draft_content': content}).status_code == 422
    assert_unchanged(factory)


@pytest.mark.parametrize('state', ['APPROVED', 'ARCHIVED'])
@pytest.mark.parametrize('method,path', [('put', '/reports/1'), ('post', '/reports/1/approve')])
def test_non_draft_cannot_be_edited_or_approved(reports, state, method, path):
    client, factory = reports
    with factory() as db:
        db.get(Report, 1).status = state
        db.commit()
    assert client.request(method, path, headers=HEADERS, json={'draft_content': 'change'}).status_code == 409
    with factory() as db:
        assert db.get(Report, 1).status == state
        assert db.get(Report, 1).draft_content == ORIGINAL
        assert db.execute(select(AuditLog)).scalars().all() == []
