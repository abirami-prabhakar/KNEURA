from fastapi import FastAPI

from services.report_generator import generate_report
from services.llm_service import generate_llm_report
from services.safety_validator import validate_llm_report
from services.report_schema_validator import validate_report_schema

from services.patient_explanation import generate_patient_explanation
from services.patient_safety_validator import validate_patient_explanation

from schemas.api_contract import create_llm_input


app = FastAPI(
    title="KNEE-AI 3.3 Member 2 LLM API",
    version="1.0.0"
)


@app.get("/")
def root():

    return {
        "service": "KNEE-AI 3.3 Member 2",
        "status": "running"
    }


@app.get("/health")
def health():

    return {
        "status": "healthy"
    }


# ============================================================
# REPORT GENERATION ENDPOINT
# ============================================================

@app.post("/api/v1/report/generate")
def generate_report_endpoint(validated_findings: dict):

    # 1. Create structured draft

    draft_report = generate_report(
        validated_findings
    )


    # 2. Create controlled LLM input

    llm_input = create_llm_input(
        study_id=validated_findings["study_id"],
        validated_findings=validated_findings["findings"],
        clinical_context=validated_findings.get(
            "clinical_context",
            ""
        )
    )


    # 3. Prepare approved findings for the prompt

    approved_findings = llm_input["approved_findings"]


    # 4. Load report prompt

    with open(
        "prompts/report_prompt.txt",
        "r",
        encoding="utf-8"
    ) as file:

        prompt_template = file.read()


    # 5. Fill the report prompt

    llm_prompt = prompt_template.format(
        study_id=llm_input["study_id"],
        validated_findings=approved_findings,
        clinical_context=llm_input["clinical_context"]
    )


    # 6. Generate LLM report

    llm_report = generate_llm_report(
        llm_prompt
    )


    # 7. Validate backend-generated draft report structure

    schema_result, schema_message = validate_report_schema(
        draft_report,
        llm_input["study_id"]
    )

    if not schema_result:
        raise ValueError(schema_message)


    # 8. Safety validation

    validation_result, validation_message = (
        validate_llm_report(
            llm_report,
            validated_findings
        )
    )


    # 9. Return report result

    return {

        "status": "DRAFT",

        "llm_input": llm_input,

        "llm_report": llm_report,

        "safety_validation": {
            "passed": validation_result,
            "message": validation_message
        },

        "report": draft_report,

        "final_approval": "PENDING"
    }


# ============================================================
# PATIENT EXPLANATION ENDPOINT
# ============================================================

@app.post("/api/v1/patient/explanation")
def patient_explanation_endpoint(validated_findings: dict):

    # 1. Keep ONLY radiologist-approved findings

    approved_findings = [
        finding
        for finding in validated_findings["findings"]
        if finding["status"] == "APPROVED"
    ]


    # 2. Load patient explanation prompt

    with open(
        "prompts/patient_prompt.txt",
        "r",
        encoding="utf-8"
    ) as file:

        prompt_template = file.read()


    # 3. Fill patient explanation prompt

    patient_prompt = prompt_template.format(
        study_id=validated_findings["study_id"],
        approved_findings=approved_findings,
        clinical_context=validated_findings.get(
            "clinical_context",
            ""
        )
    )


    # 4. Generate patient explanation

    patient_explanation = generate_patient_explanation(
        patient_prompt
    )


    # 5. Safety validation

    validation_result, validation_message = (
        validate_patient_explanation(
            patient_explanation,
            validated_findings
        )
    )


    # 6. Return patient explanation

    return {

        "patient_explanation": patient_explanation,

        "safety_validation": {
            "passed": validation_result,
            "message": validation_message
        }
    }