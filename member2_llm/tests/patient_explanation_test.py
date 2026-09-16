# ============================================================
# KNEE-AI 3.3 — PATIENT EXPLANATION OFFLINE TEST
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

from services.patient_safety_validator import (
    validate_patient_explanation
)


# ============================================================
# GOLDEN CASE — RADIOLOGIST VALIDATION
# ============================================================

validated_findings = {

    "study_id": "RSNA_GOLDEN_001",

    "findings": [

        {"abnormality": "ACL",
         "probability": 0.0768,
         "status": "REJECTED"},

        {"abnormality": "MCL",
         "probability": 0.2105,
         "status": "REJECTED"},

        {"abnormality": "Medial Meniscus",
         "probability": 0.5337,
         "status": "APPROVED"},

        {"abnormality": "Lateral Meniscus",
         "probability": 0.9094,
         "status": "APPROVED"},

        {"abnormality": "Medial OA",
         "probability": 0.9076,
         "status": "APPROVED"},

        {"abnormality": "Lateral OA",
         "probability": 0.8253,
         "status": "APPROVED"},

        {"abnormality": "PF OA",
         "probability": 0.9420,
         "status": "APPROVED"},

        {"abnormality": "Effusion",
         "probability": 0.3521,
         "status": "REJECTED"},

        {"abnormality": "Synovitis",
         "probability": 0.6673,
         "status": "APPROVED"},

        {"abnormality": "Baker's",
         "probability": 0.4718,
         "status": "REJECTED"},

        {"abnormality": "Contusion",
         "probability": 0.0506,
         "status": "REJECTED"},

        {"abnormality": "Fracture",
         "probability": 0.4389,
         "status": "REJECTED"}
    ]
}


# ============================================================
# SIMULATED PATIENT EXPLANATION
# ============================================================

patient_explanation = {

    "title": "Patient-Friendly MRI Explanation",

    "study_id": "RSNA_GOLDEN_001",

    "approved_findings": (
        "The MRI shows findings involving the medial meniscus, "
        "lateral meniscus, medial OA, lateral OA, PF OA, "
        "and synovitis."
    ),

    "what_this_means": (
        "These are findings that were reviewed and approved "
        "by the radiologist. The explanation is provided "
        "in simple language to help you understand the "
        "MRI information."
    ),

    "important_note": (
        "This explanation is based on radiologist-approved "
        "information. Please discuss your MRI results with "
        "your doctor for clinical interpretation and next steps."
    )
}


# ============================================================
# RUN SAFETY VALIDATION
# ============================================================

passed, message = validate_patient_explanation(
    patient_explanation,
    validated_findings
)


# ============================================================
# RESULT
# ============================================================

print("=" * 60)
print("KNEE-AI 3.3 — PATIENT EXPLANATION TEST")
print("=" * 60)

print()

if passed:

    print("PATIENT EXPLANATION TEST PASSED")

else:

    print("PATIENT EXPLANATION TEST FAILED")

print()
print("Message:", message)

print()
print("=" * 60)