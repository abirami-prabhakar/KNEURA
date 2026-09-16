# ============================================================
# KNEE-AI 3.3 — STRUCTURED REPORT GENERATOR
# ============================================================


from schemas.report_schema import create_report_schema


def generate_report(validated_findings):

    approved_findings = [
        finding
        for finding in validated_findings["findings"]
        if finding["status"] == "APPROVED"
    ]

    report_findings = []

    for finding in approved_findings:

        report_findings.append({
            "abnormality": finding["abnormality"],
            "status": "APPROVED"
        })

    report = create_report_schema(

        study_id=validated_findings["study_id"],

        findings=report_findings,

        impression=(
            "This draft contains only radiologist-approved findings."
        )
    )

    return report