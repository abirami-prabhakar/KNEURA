# ============================================================
# KNEE-AI 3.3 — PATIENT EXPLANATION SAFETY VALIDATOR
# ============================================================


def validate_patient_explanation(
    patient_explanation,
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

    explanation_text = str(
        patient_explanation
    ).lower()


    # ========================================================
    # ALIASES
    # ========================================================

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


    # ========================================================
    # 1. APPROVED FINDINGS MUST BE EXPLAINED
    # ========================================================

    for finding in approved_findings:

        allowed_terms = aliases.get(
            finding,
            [finding]
        )

        if not any(
            term in explanation_text
            for term in allowed_terms
        ):

            return (
                False,
                f"Approved finding missing: {finding}"
            )


    # ========================================================
    # 2. REJECTED FINDINGS MUST NOT APPEAR
    # ========================================================

    for finding in rejected_findings:

        allowed_terms = aliases.get(
            finding,
            [finding]
        )

        if any(
            term in explanation_text
            for term in allowed_terms
        ):

            return (
                False,
                f"Rejected finding detected: {finding}"
            )


    # ========================================================
    # 3. TREATMENT RECOMMENDATION CHECK
    # ========================================================

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

        if term in explanation_text:

            return (
                False,
                "Treatment recommendation detected"
            )


    # ========================================================
    # 4. DOCTOR CONSULTATION MESSAGE
    # ========================================================

    if "doctor" not in explanation_text:

        return (
            False,
            "Doctor consultation message missing"
        )


    # ========================================================
    # 5. SAFETY PASSED
    # ========================================================

    return (
        True,
        "Patient explanation passed safety validation"
    )