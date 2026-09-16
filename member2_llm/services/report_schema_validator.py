def validate_report_schema(report, expected_study_id):

    required_fields = [
        "title",
        "study_id",
        "status",
        "findings",
        "impression",
        "note"
    ]

    for field in required_fields:
        if field not in report:
            return False, f"Missing required field: {field}"

    if report["title"] != "Knee MRI Report":
        return False, "Invalid report title"

    if report["study_id"] != expected_study_id:
        return False, "Study ID mismatch"

    if report["status"] != "DRAFT":
        return False, "Report status must be DRAFT"

    if not isinstance(report["findings"], list):
        return False, "Findings must be a list"

    if not isinstance(report["impression"], str):
        return False, "Impression must be a string"

    if not isinstance(report["note"], str):
        return False, "Note must be a string"

    return True, "Report schema validation passed"