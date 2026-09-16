# ============================================================
# KNEE-AI 3.3 - MEMBER 2 REPORT SCHEMA
# ============================================================


REPORT_STATUS_DRAFT = "DRAFT"
FINAL_APPROVAL_PENDING = "PENDING"


def create_report_schema(
    study_id,
    findings,
    impression
):
    """
    Create the standard KNEE-AI draft report structure.

    The report is always created as DRAFT.
    Final approval must be performed by a radiologist.
    """

    return {
        "title": "Knee MRI Report",

        "study_id": study_id,

        "status": REPORT_STATUS_DRAFT,

        "findings": findings,

        "impression": impression,

        "note": (
            "This is an AI-generated draft based on "
            "radiologist-approved information and requires "
            "radiologist review and final approval."
        ),

        "final_approval": FINAL_APPROVAL_PENDING
    }