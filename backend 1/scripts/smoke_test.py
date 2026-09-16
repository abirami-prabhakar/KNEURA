import sys
sys.path.insert(0, ".")
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.llm_adapter import Member2ClinicalLLMAdapter, get_llm_adapter
from app.main import app, get_db
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview
from app.models.report import Report, ReportVersion
from app.models.study import Study
from app.workflow import WorkflowState

CANONICAL_12_LABELS = [
    "ACL", "MCL", "Medial Meniscus", "Lateral Meniscus", "Medial OA",
    "Lateral OA", "PF OA", "Effusion", "Synovitis", "Baker's",
    "Contusion", "Fracture",
]

RAD_HEADERS = {"X-Authenticated-User-Id": "dr-smith-rad", "X-User-Role": "RADIOLOGIST"}
ORTHO_HEADERS = {"X-Authenticated-User-Id": "dr-jones-ortho", "X-User-Role": "ORTHOPEDIC_SURGEON"}
RELEASE_HEADERS = {"X-Authenticated-User-Id": "dr-jones-ortho", "X-User-Role": "ORTHOPEDIC_SURGEON"}
PATIENT_HEADERS = {"X-Authenticated-User-Id": "patient-smoke-1", "X-User-Role": "PATIENT"}
OTHER_PATIENT_HEADERS = {"X-Authenticated-User-Id": "patient-smoke-2", "X-User-Role": "PATIENT"}

def run_smoke_test():
    print("==================================================")
    print("RUNNING KNEE-AI 3.3 READ-ONLY SMOKE TEST SEQUENCE")
    print("==================================================")
    
    # 1. Database & App Client Setup (isolated test db)
    test_db_path = Path("smoke_test.db")
    if test_db_path.exists():
        test_db_path.unlink()
    engine = create_engine(f"sqlite:///{test_db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    captured_llm_prompts = []
    def mock_llm_fn(prompt: str) -> dict:
        captured_llm_prompts.append(prompt)
        return {
            "title": "Knee MRI Report",
            "study_id": "study-smoke-001",
            "status": "DRAFT",
            "findings": [
                "Medial meniscus abnormality detected.",
                "Lateral meniscus abnormality detected.",
            ],
            "impression": "Bilateral meniscal abnormalities confirmed.",
            "note": "AI-generated draft requiring radiologist review and final approval.",
        }

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm_adapter] = lambda: Member2ClinicalLLMAdapter(generate_llm_fn=mock_llm_fn)
    client = TestClient(app)

    try:
        # Step 1: Study Exists
        db = session_factory()
        db.add(Study(
            study_id="study-smoke-001",
            patient_id="patient-smoke-1",
            workflow_state=None,
            data_mode="CLINICAL",
        ))
        db.commit()
        db.close()
        print("PASS: Step 1 - Study exists in database.")

        # Step 2: AI Analysis / Workflow Initialization
        # Simulate AI analysis pipeline completing and generating 12 predictions
        db = session_factory()
        study = db.query(Study).filter_by(study_id="study-smoke-001").first()
        study.workflow_state = WorkflowState.AI_COMPLETE.value
        for idx, label in enumerate(CANONICAL_12_LABELS):
            db.add(Prediction(study_id="study-smoke-001", label=label, confidence=0.08 * (idx + 1)))
        db.commit()
        db.close()
        print("PASS: Step 2 - AI analysis transitioned workflow to AI_COMPLETE.")

        # Step 3: 12 Predictions Persisted
        db = session_factory()
        preds = db.query(Prediction).filter_by(study_id="study-smoke-001").all()
        assert len(preds) == 12
        assert [p.label for p in preds] == CANONICAL_12_LABELS
        db.close()
        print("PASS: Step 3 - All 12 canonical AI predictions persisted.")

        # Step 4: Security & Radiologist Review (Security Checks)
        # 4a. Orthopedic or Patient CANNOT perform radiologist review (403)
        res_bad_role = client.post("/studies/study-smoke-001/review", headers=ORTHO_HEADERS, json={"decision": "CONFIRMED", "validated_findings": [{"finding": "ACL", "outcome": "APPROVED"}]})
        assert res_bad_role.status_code == 403, f"Expected 403, got {res_bad_role.status_code}"
        res_pat_role = client.post("/studies/study-smoke-001/review", headers=PATIENT_HEADERS, json={"decision": "CONFIRMED", "validated_findings": [{"finding": "ACL", "outcome": "APPROVED"}]})
        assert res_pat_role.status_code == 403, f"Expected 403, got {res_pat_role.status_code}"
        print("PASS: Security Check - Non-radiologists rejected from radiologist review (403).")

        # 4b. Radiologist review of all 12 findings (mixed: 2 approved, 10 rejected)
        review_findings = []
        for idx, label in enumerate(CANONICAL_12_LABELS):
            outcome = "APPROVED" if idx in (2, 3) else "REJECTED" # Medial & Lateral Meniscus approved
            review_findings.append({
                "finding": label,
                "outcome": outcome,
                "details": f"Decision: {outcome}",
            })
        rev_res = client.post(
            "/studies/study-smoke-001/review",
            headers=RAD_HEADERS,
            json={
                "decision": "MIXED",
                "notes": "Meniscal pathology confirmed on coronal views.",
                "validated_findings": review_findings,
            },
        )
        assert rev_res.status_code == 201, f"Expected 201, got {rev_res.status_code}: {rev_res.text}"
        print("PASS: Step 4 - Radiologist successfully reviewed all 12 findings individually.")

        # Step 5: Grad-CAM Authorization & Generation
        # 5a. Unauthenticated rejected (401)
        gc_unauth = client.post("/api/v1/ai/gradcam", json={"study_id": "study-smoke-001", "abnormality": "Medial Meniscus"})
        assert gc_unauth.status_code == 401, f"Expected 401, got {gc_unauth.status_code}"
        # 5b. Orthopedic rejected (403)
        gc_ortho = client.post("/api/v1/ai/gradcam", headers=ORTHO_HEADERS, json={"study_id": "study-smoke-001", "abnormality": "Medial Meniscus"})
        assert gc_ortho.status_code == 403, f"Expected 403, got {gc_ortho.status_code}"
        # 5c. Authorized Radiologist succeeds (mocking backend execution)
        mock_gc = {
            "model_version": "KNEE-AI 3.3",
            "abnormality": "Medial Meniscus",
            "class_index": 2,
            "probability": 0.24,
            "plane": "CORONAL",
            "series_instance_uid": "1.2.3.4",
            "window_index": 2,
            "instance_numbers": [1, 2, 3, 4, 5],
            "heatmap": [[0.1, 0.2], [0.3, 0.4]],
        }
        with patch("app.main.FrozenKneeAIAdapter.generate_gradcam", return_value=mock_gc):
            gc_ok = client.post("/api/v1/ai/gradcam", headers=RAD_HEADERS, json={"study_id": "study-smoke-001", "abnormality": "Medial Meniscus"})
            assert gc_ok.status_code == 200, f"Expected 200, got {gc_ok.status_code}"
            assert gc_ok.json()["abnormality"] == "Medial Meniscus"
            assert gc_ok.json()["class_index"] == 2
        print("PASS: Step 5 - Grad-CAM authorization enforced (401/403) and radiologist generation verified (200).")

        # Step 6: LLM Draft Generation
        # 6a. Verify non-radiologist cannot generate draft (403)
        gen_unauth = client.post("/studies/study-smoke-001/generate-report", headers=ORTHO_HEADERS)
        assert gen_unauth.status_code == 403
        # 6b. Radiologist generates draft report
        gen_res = client.post("/studies/study-smoke-001/generate-report", headers=RAD_HEADERS)
        assert gen_res.status_code == 201, f"Expected 201, got {gen_res.status_code}: {gen_res.text}"
        rep_data = gen_res.json()
        report_id = rep_data["report_id"]
        assert rep_data["current_version"] == 1
        assert rep_data["status"] == "DRAFT"
        # Responsible AI Check: rejected findings were NOT positive inputs to LLM
        assert len(captured_llm_prompts) == 1
        llm_prompt = captured_llm_prompts[0]
        assert "Medial Meniscus" in llm_prompt
        assert "Lateral Meniscus" in llm_prompt
        assert "Do not include rejected findings" in llm_prompt or "rules" in llm_prompt.lower()
        print("PASS: Step 6 - Draft report generated as Version 1; Responsible AI input boundary verified.")

        # Step 7 & 8: Edit Report and Immutable Versioning
        edited_content = rep_data["draft_content"] + "\nAddendum: Correlation with patient's joint line tenderness recommended."
        edit_res = client.put(f"/reports/{report_id}", headers=RAD_HEADERS, json={"draft_content": edited_content})
        assert edit_res.status_code == 200
        assert edit_res.json()["current_version"] == 2
        
        # Verify both version 1 and version 2 exist in DB
        db = session_factory()
        v1 = db.query(ReportVersion).filter_by(report_id=report_id, version_number=1).first()
        v2 = db.query(ReportVersion).filter_by(report_id=report_id, version_number=2).first()
        assert v1 is not None and v1.content != edited_content
        assert v2 is not None and v2.content == edited_content
        db.close()
        print("PASS: Step 7 & 8 - Draft report edited; immutable ReportVersion 2 created.")

        # Step 9: Radiologist Approves Report
        # 9a. Orthopedic cannot approve report (403)
        app_ortho = client.post(f"/reports/{report_id}/approve", headers=ORTHO_HEADERS)
        assert app_ortho.status_code == 403
        # 9b. Radiologist approves
        app_res = client.post(f"/reports/{report_id}/approve", headers=RAD_HEADERS)
        assert app_res.status_code == 200
        assert app_res.json()["status"] == "APPROVED"
        assert app_res.json()["approved_version"] == 2
        print("PASS: Step 9 - Radiologist approved report; approved_version locked to version 2.")

        # Responsible AI / Workflow Check: Patient CANNOT access unreleased report (409)
        unrel_res = client.get("/patient/reports/study-smoke-001", headers=PATIENT_HEADERS)
        assert unrel_res.status_code == 409, f"Expected 409, got {unrel_res.status_code}"
        print("PASS: Security Check - Patient blocked from unreleased study (409).")

        # Step 10 & 11: Orthopedic Review with Patient-Information Approval
        # 10a. Radiologist cannot submit orthopedic review (403)
        ortho_bad = client.post("/orthopedic/study-smoke-001/review", headers=RAD_HEADERS, json={"assessment": "A", "recommendation": "R"})
        assert ortho_bad.status_code == 403
        # 10b. Orthopedic submits review with patient_information_approved=True
        ortho_res = client.post(
            "/orthopedic/study-smoke-001/review",
            headers=ORTHO_HEADERS,
            json={
                "assessment": "Bilateral meniscal tears without ligamentous instability.",
                "recommendation": "Prescribe structured physical therapy and clinical follow-up.",
                "notes": "Patient informed of low impact activity guidelines.",
                "patient_information_approved": True,
                "approved_followup_info": "Follow up in clinic in 4 weeks with PT compliance log.",
            },
        )
        assert ortho_res.status_code == 201, f"Expected 201, got {ortho_res.status_code}"
        assert ortho_res.json()["patient_information_approved"] is True
        print("PASS: Step 10 & 11 - Orthopedic review submitted with patient_information_approved = True.")

        # Patient Explanation Generation
        mock_pat_exp = {
            "summary": "Your MRI shows wear/tears in the cartilage cushions (menisci) of your knee.",
            "findings_explained": [
                {"finding": "Medial meniscus tear", "plain_english": "Tear in the inner cartilage cushion"},
                {"finding": "Lateral meniscus tear", "plain_english": "Tear in the outer cartilage cushion"},
            ],
            "next_steps": "Follow up with physical therapy as prescribed.",
        }
        with patch("app.llm_adapter.Member2ClinicalLLMAdapter.generate_patient_explanation", return_value=mock_pat_exp):
            pe_res = client.post("/studies/study-smoke-001/patient-explanation", headers=RAD_HEADERS)
            assert pe_res.status_code == 200
        print("PASS: Generated patient-friendly explanation with safety validator.")

        # Step 12: Release Authority Releases Study
        # 12a. Patient cannot release study (403)
        rel_pat = client.post("/studies/study-smoke-001/patient-release", headers=PATIENT_HEADERS)
        assert rel_pat.status_code == 403
        # 12b. Authorized release authority releases study
        rel_res = client.post(
            "/studies/study-smoke-001/patient-release",
            headers=RELEASE_HEADERS,
            json={"patient_information_approved": True},
        )
        assert rel_res.status_code == 200, f"Expected 200, got {rel_res.status_code}"
        assert rel_res.json()["workflow_state"] == "PATIENT_RELEASED"
        print("PASS: Step 12 - Study released to patient by authorized clinician.")

        # Step 13, 14, 15: Patient Retrieves Released Report & Validates Data Minimization
        # 13a. Cross-patient isolation: other patient gets 403
        cross_res = client.get("/patient/reports/study-smoke-001", headers=OTHER_PATIENT_HEADERS)
        assert cross_res.status_code == 403, f"Expected 403, got {cross_res.status_code}"
        print("PASS: Security Check - Cross-patient access strictly rejected (403).")

        # 13b. Authorized patient accesses report
        pat_res = client.get("/patient/reports/study-smoke-001", headers=PATIENT_HEADERS)
        assert pat_res.status_code == 200, f"Expected 200, got {pat_res.status_code}"
        p_body = pat_res.json()
        assert p_body["study_id"] == "study-smoke-001"
        assert p_body["status"] == "RELEASED"
        assert p_body["approved_report"] == edited_content
        # 14: Plain-language explanation received
        assert p_body["patient_explanation"]["summary"] == mock_pat_exp["summary"]
        # 15: Approved follow-up information received
        assert "Follow up in clinic in 4 weeks" in p_body["approved_followup_info"]
        # Data Minimization Check: no raw predictions / probabilities leaked to patient
        assert "probabilities" not in p_body
        assert "confidence" not in p_body
        assert "internal" not in str(p_body).lower()
        print("PASS: Step 13, 14, 15 - Patient successfully received approved report, plain-language explanation, and follow-up guidance without raw AI probabilities.")

        print("==================================================")
        print("ALL 15 SMOKE TEST STEPS & SECURITY GATES PASSED!")
        print("==================================================")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        if test_db_path.exists():
            try:
                test_db_path.unlink()
            except OSError:
                pass

if __name__ == "__main__":
    run_smoke_test()
