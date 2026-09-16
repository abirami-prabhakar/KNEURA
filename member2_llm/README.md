# KNEE-AI 3.3 — Member 2
## LLM + Clinical Intelligence Pipeline

Member 2 is responsible for the controlled LLM layer of KNEE-AI 3.3.

The LLM is a controlled generation layer, not the diagnostic engine.

---

## Pipeline

AI predictions
↓
Radiologist validation
↓
Approved findings only
↓
LLM
↓
Draft report
↓
Safety validation
↓
Patient-friendly explanation
↓
Radiologist final approval

---

## Responsibilities

Member 2 handles:

- LLM prompt engineering
- Structured MRI draft report generation
- Patient-friendly explanation
- LLM safety validation
- Patient explanation safety validation
- Controlled LLM input
- Report formatting
- Integration documentation

---

## LLM Input Boundary

The LLM receives only:

- Study ID
- Radiologist-approved findings
- Authorized clinical context

Rejected findings are excluded from report-generating LLM input.

The LLM must NOT:

- Interpret raw MRI images
- Decide whether an AI prediction is correct
- Use rejected findings
- Invent abnormalities
- Invent clinical information
- Create unsupported diagnoses
- Provide treatment recommendations
- Finalize a clinical report

---

## Report Generation

The report generator creates a structured draft report.

Report status:

DRAFT

Final approval:

PENDING

The LLM cannot finalize the report.

The final clinical report requires radiologist approval.

---

## Patient Explanation

The patient explanation uses only:

- Radiologist-approved findings
- Authorized clinical context

The explanation:

- Uses simple language
- Explains medical terminology where appropriate
- Avoids unsupported diagnoses
- Avoids treatment recommendations
- Encourages discussion with the patient's doctor
- States that the explanation is based on radiologist-approved information

---

## Safety Validators

### Report Safety Validator

Checks:

- All approved findings are present
- Rejected findings are absent
- Report status is DRAFT

### Patient Safety Validator

Checks:

- Approved findings are present
- Rejected findings are absent
- Treatment recommendations are absent
- Doctor consultation message is present

---

## API Endpoints

### Report Generation

POST `/api/v1/report/generate`

Generates a controlled draft MRI report.

### Patient Explanation

POST `/api/v1/patient/explanation`

Generates a patient-friendly explanation from approved findings.

---

## Frozen Abnormality List

KNEE-AI 3.3 uses exactly 12 abnormalities:

1. ACL
2. MCL
3. Medial Meniscus
4. Lateral Meniscus
5. Medial OA
6. Lateral OA
7. PF OA
8. Effusion
9. Synovitis
10. Baker's
11. Contusion
12. Fracture

---

## Testing

Member 2 includes offline tests for:

- Structured report generation
- Approved-only LLM input
- Rejected finding detection
- Missing finding detection
- Draft status validation
- Patient explanation validation
- Treatment recommendation detection
- API contract validation
- Full Member 2 pipeline

Gemini API is not required for the offline tests.

---

## Current Validation Status

All Member 2 offline tests pass.

The full Member 2 offline pipeline passes.

Gemini live generation should only be tested when API quota is available.

---

## Final Safety Boundary

The LLM generates a DRAFT only.

Final workflow:

LLM
↓
DRAFT
↓
Radiologist review
↓
FINAL approval

No automatic diagnosis.

No automatic approval.

No treatment recommendations.

No unsupported clinical information.