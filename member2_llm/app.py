
# ============================================================
# KNEE-AI 3.3 — MEMBER 2
# LLM + CLINICAL INTELLIGENCE PIPELINE
# ============================================================

from services.report_generator import generate_report
from services.llm_service import generate_llm_report
from services.safety_validator import validate_llm_report
from services.patient_explanation import generate_patient_explanation
from services.patient_safety_validator import validate_patient_explanation


# ============================================================
# 0. CANONICAL GOLDEN CASE STUDY ID
# ============================================================

CANONICAL_GOLDEN_STUDY_ID = (
    "1.2.826.0.1.3680043.8.498."
    "10004873229099053869093324292195817260"
)


# ============================================================
# 1. GOLDEN CASE — RADIOLOGIST REVIEWED FINDINGS
# ============================================================

validated_findings = {

    "study_id": CANONICAL_GOLDEN_STUDY_ID,

    "model_version": "KNEE-AI 3.3",

    "findings": [

        {
            "abnormality": "ACL",
            "probability": 0.076839864254,
            "status": "REJECTED"
        },

        {
            "abnormality": "MCL",
            "probability": 0.210538342595,
            "status": "REJECTED"
        },

        {
            "abnormality": "Medial Meniscus",
            "probability": 0.533730864525,
            "status": "APPROVED"
        },

        {
            "abnormality": "Lateral Meniscus",
            "probability": 0.909474194050,
            "status": "APPROVED"
        },

        {
            "abnormality": "Medial OA",
            "probability": 0.907636880875,
            "status": "APPROVED"
        },

        {
            "abnormality": "Lateral OA",
            "probability": 0.825265347958,
            "status": "APPROVED"
        },

        {
            "abnormality": "PF OA",
            "probability": 0.942036688328,
            "status": "APPROVED"
        },

        {
            "abnormality": "Effusion",
            "probability": 0.352069199085,
            "status": "REJECTED"
        },

        {
            "abnormality": "Synovitis",
            "probability": 0.667338013649,
            "status": "APPROVED"
        },

        {
            "abnormality": "Baker's",
            "probability": 0.471786767244,
            "status": "REJECTED"
        },

        {
            "abnormality": "Contusion",
            "probability": 0.050634816289,
            "status": "REJECTED"
        },

        {
            "abnormality": "Fracture",
            "probability": 0.438851922750,
            "status": "REJECTED"
        }
    ],

    "clinical_context": (
        "Persistent knee pain with activity and intermittent stiffness."
    )
}


# ============================================================
# 2. GOLDEN STUDY ID VERIFICATION
# ============================================================

print("\n" + "=" * 60)
print("CANONICAL GOLDEN STUDY ID")
print("=" * 60)

print(validated_findings["study_id"])


if validated_findings["study_id"] != CANONICAL_GOLDEN_STUDY_ID:
    raise ValueError(
        "Canonical Golden Study ID mismatch."
    )

print("Study ID verification PASSED.")


# ============================================================
# 3. STRUCTURED DRAFT REPORT
# ============================================================

draft_report = generate_report(validated_findings)


print("\n" + "=" * 60)
print("STRUCTURED DRAFT REPORT")
print("=" * 60)

print(draft_report)


# ============================================================
# 4. VERIFY STUDY ID IN STRUCTURED REPORT
# ============================================================

if draft_report["study_id"] != CANONICAL_GOLDEN_STUDY_ID:

    raise ValueError(
        "Study ID mismatch between Golden Case and draft report."
    )

print("\nStudy ID linkage: Golden Case -> Draft Report PASSED.")


# ============================================================
# 5. EXTRACT ONLY RADIOLOGIST-APPROVED FINDINGS
# ============================================================

approved_findings = [
    finding
    for finding in validated_findings["findings"]
    if finding["status"] == "APPROVED"
]


print("\n" + "=" * 60)
print("APPROVED FINDINGS SENT TO LLM")
print("=" * 60)

for finding in approved_findings:
    print(
        f"- {finding['abnormality']}"
    )


# ============================================================
# 6. GEMINI REPORT GENERATION
# ============================================================

with open(
    "prompts/report_prompt.txt",
    "r",
    encoding="utf-8"
) as file:

    llm_prompt = file.read()


llm_prompt = llm_prompt.format(

    study_id=validated_findings["study_id"],

    validated_findings=approved_findings,

    clinical_context=validated_findings["clinical_context"]
)


llm_report = generate_llm_report(llm_prompt)


print("\n" + "=" * 60)
print("GEMINI DRAFT REPORT")
print("=" * 60)

print(llm_report)


# ============================================================
# 7. VERIFY STUDY ID IN LLM REPORT
# ============================================================

if llm_report.get("study_id") != CANONICAL_GOLDEN_STUDY_ID:

    raise ValueError(
        "Study ID mismatch between Golden Case and LLM report."
    )

print("\nStudy ID linkage: Golden Case -> LLM Report PASSED.")


# ============================================================
# 8. LLM REPORT SAFETY VALIDATION
# ============================================================

validation_result, validation_message = validate_llm_report(
    llm_report,
    validated_findings
)


print("\n" + "=" * 60)
print("LLM SAFETY VALIDATION")
print("=" * 60)

print(validation_message)


# ============================================================
# 9. PATIENT-FRIENDLY EXPLANATION
# ============================================================

with open(
    "prompts/patient_prompt.txt",
    "r",
    encoding="utf-8"
) as file:

    patient_prompt = file.read()


patient_prompt = patient_prompt.format(

    study_id=validated_findings["study_id"],

    approved_findings=approved_findings,

    clinical_context=validated_findings["clinical_context"]
)


# Explicit verification that the canonical Study ID
# is being passed into the patient explanation prompt.

if CANONICAL_GOLDEN_STUDY_ID not in patient_prompt:

    raise ValueError(
        "Canonical Study ID missing from patient explanation prompt."
    )


patient_explanation = generate_patient_explanation(
    patient_prompt
)


print("\n" + "=" * 60)
print("PATIENT-FRIENDLY EXPLANATION")
print("=" * 60)

print(patient_explanation)


# ============================================================
# 10. PATIENT SAFETY VALIDATION
# ============================================================

patient_validation_result, patient_validation_message = (
    validate_patient_explanation(
        patient_explanation,
        validated_findings
    )
)


print("\n" + "=" * 60)
print("PATIENT SAFETY VALIDATION")
print("=" * 60)

print(patient_validation_message)


# ============================================================
# 11. FINAL STUDY ID LINKAGE STATUS
# ============================================================

print("\n" + "=" * 60)
print("STUDY ID LINKAGE STATUS")
print("=" * 60)

print("Golden Case Study ID:")
print(CANONICAL_GOLDEN_STUDY_ID)

print("\nVerified flow:")
print("Golden Case")
print("     ↓")
print("Structured Draft Report")
print("     ↓")
print("LLM Prompt")
print("     ↓")
print("Gemini Draft Report")
print("     ↓")
print("Patient Explanation Prompt")

print("\nSTUDY ID LINKAGE PASSED")


# ============================================================
# 12. FINAL STATUS
# ============================================================

print("\n" + "=" * 60)
print("PIPELINE STATUS")
print("=" * 60)


if validation_result and patient_validation_result:

    print("SUCCESS")
    print("LLM draft passed safety validation.")
    print("Patient explanation passed safety validation.")
    print("Report remains DRAFT.")
    print("Final approval must be performed by the radiologist.")

else:

    print("SAFETY VALIDATION FAILED")
    print("The generated output must not be finalized.")

