# ============================================================
# KNEE-AI 3.3 — LLM SAFETY VALIDATOR
# ============================================================


def validate_llm_report(
    llm_report,
    validated_findings
):

    approved_findings = {
        finding["abnormality"].lower()
        for finding in validated_findings["findings"]
        if finding["status"] == "APPROVED"
    }

    rejected_findings = {
        finding["abnormality"].lower()
        for finding in validated_findings["findings"]
        if finding["status"] == "REJECTED"
    }

    report_text = str(llm_report).lower()

    aliases = {

        "acl": [
            "acl",
            "anterior cruciate ligament"
        ],

        "mcl": [
            "mcl",
            "medial collateral ligament"
        ],

        "medial meniscus": [
            "medial meniscus"
        ],

        "lateral meniscus": [
            "lateral meniscus"
        ],

        "medial oa": [
            "medial oa",
            "medial osteoarthritis",
            "medial compartment osteoarthritis"
        ],

        "lateral oa": [
            "lateral oa",
            "lateral osteoarthritis",
            "lateral compartment osteoarthritis"
        ],

        "pf oa": [
            "pf oa",
            "pf osteoarthritis",
            "patellofemoral osteoarthritis"
        ],

        "effusion": [
            "effusion"
        ],

        "synovitis": [
            "synovitis"
        ],

        "baker's": [
            "baker's",
            "bakers",
            "baker cyst",
            "baker's cyst"
        ],

        "contusion": [
            "contusion"
        ],

        "fracture": [
            "fracture"
        ]
    }

    # 1. EVERY APPROVED FINDING MUST BE PRESENT

    for finding in approved_findings:

        allowed_terms = aliases.get(
            finding,
            [finding]
        )

        if not any(
            term in report_text
            for term in allowed_terms
        ):

            return (
                False,
                f"Approved finding missing: {finding}"
            )

    # 2. REJECTED FINDINGS MUST NOT BE PRESENT

    for finding in rejected_findings:

        allowed_terms = aliases.get(
            finding,
            [finding]
        )

        if any(
            term in report_text
            for term in allowed_terms
        ):

            return (
                False,
                f"Rejected finding detected: {finding}"
            )

    # 3. REPORT MUST REMAIN DRAFT

    if llm_report.get("status") != "DRAFT":

        return (
            False,
            "Report is not marked as DRAFT"
        )

    # 4. TREATMENT RECOMMENDATION CHECK

    treatment_terms = [

        "take medication",
        "take medicine",
        "start medication",
        "start medicine",

        "surgery is recommended",
        "surgery recommended",

        "you should exercise",
        "do exercise",

        "do physiotherapy",
        "physiotherapy is recommended",

        "you should undergo surgery"
    ]

    for term in treatment_terms:

        if term in report_text:

            return (
                False,
                "Treatment recommendation detected"
            )

    # 5. SAFETY CHECK PASSED

    return (
        True,
        "LLM report passed safety validation"
    )