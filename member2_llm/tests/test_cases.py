import sys
import os

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

# ============================================================
# KNEE-AI 3.3 — MEMBER 2 OFFLINE TESTS
# ============================================================

from services.report_generator import generate_report
from services.safety_validator import validate_llm_report
from services.patient_safety_validator import (
    validate_patient_explanation
)
from schemas.api_contract import create_llm_input


# ============================================================
# TEST INPUT
# ============================================================

validated_findings = {

    "study_id": "TEST_001",

    "findings": [

        {
            "abnormality": "ACL",
            "status": "REJECTED"
        },

        {
            "abnormality": "MCL",
            "status": "REJECTED"
        },

        {
            "abnormality": "Medial Meniscus",
            "status": "APPROVED"
        },

        {
            "abnormality": "Lateral Meniscus",
            "status": "APPROVED"
        },

        {
            "abnormality": "Medial OA",
            "status": "APPROVED"
        },

        {
            "abnormality": "Lateral OA",
            "status": "APPROVED"
        },

        {
            "abnormality": "PF OA",
            "status": "APPROVED"
        },

        {
            "abnormality": "Effusion",
            "status": "REJECTED"
        },

        {
            "abnormality": "Synovitis",
            "status": "APPROVED"
        },

        {
            "abnormality": "Baker's",
            "status": "REJECTED"
        },

        {
            "abnormality": "Contusion",
            "status": "REJECTED"
        },

        {
            "abnormality": "Fracture",
            "status": "REJECTED"
        }
    ],

    "clinical_context": (
        "Persistent knee pain with activity."
    )
}


# ============================================================
# TEST 1 — STRUCTURED REPORT
# ============================================================

report = generate_report(
    validated_findings
)

assert report["status"] == "DRAFT"

assert len(report["findings"]) == 6

print("TEST 1 PASSED — Structured report contains approved findings only.")


# ============================================================
# TEST 2 — VALID LLM REPORT
# ============================================================

valid_llm_report = {

    "title": "Knee MRI Report",

    "study_id": "TEST_001",

    "status": "DRAFT",

    "findings": [
        "Medial Meniscus abnormality.",
        "Lateral Meniscus abnormality.",
        "Medial OA.",
        "Lateral OA.",
        "PF OA.",
        "Synovitis."
    ],

    "impression": (
        "The approved findings include meniscal abnormalities "
        "and osteoarthritic changes."
    ),

    "note": (
        "This is a draft and requires radiologist review "
        "and final approval."
    )
}


result, message = validate_llm_report(
    valid_llm_report,
    validated_findings
)

assert result is True

print("TEST 2 PASSED — Valid LLM draft accepted.")


# ============================================================
# TEST 3 — REJECTED FINDING DETECTION
# ============================================================

bad_llm_report = {

    "title": "Knee MRI Report",

    "study_id": "TEST_001",

    "status": "DRAFT",

    "findings": [
        "Medial Meniscus abnormality.",
        "Lateral Meniscus abnormality.",
        "Medial OA.",
        "Lateral OA.",
        "PF OA.",
        "Synovitis.",
        "ACL tear."
    ],

    "impression": "Draft report.",

    "note": "Requires radiologist review."
}


result, message = validate_llm_report(
    bad_llm_report,
    validated_findings
)

assert result is False

print("TEST 3 PASSED — Rejected finding correctly detected.")


# ============================================================
# TEST 4 — MISSING APPROVED FINDING
# ============================================================

missing_finding_report = {

    "title": "Knee MRI Report",

    "study_id": "TEST_001",

    "status": "DRAFT",

    "findings": [
        "Medial Meniscus abnormality.",
        "Lateral Meniscus abnormality.",
        "Medial OA.",
        "Lateral OA.",
        "PF OA."
    ],

    "impression": "Draft report.",

    "note": "Requires radiologist review."
}


result, message = validate_llm_report(
    missing_finding_report,
    validated_findings
)

assert result is False

print("TEST 4 PASSED — Missing approved finding correctly detected.")


# ============================================================
# TEST 5 — FINAL REPORT MUST FAIL
# ============================================================

final_report = dict(valid_llm_report)

final_report["status"] = "FINAL"


result, message = validate_llm_report(
    final_report,
    validated_findings
)

assert result is False

print("TEST 5 PASSED — FINAL report rejected by Member 2 validator.")


# ============================================================
# TEST 6 — PATIENT EXPLANATION
# ============================================================

patient_explanation = {

    "title": "Patient-Friendly MRI Explanation",

    "study_id": "TEST_001",

    "approved_findings": (
        "The MRI shows findings involving the "
        "medial meniscus, lateral meniscus, "
        "medial OA, lateral OA, PF OA and synovitis."
    ),

    "what_this_means": (
        "These are the findings that were approved "
        "by the radiologist."
    ),

    "important_note": (
        "This explanation is based on radiologist-approved "
        "information. Please discuss the results with your doctor."
    )
}


result, message = validate_patient_explanation(
    patient_explanation,
    validated_findings
)

assert result is True

print("TEST 6 PASSED — Patient explanation accepted.")


# ============================================================
# TEST 7 — PATIENT TREATMENT RECOMMENDATION
# ============================================================

bad_patient_explanation = dict(
    patient_explanation
)

bad_patient_explanation["what_this_means"] = (
    "You should take medication and do physiotherapy."
)


result, message = validate_patient_explanation(
    bad_patient_explanation,
    validated_findings
)

assert result is False

print("TEST 7 PASSED — Treatment recommendation detected.")


# ============================================================
# TEST 8 — API CONTRACT
# ============================================================

llm_input = create_llm_input(

    "TEST_001",

    validated_findings["findings"],

    validated_findings["clinical_context"]
)


assert "approved_findings" in llm_input

assert len(
    llm_input["approved_findings"]
) == 6

assert "rejected_findings" not in llm_input


for finding in llm_input["approved_findings"]:

    assert finding["status"] == "APPROVED"


print(
    "TEST 8 PASSED — LLM input contains approved findings only."
)


# ============================================================
# FINAL RESULT
# ============================================================

print("\n" + "=" * 60)
print("ALL MEMBER 2 OFFLINE TESTS PASSED")
print("=" * 60)