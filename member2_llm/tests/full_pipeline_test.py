# ============================================================
# KNEE-AI 3.3 — MEMBER 2 FULL OFFLINE PIPELINE TEST
# ============================================================

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

from services.report_generator import generate_report
from services.safety_validator import validate_llm_report
from services.patient_safety_validator import (
    validate_patient_explanation
)
from schemas.api_contract import create_llm_input


# ============================================================
# 1. RADIOLOGIST-VALIDATED FINDINGS
# ============================================================

validated_findings = {

    "study_id": "OFFLINE_DEMO_001",

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


print("\n" + "=" * 60)
print("KNEE-AI 3.3 — FULL MEMBER 2 OFFLINE PIPELINE")
print("=" * 60)


# ============================================================
# 2. CREATE STRUCTURED DRAFT
# ============================================================

draft_report = generate_report(
    validated_findings
)

assert draft_report["status"] == "DRAFT"

print("\nSTEP 1 PASSED")
print("Structured draft created.")


# ============================================================
# 3. CREATE CONTROLLED LLM INPUT
# ============================================================

llm_input = create_llm_input(

    validated_findings["study_id"],

    validated_findings["findings"],

    validated_findings["clinical_context"]
)

assert len(
    llm_input["approved_findings"]
) == 6

assert "rejected_findings" not in llm_input

print("\nSTEP 2 PASSED")
print("Only approved findings prepared for LLM.")


# ============================================================
# 4. SIMULATED LLM DRAFT
# ============================================================

simulated_llm_report = {

    "title": "Knee MRI Report",

    "study_id": "OFFLINE_DEMO_001",

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
        "The approved findings include meniscal "
        "abnormalities, osteoarthritic changes "
        "and synovitis."
    ),

    "note": (
        "This is an AI-generated draft based on "
        "radiologist-approved information and "
        "requires radiologist review and final approval."
    )
}


print("\nSTEP 3")
print("Simulated LLM draft generated.")


# ============================================================
# 5. VALIDATE LLM DRAFT
# ============================================================

result, message = validate_llm_report(

    simulated_llm_report,

    validated_findings
)

assert result is True

print("\nSTEP 4 PASSED")
print(message)


# ============================================================
# 6. SIMULATED PATIENT EXPLANATION
# ============================================================

simulated_patient_explanation = {

    "title": "Patient-Friendly MRI Explanation",

    "study_id": "OFFLINE_DEMO_001",

    "approved_findings": (
        "The MRI contains approved findings involving "
        "the medial meniscus, lateral meniscus, "
        "medial OA, lateral OA, PF OA and synovitis."
    ),

    "what_this_means": (
        "These findings were reviewed and approved "
        "by the radiologist."
    ),

    "important_note": (
        "This explanation is based on radiologist-approved "
        "information. Please discuss your MRI results "
        "with your doctor."
    )
}


print("\nSTEP 5")
print("Simulated patient explanation generated.")


# ============================================================
# 7. VALIDATE PATIENT EXPLANATION
# ============================================================

result, message = validate_patient_explanation(

    simulated_patient_explanation,

    validated_findings
)

assert result is True

print("\nSTEP 6 PASSED")
print(message)


# ============================================================
# 8. FINAL PIPELINE CHECK
# ============================================================

print("\n" + "=" * 60)
print("FULL PIPELINE TEST PASSED")
print("=" * 60)

print("\nAI findings")
print("     ↓")
print("Radiologist validation")
print("     ↓")
print("Approved findings only")
print("     ↓")
print("LLM draft report")
print("     ↓")
print("Safety validation")
print("     ↓")
print("Patient-friendly explanation")
print("     ↓")
print("Radiologist final approval required")

print("\nGemini API was NOT called.")
print("Report remains DRAFT.")
print("Final approval remains PENDING.")