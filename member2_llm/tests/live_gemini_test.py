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

from services.llm_service import generate_llm_report
from services.safety_validator import validate_llm_report


# ============================================================
# KNEE-AI 3.3 — LIVE GEMINI REPORT TEST
# ============================================================


validated_findings = {
    "study_id": "KNEE-AI-LIVE-001",

    "model_version": "KNEE-AI 3.3",

    "findings": [

        {
            "abnormality": "ACL",
            "probability": 0.86,
            "status": "APPROVED"
        },

        {
            "abnormality": "Fracture",
            "probability": 0.20,
            "status": "REJECTED"
        }

    ],

    "clinical_context": (
        "Persistent knee pain with activity."
    )
}


# ------------------------------------------------------------
# Keep ONLY approved findings for LLM
# ------------------------------------------------------------

approved_findings = [

    finding
    for finding in validated_findings["findings"]
    if finding["status"] == "APPROVED"

]


# ------------------------------------------------------------
# Load the ACTUAL production report prompt
# ------------------------------------------------------------

with open(
    "prompts/report_prompt.txt",
    "r",
    encoding="utf-8"
) as file:

    prompt_template = file.read()


# ------------------------------------------------------------
# Create the same prompt used by the API
# ------------------------------------------------------------

llm_prompt = prompt_template.format(

    study_id=validated_findings["study_id"],

    validated_findings=approved_findings,

    clinical_context=validated_findings["clinical_context"]

)


# ------------------------------------------------------------
# Call Gemini
# ------------------------------------------------------------

try:

    result = generate_llm_report(
        llm_prompt
    )


    # --------------------------------------------------------
    # Check report status
    # --------------------------------------------------------

    if result.get("status") != "DRAFT":

        raise RuntimeError(
            "Report status is not DRAFT"
        )


    # --------------------------------------------------------
    # Run KNEE-AI safety validator
    # --------------------------------------------------------

    validation_result, validation_message = (
        validate_llm_report(
            result,
            validated_findings
        )
    )


    # --------------------------------------------------------
    # Final result
    # --------------------------------------------------------

    if not validation_result:

        raise RuntimeError(
            validation_message
        )


    print("\n" + "=" * 60)
    print("LIVE GEMINI TEST PASSED")
    print("=" * 60)

    print("\nGenerated report:\n")

    print(result)

    print("\nStatus check: PASSED")
    print("Report status: DRAFT")

    print("\nSafety validation: PASSED")
    print(validation_message)

    print("\n" + "=" * 60)


except Exception as error:

    print("\n" + "=" * 60)
    print("LIVE GEMINI TEST FAILED")
    print("=" * 60)

    print("\nError:")
    print(error)

    print("\n" + "=" * 60)