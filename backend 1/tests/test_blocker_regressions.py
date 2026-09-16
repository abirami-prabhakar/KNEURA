"""Regressions for complete AI review and the de-identified Member 2 boundary."""

import ast
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.llm_adapter import (
    CANONICAL_ABNORMALITIES as LABELS,
    LLMIntegrationError,
    Member2ClinicalLLMAdapter,
    get_llm_adapter,
    map_backend_to_member2,
)
from app.main import app, get_db
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.report import Report
from app.models.study import Study

HEADERS = {"X-Authenticated-User-Id": "audit-radiologist", "X-User-Role": "RADIOLOGIST"}
STUDY_UID = "1.2.826.0.1.3680043.8.498.987654321"
SERIES_UID = "1.2.826.0.1.3680043.8.498.123456789"
PATIENT_ID = "PRIVATE-PATIENT-471"


def provider_response(prompt):
    study_id = prompt.split("STUDY ID:\n", 1)[1].splitlines()[0]
    approved = ast.literal_eval(prompt.split("RADIOLOGIST-APPROVED FINDINGS:\n", 1)[1].splitlines()[0])
    findings = [item["abnormality"] for item in approved]
    if "patient-friendly explanation assistant" in prompt:
        return {
            "title": "Patient-Friendly MRI Explanation",
            "study_id": study_id,
            "approved_findings": ", ".join(findings),
            "what_this_means": "Based on the radiologist review.",
            "important_note": "Discuss these findings with your doctor.",
        }
    return {
        "title": "Knee MRI Report", "study_id": study_id, "status": "DRAFT",
        "findings": findings, "impression": ", ".join(findings),
        "note": "Draft requires radiologist review and approval.",
    }


@pytest.fixture()
def boundary_client(request):
    study_id = getattr(request, "param", "audit-study")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Study(study_id=study_id, patient_id=PATIENT_ID, workflow_state="AI_COMPLETE"))
        db.add_all([Prediction(study_id=study_id, label=label, confidence=0.02 * (i + 1)) for i, label in enumerate(LABELS)])
        db.commit()

    captured = []

    def provider(prompt):
        captured.append(prompt)
        return provider_response(prompt)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(generate_llm_fn=provider)
    try:
        with TestClient(app) as client:
            yield client, factory, captured, study_id
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def submit(boundary_client, findings, decision="MIXED", notes=None):
    client, _, _, study_id = boundary_client
    return client.post(f"/studies/{study_id}/review", headers=HEADERS,
                       json={"decision": decision, "validated_findings": findings, "notes": notes})


def generate(boundary_client):
    return boundary_client[0].post(f"/studies/{boundary_client[3]}/generate-report", headers=HEADERS)


def decisions(outcome="CONFIRMED", omitted=None):
    return [{"finding": label, "outcome": outcome} for label in LABELS if label != omitted]


@pytest.mark.parametrize("outcome", ["CONFIRMED", "APPROVED", "EDITED", "REJECTED"])
def test_all_twelve_explicit_decisions_allow_draft(boundary_client, outcome):
    assert submit(boundary_client, decisions(outcome), outcome).status_code == 201
    result = generate(boundary_client)
    assert result.status_code == 201, result.text
    assert result.json()["status"] == "DRAFT"
    assert json.loads(result.json()["draft_content"])["final_approval"] == "PENDING"
    assert len(boundary_client[2]) == 1


@pytest.mark.parametrize("outcome", ["CONFIRMED", "APPROVED", "EDITED", "REJECTED"])
@pytest.mark.parametrize("missing", LABELS)
def test_each_missing_ai_decision_blocks_every_review_type(boundary_client, outcome, missing):
    assert submit(boundary_client, decisions(outcome, missing), outcome).status_code == 201
    response = generate(boundary_client)
    assert response.status_code == 409
    assert missing in response.json()["detail"]
    assert boundary_client[2] == []
    with boundary_client[1]() as db:
        assert db.query(Report).count() == 0
        assert db.query(Study).one().workflow_state == "RADIOLOGIST_REVIEW"


@pytest.mark.parametrize("outcome", ["CONFIRMED", "EDITED"])
def test_original_single_acl_bypass_is_closed(boundary_client, outcome):
    assert submit(boundary_client, [{"finding": "ACL", "outcome": outcome}], outcome).status_code == 201
    assert generate(boundary_client).status_code == 409
    assert boundary_client[2] == []


def test_noncanonical_added_finding_cannot_complete_review(boundary_client):
    findings = decisions(omitted="ACL")
    findings.append({"finding": "Pes anserine bursitis", "outcome": "CONFIRMED", "is_radiologist_added": True})
    assert submit(boundary_client, findings).status_code == 201
    assert generate(boundary_client).status_code == 409
    assert boundary_client[2] == []


@pytest.mark.parametrize("added_text", ["ACL", "Anterior cruciate ligament tear", "ACL and MCL injury"])
def test_added_canonical_duplicate_rejected_without_altering_predictions(boundary_client, added_text):
    findings = decisions()
    findings.append({"finding": added_text, "outcome": "CONFIRMED", "is_radiologist_added": True})
    response = submit(boundary_client, findings)
    assert response.status_code == 422
    assert "duplicate" in response.json()["detail"]
    with boundary_client[1]() as db:
        assert db.query(RadiologistReview).count() == 0
        assert [(p.label, p.confidence) for p in db.query(Prediction).order_by(Prediction.id)] == [
            (label, 0.02 * (i + 1)) for i, label in enumerate(LABELS)
        ]


def test_duplicate_ai_decisions_rejected(boundary_client):
    assert submit(boundary_client, decisions() + [{"finding": "anterior cruciate ligament", "outcome": "REJECTED"}]).status_code == 422
    assert boundary_client[2] == []


@pytest.mark.parametrize("corruption", ["duplicate", "added_substitute", "pending", "missing_outcome"])
def test_persisted_invalid_review_cannot_bypass_generation(boundary_client, corruption):
    assert submit(boundary_client, decisions()).status_code == 201
    with boundary_client[1]() as db:
        finding = db.query(ValidatedFinding).filter_by(finding="ACL").one()
        if corruption == "duplicate":
            db.add(ValidatedFinding(review_id=finding.review_id, finding="ACL", outcome="REJECTED"))
        elif corruption == "added_substitute":
            finding.is_radiologist_added = True
        else:
            finding.outcome = "PENDING" if corruption == "pending" else ""
        db.commit()
    assert generate(boundary_client).status_code == 409
    assert boundary_client[2] == []


@pytest.mark.parametrize("boundary_client", [STUDY_UID], indirect=True)
def test_uid_stays_backend_only_for_report_and_patient_explanation(boundary_client):
    findings = decisions("REJECTED")
    findings[0]["outcome"] = "EDITED"
    findings[0]["details"] = "Partial thickness tear, 2.5 mm."
    assert submit(boundary_client, findings, notes="Pain for 3 weeks.").status_code == 201
    report = generate(boundary_client)
    assert report.status_code == 201, report.text
    assert json.loads(report.json()["draft_content"])["study_id"] == STUDY_UID
    explanation = boundary_client[0].post(f"/studies/{STUDY_UID}/patient-explanation", headers=HEADERS)
    assert explanation.status_code == 200, explanation.text
    assert explanation.json()["patient_explanation"]["study_id"] == STUDY_UID
    assert len(boundary_client[2]) == 2
    with boundary_client[1]() as db:
        internal_id = db.query(Study).one().id
        assert db.query(Report).one().study_id == STUDY_UID
    for prompt in boundary_client[2]:
        assert f"STUDY ID:\nstudy-{internal_id}\n" in prompt
        for forbidden in [STUDY_UID, SERIES_UID, PATIENT_ID, "StudyInstanceUID", "SeriesInstanceUID", "PatientID"]:
            assert forbidden not in prompt
        assert "Partial thickness tear, 2.5 mm." in prompt
        assert "Pain for 3 weeks." in prompt
        approved = ast.literal_eval(prompt.split("RADIOLOGIST-APPROVED FINDINGS:\n", 1)[1].splitlines()[0])
        assert approved == [{"abnormality": "ACL", "probability": 0.02, "status": "APPROVED"}]
        for rejected in LABELS[1:]:
            assert rejected not in prompt


@pytest.mark.parametrize("unsafe_text", [
    f"StudyInstanceUID: {STUDY_UID}", f"SeriesInstanceUID={SERIES_UID}",
    f"PatientID: {PATIENT_ID}", STUDY_UID, SERIES_UID, PATIENT_ID,
    "patient_id = unknown-patient", "study instance uid: private", "series-instance-uid: private",
    r"C:\MRI\private\slice.dcm", "/data/private/series/image.dcm", "private/image.dcm",
    "tensor([[[0.1, 0.2]]])", "array([[1, 2, 3]])",
])
@pytest.mark.parametrize("field", ["notes", "edited_details", "added_text", "added_details"])
def test_sensitive_clinical_text_never_calls_either_provider(unsafe_text, field):
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    findings = [{"finding": "ACL", "outcome": "EDITED", "details": "Partial tear."}]
    context = "Pain for 3 weeks."
    if field == "notes":
        context = unsafe_text
    elif field == "edited_details":
        findings[0]["details"] = unsafe_text
    else:
        findings.append({"finding": unsafe_text if field == "added_text" else "Pes anserine bursitis",
                         "outcome": "CONFIRMED", "is_radiologist_added": True,
                         "details": unsafe_text if field == "added_details" else None})
    for method in [adapter.generate_report, adapter.generate_patient_explanation]:
        with pytest.raises(LLMIntegrationError):
            method(STUDY_UID, findings, [{"label": "ACL", "confidence": 0.2}], context,
                   application_study_id=7, sensitive_values=(PATIENT_ID,))
    assert calls == []


def test_known_patient_identifier_from_study_blocks_endpoint(boundary_client):
    assert submit(boundary_client, decisions(), notes=f"Clinical note for {PATIENT_ID}").status_code == 201
    response = generate(boundary_client)
    assert response.status_code == 503
    assert PATIENT_ID not in response.text
    assert boundary_client[2] == []
    with boundary_client[1]() as db:
        assert db.query(Report).count() == 0


@pytest.mark.parametrize("context", ["MCL sprain present.", "Medial collateral ligament injury."])
def test_rejected_finding_in_context_blocks_both_providers(context):
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    findings = [{"finding": "ACL", "outcome": "CONFIRMED"}, {"finding": "MCL", "outcome": "REJECTED"}]
    predictions = [{"label": "ACL", "confidence": 0.2}, {"label": "MCL", "confidence": 0.9}]
    for method in [adapter.generate_report, adapter.generate_patient_explanation]:
        with pytest.raises(LLMIntegrationError, match="rejected"):
            method("application-study", findings, predictions, context)
    assert calls == []


def test_direct_uid_call_without_internal_id_fails_closed():
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    for method in [adapter.generate_report, adapter.generate_patient_explanation]:
        with pytest.raises(LLMIntegrationError, match="application study identifier"):
            method(STUDY_UID, [], [])
    assert calls == []


def test_persisted_added_canonical_duplicate_fails_at_member2_boundary():
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    with pytest.raises(LLMIntegrationError, match="duplicate"):
        adapter.generate_report("application-study", [
            {"finding": "ACL", "outcome": "REJECTED"},
            {"finding": "anterior cruciate ligament tear", "outcome": "CONFIRMED", "is_radiologist_added": True},
        ], [{"label": "ACL", "confidence": 0.2}])
    assert calls == []


@pytest.mark.parametrize("raw_data", [[[0.1] * 5], {"pixel_array": [1, 2, 3]}])
def test_raw_structured_image_data_is_rejected(raw_data):
    calls = []
    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=lambda prompt: calls.append(prompt))
    for method in [adapter.generate_report, adapter.generate_patient_explanation]:
        with pytest.raises(LLMIntegrationError, match="clinical text only"):
            method("application-study", [], [], raw_data)
    assert calls == []


@pytest.mark.parametrize("study_id", [STUDY_UID, "1.2"])
def test_member2_input_itself_uses_internal_identity(study_id):
    mapped = map_backend_to_member2(study_id, [], [], "Pain for 3 weeks; 2.5 mm focus.", application_study_id=7)
    assert mapped["study_id"] == "study-7"
    assert mapped["clinical_context"] == "Pain for 3 weeks; 2.5 mm focus."
    with pytest.raises(LLMIntegrationError, match="identifier"):
        map_backend_to_member2(study_id, [], [], f"Study reference: {study_id}", application_study_id=7)


def test_provider_identity_is_validated_before_restoring_backend_identity():
    calls = []

    def mismatched_provider(prompt):
        calls.append(prompt)
        result = provider_response(prompt)
        result["study_id"] = "wrong-study"
        return result

    adapter = Member2ClinicalLLMAdapter(generate_llm_fn=mismatched_provider)
    for method in [adapter.generate_report, adapter.generate_patient_explanation]:
        with pytest.raises(LLMIntegrationError, match="[Ss]tudy ID mismatch"):
            method(STUDY_UID, [], [], application_study_id=7)
    assert len(calls) == 2
    assert all(STUDY_UID not in prompt for prompt in calls)
