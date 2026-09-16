import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.authentication import create_access_token
from app.models.user import User
from app.security import get_db as get_security_db
from app.llm_adapter import (
    CANONICAL_ABNORMALITIES,
    LLMIntegrationError,
    Member2ClinicalLLMAdapter,
    get_llm_adapter,
    map_backend_to_member2,
    match_canonical_abnormality,
)
from app.main import app, get_db
from app.models.audit_log import AuditLog
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.report import Report
from app.models.study import Study
from schemas.api_contract import create_llm_input


@pytest.fixture()
def m2_client(tmp_path: Path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_m2.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()

    db.add(User(id=99, email="member2-test@example.invalid", password_hash="unused", role="RADIOLOGIST"))
    monkeypatch.setitem(RADIOLOGIST_HEADERS, "Authorization", f"Bearer {create_access_token(99, 'RADIOLOGIST')}")

    db.add(Study(study_id="STUDY_M2_001", workflow_state="RADIOLOGIST_REVIEW"))
    # Four AI predictions with exact floating point probabilities
    db.add_all(
        [
            Prediction(study_id="STUDY_M2_001", label="ACL", confidence=0.201472851),
            Prediction(study_id="STUDY_M2_001", label="Lateral Meniscus", confidence=0.914285714),
            Prediction(study_id="STUDY_M2_001", label="Medial Meniscus", confidence=0.732145678),
            Prediction(study_id="STUDY_M2_001", label="Effusion", confidence=0.450123456),
        ]
    )

    review = RadiologistReview(
        study_id="STUDY_M2_001",
        reviewer_id="radiologist-99",
        decision="EDITED",
        notes="Clinical context: severe rotational instability after athletic trauma.",
    )
    db.add(review)
    db.flush()

    # Validated findings:
    # 1. Lateral Meniscus: CONFIRMED
    # 2. Medial Meniscus: EDITED with custom description
    # 3. ACL: REJECTED
    # (Effusion remains unreviewed / PENDING)
    db.add_all(
        [
            ValidatedFinding(
                review_id=review.id,
                finding="Lateral Meniscus",
                outcome="CONFIRMED",
            ),
            ValidatedFinding(
                review_id=review.id,
                finding="Complex tear of medial meniscus",
                outcome="EDITED",
                details="Posterior horn complex tear",
            ),
            ValidatedFinding(
                review_id=review.id,
                finding="ACL",
                outcome="REJECTED",
            ),
        ]
    )

    db.commit()
    db.close()

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    default_mock_llm = {
        "title": "Knee MRI Report",
        "study_id": "STUDY_M2_001",
        "status": "DRAFT",
        "findings": [
            "Lateral Meniscus abnormality.",
            "Medial Meniscus complex tear.",
        ],
        "impression": "Meniscal tears involving both lateral and medial meniscus.",
        "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
    }

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_security_db] = override_db
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(
        generate_llm_fn=lambda _prompt: default_mock_llm
    )
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()


RADIOLOGIST_HEADERS = {
    "X-Authenticated-User-Id": "radiologist-99",
    "X-User-Role": "RADIOLOGIST",
}


def test_confirmed_and_edited_mapped_to_approved_and_rejected_excluded(m2_client):
    db = m2_client[1]()
    study = db.execute(select(Study).filter_by(study_id="STUDY_M2_001")).scalar_one()
    review = db.execute(select(RadiologistReview).filter_by(study_id="STUDY_M2_001")).scalar_one()
    findings = db.execute(select(ValidatedFinding).filter_by(review_id=review.id)).scalars().all()
    predictions = db.execute(select(Prediction).filter_by(study_id="STUDY_M2_001")).scalars().all()
    db.close()

    mapped = map_backend_to_member2(
        study_id=study.study_id,
        validated_findings=findings,
        predictions=predictions,
        clinical_context=review.notes,
    )

    # 1. Check outer object
    assert mapped["study_id"] == "STUDY_M2_001"
    assert mapped["clinical_context"].startswith("Clinical context: severe rotational instability after athletic trauma.")
    assert '"outcome": "EDITED"' in mapped["clinical_context"]
    assert "Posterior horn complex tear" in mapped["clinical_context"]
    status_map = {f["abnormality"]: f["status"] for f in mapped["findings"]}
    assert status_map["Lateral Meniscus"] == "APPROVED"
    assert status_map["Medial Meniscus"] == "APPROVED"
    assert status_map["ACL"] == "REJECTED"

    # 2. Member 2 create_llm_input filters approved findings
    llm_input = create_llm_input(
        study_id=mapped["study_id"],
        validated_findings=mapped["findings"],
        clinical_context=mapped["clinical_context"],
    )

    approved = llm_input["approved_findings"]
    approved_abnormalities = [f["abnormality"] for f in approved]
    assert "Lateral Meniscus" in approved_abnormalities
    assert "Medial Meniscus" in approved_abnormalities
    assert "ACL" not in approved_abnormalities


def test_exact_probability_preservation_without_recalculation(m2_client):
    db = m2_client[1]()
    review = db.execute(select(RadiologistReview).filter_by(study_id="STUDY_M2_001")).scalar_one()
    findings = db.execute(select(ValidatedFinding).filter_by(review_id=review.id)).scalars().all()
    predictions = db.execute(select(Prediction).filter_by(study_id="STUDY_M2_001")).scalars().all()
    db.close()

    mapped = map_backend_to_member2(
        study_id="STUDY_M2_001",
        validated_findings=findings,
        predictions=predictions,
    )

    prob_map = {f["abnormality"]: f["probability"] for f in mapped["findings"]}
    # Preserves exact Model 1 probability float without rounding or recomputation
    assert prob_map["Lateral Meniscus"] == 0.914285714
    assert prob_map["ACL"] == 0.201472851
    assert prob_map["Medial Meniscus"] == 0.732145678


def test_rejected_and_unreviewed_findings_never_reach_llm_input(m2_client):
    captured_payloads = []
    default_mock_llm = {
        "title": "Knee MRI Report",
        "study_id": "STUDY_M2_001",
        "status": "DRAFT",
        "findings": [
            "Lateral Meniscus abnormality.",
            "Medial Meniscus complex tear.",
        ],
        "impression": "Meniscal tears involving both lateral and medial meniscus.",
        "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
    }

    class SpyAdapter(Member2ClinicalLLMAdapter):
        def generate_report(self, study_id, validated_findings, predictions, clinical_context=None, **boundary_context):
            mapped = map_backend_to_member2(study_id, validated_findings, predictions, clinical_context)
            llm_input = create_llm_input(study_id, mapped["findings"], clinical_context)
            captured_payloads.append(llm_input)
            return super().generate_report(study_id, validated_findings, predictions, clinical_context, **boundary_context)

    app.dependency_overrides[get_llm_adapter] = lambda: SpyAdapter(
        generate_llm_fn=lambda _p: default_mock_llm
    )

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    assert len(captured_payloads) == 1

    approved = captured_payloads[0]["approved_findings"]
    approved_names = [f["abnormality"] for f in approved]

    # REJECTED "ACL" must NOT be in approved_findings
    assert "ACL" not in approved_names
    # Unreviewed / PENDING "Effusion" must NOT be in approved_findings
    assert "Effusion" not in approved_names
    # Only the approved findings are present
    assert len(approved) == 2


def test_member2_contract_shape(m2_client):
    captured_payloads = []
    default_mock_llm = {
        "title": "Knee MRI Report",
        "study_id": "STUDY_M2_001",
        "status": "DRAFT",
        "findings": [
            "Lateral Meniscus abnormality.",
            "Medial Meniscus complex tear.",
        ],
        "impression": "Meniscal tears involving both lateral and medial meniscus.",
        "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
    }

    class SpyAdapter(Member2ClinicalLLMAdapter):
        def generate_report(self, study_id, validated_findings, predictions, clinical_context=None, **boundary_context):
            mapped = map_backend_to_member2(study_id, validated_findings, predictions, clinical_context)
            llm_input = create_llm_input(study_id, mapped["findings"], clinical_context)
            captured_payloads.append(llm_input)
            return super().generate_report(study_id, validated_findings, predictions, clinical_context, **boundary_context)

    app.dependency_overrides[get_llm_adapter] = lambda: SpyAdapter(
        generate_llm_fn=lambda _p: default_mock_llm
    )

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    llm_input = captured_payloads[0]

    assert "study_id" in llm_input
    assert "approved_findings" in llm_input
    assert "clinical_context" in llm_input

    for item in llm_input["approved_findings"]:
        assert "abnormality" in item
        assert "probability" in item
        assert isinstance(item["probability"], float)
        assert item["status"] == "APPROVED"


def test_real_study_id_and_authorized_clinical_context_preserved(m2_client):
    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["study_id"] == "STUDY_M2_001"

    parsed = json.loads(body["draft_content"])
    assert parsed["study_id"] == "STUDY_M2_001"
    assert parsed["status"] == "DRAFT"
    assert parsed["final_approval"] == "PENDING"
    assert "PatientID" not in body["draft_content"]
    assert "StudyInstanceUID" not in body["draft_content"]
    assert "SeriesInstanceUID" not in body["draft_content"]


def test_structured_draft_report_correctly_persisted_in_database(m2_client):
    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201
    report_id = response.json()["report_id"]

    db = m2_client[1]()
    report = db.execute(select(Report).filter_by(id=report_id)).scalar_one()
    db.close()

    assert report.study_id == "STUDY_M2_001"
    assert report.author_id == "99"  # Identity comes from the authenticated database user.
    assert report.status == "DRAFT"

    parsed = json.loads(report.draft_content)
    assert parsed["title"] == "Knee MRI Report"
    assert parsed["study_id"] == "STUDY_M2_001"
    assert parsed["status"] == "DRAFT"
    assert "findings" in parsed
    assert "impression" in parsed
    assert "note" in parsed
    assert parsed["final_approval"] == "PENDING"


def test_member2_safety_validation_failure_blocks_persistence(m2_client):
    # Mock LLM to return an unsafe report that hallucinates the REJECTED "ACL" finding
    unsafe_report = {
        "title": "Knee MRI Report",
        "study_id": "STUDY_M2_001",
        "status": "DRAFT",
        "findings": [
            "Lateral Meniscus abnormality.",
            "Complex tear of medial meniscus.",
            "ACL tear detected.",  # REJECTED finding hallucinated!
        ],
        "impression": "Severe ACL tear and meniscal pathology.",
        "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
    }

    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda _p: unsafe_report)
    app.dependency_overrides[get_llm_adapter] = lambda: adapter

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "safety validation failed" in response.json()["detail"].lower()

    db = m2_client[1]()
    reports = db.execute(select(Report)).scalars().all()
    db.close()
    assert len(reports) == 0


def test_member2_treatment_recommendation_detection_blocks_persistence(m2_client):
    # Mock LLM to return an unsafe report that contains forbidden treatment recommendations
    unsafe_report = {
        "title": "Knee MRI Report",
        "study_id": "STUDY_M2_001",
        "status": "DRAFT",
        "findings": [
            "Lateral Meniscus abnormality.",
            "Complex tear of medial meniscus.",
        ],
        "impression": "Meniscal pathology. Surgery is recommended.",  # Prohibited!
        "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
    }

    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda _p: unsafe_report)
    app.dependency_overrides[get_llm_adapter] = lambda: adapter

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "safety validation failed" in response.json()["detail"].lower()

    db = m2_client[1]()
    reports = db.execute(select(Report)).scalars().all()
    db.close()
    assert len(reports) == 0


def test_provider_failure_returns_503_and_creates_no_report(m2_client):
    def failing_llm(_prompt):
        raise RuntimeError("503 Service Unavailable: Gemini model overloaded")

    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=failing_llm)
    app.dependency_overrides[get_llm_adapter] = lambda: adapter

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "provider failure" in response.json()["detail"].lower()

    db = m2_client[1]()
    reports = db.execute(select(Report)).scalars().all()
    db.close()
    assert len(reports) == 0


def test_deterministic_l4_failure_handling_unit_test():
    """Unit test verifying Member 2's L4 failure handling deterministically without live Gemini."""
    def simulated_failing_gemini(_prompt):
        raise RuntimeError("503 Server Unavailable")

    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=simulated_failing_gemini)
    with pytest.raises(LLMIntegrationError) as exc_info:
        adapter.generate_report(
            study_id="TEST_STUDY",
            validated_findings=[{"finding": "MCL", "outcome": "CONFIRMED"}],
            predictions=[{"label": "MCL", "confidence": 0.88}],
        )
    assert "503" in str(exc_info.value)


def test_ai_predictions_and_review_data_remain_strictly_immutable(m2_client):
    db = m2_client[1]()
    preds_before = [
        (p.id, p.study_id, p.label, p.confidence)
        for p in db.execute(select(Prediction).order_by(Prediction.id)).scalars()
    ]
    review_before = [
        (r.id, r.study_id, r.reviewer_id, r.decision, r.notes)
        for r in db.execute(select(RadiologistReview)).scalars()
    ]
    findings_before = [
        (f.id, f.review_id, f.finding, f.outcome, f.details)
        for f in db.execute(select(ValidatedFinding).order_by(ValidatedFinding.id)).scalars()
    ]
    db.close()

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 201

    db = m2_client[1]()
    preds_after = [
        (p.id, p.study_id, p.label, p.confidence)
        for p in db.execute(select(Prediction).order_by(Prediction.id)).scalars()
    ]
    review_after = [
        (r.id, r.study_id, r.reviewer_id, r.decision, r.notes)
        for r in db.execute(select(RadiologistReview)).scalars()
    ]
    findings_after = [
        (f.id, f.review_id, f.finding, f.outcome, f.details)
        for f in db.execute(select(ValidatedFinding).order_by(ValidatedFinding.id)).scalars()
    ]
    db.close()

    assert preds_after == preds_before
    assert review_after == review_before
    assert findings_after == findings_before


def test_missing_gemini_api_key_raises_503_and_creates_no_report(m2_client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter()

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "GEMINI_API_KEY is not configured" in response.json()["detail"]

    db = m2_client[1]()
    reports = db.execute(select(Report)).scalars().all()
    db.close()
    assert len(reports) == 0


def test_unmappable_edited_finding_raises_503_and_creates_no_report(m2_client):
    db = m2_client[1]()
    db.add(Study(study_id="STUDY_UNMAPPABLE", workflow_state="RADIOLOGIST_REVIEW"))
    db.add(Prediction(study_id="STUDY_UNMAPPABLE", label="ACL", confidence=0.5))
    review = RadiologistReview(
        study_id="STUDY_UNMAPPABLE",
        reviewer_id="radiologist-99",
        decision="CONFIRMED",
    )
    db.add(review)
    db.flush()
    db.add(
        ValidatedFinding(
            review_id=review.id,
            finding="Atypical ganglion cyst in calf muscle",
            outcome="EDITED",
        )
    )
    db.commit()
    db.close()

    response = m2_client[0].post(
        "/studies/STUDY_UNMAPPABLE/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "Cannot map finding" in response.json()["detail"]

    db = m2_client[1]()
    reports = db.execute(select(Report).filter_by(study_id="STUDY_UNMAPPABLE")).scalars().all()
    db.close()
    assert len(reports) == 0


def test_schema_validation_failure_on_malformed_llm_response_blocks_persistence(m2_client):
    # LLM returns report missing required field 'impression' and with invalid status
    malformed_report = {
        "title": "Knee MRI Report",
        "study_id": "STUDY_M2_001",
        "status": "FINAL",  # Invalid status: schema validator requires DRAFT
        "findings": ["Lateral Meniscus abnormality."],
        "note": "Note.",
    }
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda _p: malformed_report)
    app.dependency_overrides[get_llm_adapter] = lambda: adapter

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "schema validation failed" in response.json()["detail"].lower()

    db = m2_client[1]()
    reports = db.execute(select(Report)).scalars().all()
    db.close()
    assert len(reports) == 0


def test_missing_approved_finding_in_llm_output_triggers_safety_failure(m2_client):
    # LLM output omits approved "Lateral Meniscus" finding
    incomplete_report = {
        "title": "Knee MRI Report",
        "study_id": "STUDY_M2_001",
        "status": "DRAFT",
        "findings": ["Medial Meniscus complex tear."],
        "impression": "Medial meniscal pathology.",
        "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval.",
    }
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda _p: incomplete_report)
    app.dependency_overrides[get_llm_adapter] = lambda: adapter

    response = m2_client[0].post(
        "/studies/STUDY_M2_001/generate-report",
        headers=RADIOLOGIST_HEADERS,
    )
    assert response.status_code == 503
    assert "safety validation failed" in response.json()["detail"].lower()

    db = m2_client[1]()
    reports = db.execute(select(Report)).scalars().all()
    db.close()
    assert len(reports) == 0


def test_cannot_fabricate_probability_when_canonical_prediction_missing():
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda _p: {})
    with pytest.raises(LLMIntegrationError) as exc_info:
        adapter.generate_report(
            study_id="TEST_STUDY",
            validated_findings=[{"finding": "Fracture", "outcome": "CONFIRMED"}],
            predictions=[{"label": "ACL", "confidence": 0.88}],
        )
    assert "No Model 1 prediction found" in str(exc_info.value)


@pytest.mark.parametrize('text, expected', [
    ('Complex tear of medial meniscus', 'Medial Meniscus'),
    ('ACL injury', 'ACL'),
    ('anterior cruciate ligament ACL injury', 'ACL'),
])
def test_unique_canonical_matching(text, expected):
    assert match_canonical_abnormality(text) == expected


@pytest.mark.parametrize('text', ['unknown abnormality', 'subfracturelike', '', None])
def test_unknown_canonical_matching_raises_at_matcher(text):
    with pytest.raises(LLMIntegrationError, match='Cannot map'):
        match_canonical_abnormality(text)


@pytest.mark.parametrize('text', ['ACL and MCL abnormalities', 'ACL and medial meniscus tear'])
def test_ambiguous_mapping_never_calls_provider(text):
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    with pytest.raises(LLMIntegrationError, match='Ambiguous'):
        adapter.generate_report('study', [{'finding': text, 'outcome': 'EDITED'}], [])
    assert calls == []


@pytest.mark.parametrize('finding, predictions, error', [
    ('unknown', [], 'Cannot map'),
    ('ACL', [], 'No Model 1 prediction'),
    ('ACL', [{'label': 'ACL', 'confidence': 0.2}, {'label': 'ACL', 'confidence': 0.3}], 'Duplicate'),
    ('ACL', [{'label': 'ACL', 'confidence': float('nan')}], 'Invalid'),
])
def test_mapping_failure_never_calls_provider(finding, predictions, error):
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    with pytest.raises(LLMIntegrationError, match=error):
        adapter.generate_report('study', [{'finding': finding, 'outcome': 'EDITED'}], predictions)
    assert calls == []


def _valid_report():
    return {
        'title': 'Knee MRI Report', 'study_id': 'STUDY_M2_001', 'status': 'DRAFT',
        'findings': ['Lateral Meniscus abnormality.', 'Medial Meniscus complex tear.'],
        'impression': 'Meniscal abnormalities.',
        'note': 'Requires radiologist review and final approval.',
    }


def test_provider_once_receives_only_authorized_prompt_and_preserves_edits(m2_client):
    calls = []
    def provider(prompt):
        calls.append(prompt)
        result = _valid_report()
        result['final_approval'] = 'APPROVED'
        return result
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(generate_llm_fn=provider)
    with m2_client[1]() as db:
        review = db.execute(select(RadiologistReview)).scalar_one()
        db.add(ValidatedFinding(review_id=review.id, finding='Effusion', outcome='PENDING', details='PRIVATE_PENDING_DETAIL'))
        db.commit()
    response = m2_client[0].post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 201
    assert len(calls) == 1
    prompt = calls[0]
    assert isinstance(prompt, str)
    for excluded in ['Effusion', 'PRIVATE_PENDING_DETAIL', "'abnormality': 'ACL'", '0.201472851', 'PatientID', 'StudyInstanceUID', 'SeriesInstanceUID', 'Prediction object']:
        assert excluded not in prompt
    for included in ['0.914285714', '0.732145678', 'EDITED', 'Posterior horn complex tear']:
        assert included in prompt
    stored = json.loads(response.json()['draft_content'])
    assert stored['study_id'] == 'STUDY_M2_001'
    assert stored['status'] == 'DRAFT'
    assert stored['final_approval'] == 'PENDING'


@pytest.mark.parametrize('outcome', ['PENDING', None])
def test_pending_and_unreviewed_excluded_without_probability_lookup(outcome):
    mapped = map_backend_to_member2('study', [{'finding': 'Effusion', 'outcome': outcome}], [])
    assert create_llm_input('study', mapped['findings'], mapped['clinical_context'])['approved_findings'] == []


@pytest.mark.parametrize('extra', ['Effusion detected.', 'Fracture detected.'])
def test_unapproved_canonical_output_uses_member2_safety_and_no_persistence(m2_client, extra):
    from services.report_schema_validator import validate_report_schema
    result = _valid_report()
    result['findings'].append(extra)
    assert validate_report_schema(result, 'STUDY_M2_001')[0]
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: result)
    response = m2_client[0].post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 503
    assert 'safety validation failed' in response.json()['detail']
    with m2_client[1]() as db:
        assert db.execute(select(Report)).scalars().all() == []
        assert db.execute(select(AuditLog).filter_by(action='DRAFT_REPORT_GENERATED')).scalars().all() == []


@pytest.mark.parametrize('failure', ['missing_key', 'missing_dependency'])
def test_production_configuration_fails_before_provider_import(m2_client, monkeypatch, failure):
    import builtins
    original_import = builtins.__import__
    imports = []
    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'services.llm_service':
            imports.append(name)
            raise ModuleNotFoundError('google.genai is unavailable')
        return original_import(name, globals, locals, fromlist, level)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    if failure == 'missing_key':
        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    else:
        monkeypatch.setenv('GEMINI_API_KEY', 'test-key-not-sent')
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter()
    response = m2_client[0].post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 503
    assert len(imports) == (0 if failure == 'missing_key' else 1)
    with m2_client[1]() as db:
        assert db.execute(select(Report)).scalars().all() == []


@pytest.mark.parametrize('confidence', [float('inf'), float('-inf'), -0.01, 1.01, '0.5', 1, True, None])
def test_invalid_confidence_never_calls_provider(confidence):
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    with pytest.raises(LLMIntegrationError, match='Invalid Model 1 confidence'):
        adapter.generate_report('study', [{'finding': 'ACL', 'outcome': 'CONFIRMED'}],
                                [{'label': 'ACL', 'confidence': confidence}])
    assert calls == []


def test_valid_json_string_is_validated_and_persisted(m2_client):
    result = _valid_report()
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(
        generate_llm_fn=lambda prompt: json.dumps(result))
    response = m2_client[0].post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 201
    stored = json.loads(response.json()['draft_content'])
    assert stored == dict(result, final_approval='PENDING')
    with m2_client[1]() as db:
        assert len(db.execute(select(Report)).scalars().all()) == 1


@pytest.mark.parametrize('payload, error', [
    ('{broken', 'invalid JSON'),
    ('[]', 'invalid report format'),
    ('null', 'invalid report format'),
    ('{}', 'schema validation failed'),
])
def test_invalid_json_or_json_shape_never_persists(m2_client, payload, error):
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(
        generate_llm_fn=lambda prompt: payload)
    response = m2_client[0].post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 503
    assert error in response.json()['detail']
    with m2_client[1]() as db:
        assert db.execute(select(Report)).scalars().all() == []


def test_json_string_still_runs_member2_safety_validation(m2_client):
    from services.report_schema_validator import validate_report_schema
    result = _valid_report()
    result['findings'].append('ACL tear.')
    assert validate_report_schema(result, 'STUDY_M2_001')[0]
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(
        generate_llm_fn=lambda prompt: json.dumps(result))
    response = m2_client[0].post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 503
    assert 'safety validation failed' in response.json()['detail']
    with m2_client[1]() as db:
        assert db.execute(select(Report)).scalars().all() == []


@pytest.mark.parametrize('canonical', CANONICAL_ABNORMALITIES)
def test_every_canonical_name_maps_to_itself(canonical):
    assert match_canonical_abnormality(canonical) == canonical


def test_missing_member2_returns_actionable_api_error_without_persistence(m2_client, monkeypatch, tmp_path):
    from app import llm_adapter
    missing = tmp_path / 'missing-member2'
    monkeypatch.setattr(llm_adapter, 'MEMBER2_DIR', missing)
    monkeypatch.setattr(llm_adapter, 'MEMBER2_IMPORT_ERROR', ModuleNotFoundError(str(missing)))
    response = m2_client[0].post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 503
    assert str(missing) in response.json()['detail']
    assert 'KNEE_AI_MEMBER2_PATH' in response.json()['detail']
    with m2_client[1]() as db:
        assert db.execute(select(Report)).scalars().all() == []


@pytest.mark.parametrize('failure', [None, 'unsafe', 'missing_runtime'])
def test_authenticated_patient_explanation_preserves_review_state(m2_client, monkeypatch, failure):
    from app import llm_adapter
    client, factory = m2_client
    assert client.post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS).status_code == 201
    explanation = {
        'title': 'Patient-Friendly MRI Explanation', 'study_id': 'STUDY_M2_001',
        'approved_findings': 'Medial Meniscus and Lateral Meniscus abnormalities.',
        'what_this_means': 'Changes in the knee cartilage.',
        'important_note': 'Based on radiologist-approved information. Discuss with your doctor.',
    }
    if failure == 'unsafe':
        explanation['what_this_means'] = 'ACL tear.'
    elif failure == 'missing_runtime':
        monkeypatch.setattr(llm_adapter, 'MEMBER2_IMPORT_ERROR', ModuleNotFoundError('missing package'))
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(
        generate_llm_fn=lambda prompt: explanation)
    response = client.post('/studies/STUDY_M2_001/patient-explanation', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == (503 if failure else 200)
    if failure == 'missing_runtime':
        assert 'KNEE_AI_MEMBER2_PATH' in response.json()['detail']
    with factory() as db:
        report = db.execute(select(Report)).scalar_one()
        assert report.status == 'DRAFT'
        assert json.loads(report.draft_content)['final_approval'] == 'PENDING'
        if failure:
            assert not report.patient_explanation
        else:
            assert json.loads(report.patient_explanation) == explanation


def test_complete_ai_review_still_required_before_member2(m2_client):
    client, factory = m2_client
    with factory() as db:
        existing = set(db.execute(select(Prediction.label)).scalars())
        db.add_all(Prediction(study_id='STUDY_M2_001', label=name, confidence=0.1)
                   for name in CANONICAL_ABNORMALITIES if name not in existing)
        db.commit()
    calls = []
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(
        generate_llm_fn=lambda prompt: calls.append(prompt))
    response = client.post('/studies/STUDY_M2_001/generate-report', headers=RADIOLOGIST_HEADERS)
    assert response.status_code == 409
    assert calls == []
    with factory() as db:
        assert db.execute(select(Report)).scalars().all() == []
