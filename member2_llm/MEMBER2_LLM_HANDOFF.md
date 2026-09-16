# KNEE-AI 3.3 — MEMBER 2 LLM HANDOFF

## 1. Module Ownership

Member 2 owns the **LLM Pipeline & Clinical Intelligence** layer.

The LLM is a **controlled generation layer, not the diagnostic engine**.

Member 2 is responsible for:

* Approved-finding → LLM input preparation
* Grounded draft report generation
* Patient-friendly explanation generation
* Report schema validation
* LLM safety validation
* Patient explanation safety validation
* LLM failure handling
* LLM testing and evidence

---

# 2. LLM Input Boundary

The LLM MUST receive only:

1. Radiologist-approved findings
2. Authorized clinical context

The LLM MUST NOT:

* Interpret raw MRI data
* Decide whether an AI prediction is correct
* Diagnose directly from AI probabilities
* Generate unsupported abnormalities
* Invent patient information
* Override radiologist decisions
* Receive rejected findings as report-generating findings
* Finalize the clinical report
* Provide treatment recommendations

---

# 3. Approved Finding Contract

Member 2 expects findings in this structure:

```json
{
  "abnormality": "...",
  "probability": 0.0,
  "status": "APPROVED"
}
```

Rules:

* `abnormality` must use the canonical KNEE-AI 3.3 name.
* `probability` is the original Model 1 probability.
* Member 2 MUST NOT calculate a new confidence score.
* Only `APPROVED` findings may reach the LLM.
* `PENDING` findings are blocked.
* `REJECTED` findings are blocked.

---

# 4. Canonical Abnormality Names

The exact KNEE-AI 3.3 abnormality names are:

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

These names and their order must not be changed.

---

# 5. LLM Input Example

Example input after radiologist validation:

```json
{
  "study_id": "<BACKEND_SUPPLIED_STUDY_ID>",
  "approved_findings": [
    {
      "abnormality": "Medial Meniscus",
      "probability": 0.5337309241,
      "status": "APPROVED"
    },
    {
      "abnormality": "Lateral Meniscus",
      "probability": 0.9094741344,
      "status": "APPROVED"
    }
  ],
  "clinical_context": "Persistent knee pain with activity."
}
```

`<BACKEND_SUPPLIED_STUDY_ID>` is a placeholder only.

The real `study_id` is supplied by the backend at runtime.

Only approved findings are passed to the LLM.

---

# 6. Study ID Handling

Member 2 does NOT generate the real study ID.

The backend supplies the real `study_id`.

Member 2 must preserve the supplied `study_id`.

The LLM must not create or replace the study ID.

The flow is:

```text
Backend
   ↓
study_id
   ↓
Member 2
   ↓
LLM
   ↓
same study_id in DRAFT report
```

Member 2 documentation and test examples must not imply that a fixed demo study ID is required.

---

# 7. Authorized Clinical Context

Authorized clinical context may include:

* Age
* Sex
* Symptoms
* Medical history
* Clinical notes

Only information authorized by the backend should be provided.

Unnecessary imaging identifiers must NOT be sent to the LLM, including:

* PatientID
* StudyInstanceUID
* SeriesInstanceUID

---

# 8. LLM-Generated Draft Report

Gemini generates the following report fields:

```json
{
  "title": "Knee MRI Report",
  "study_id": "...",
  "status": "DRAFT",
  "findings": [],
  "impression": "...",
  "note": "This is an AI-generated draft based on radiologist-approved information and requires radiologist review and final approval."
}
```

The LLM-generated report does **NOT** contain `final_approval`.

`final_approval` is a backend/workflow state and must not be controlled by Gemini.

---

# 9. Final Approval State

The backend/structured report layer owns:

```text
final_approval = PENDING
```

The correct workflow is:

```text
Approved findings
      ↓
Gemini
      ↓
DRAFT report
      ↓
Backend adds/maintains:
final_approval = PENDING
      ↓
Radiologist review
      ↓
Backend-controlled approval
      ↓
FINAL
```

Gemini MUST NOT:

* Set `final_approval`
* Change `final_approval` to `APPROVED`
* Change the report to `FINAL`

Only the backend/workflow and authorized radiologist approval process control the final state.

---

# 10. Report Safety Rules

The generated report must:

* Use only approved findings
* Exclude rejected findings
* Remain grounded in authorized clinical context
* Remain marked `DRAFT`
* Clearly require radiologist review
* Avoid unsupported diagnoses
* Avoid treatment recommendations

The LLM must not recommend:

* Medication
* Surgery
* Exercises
* Physiotherapy
* Other treatments

---

# 11. Patient-Friendly Explanation

The patient explanation is generated only from:

* Radiologist-approved findings
* Authorized clinical context

It must NOT be generated from:

* Raw MRI
* Raw AI predictions
* Rejected findings
* Unsupported information

The explanation must:

* Use simple language
* Avoid unnecessary fear
* Explain terminology where appropriate
* State that it is based on radiologist-approved information
* Encourage discussion with the patient's doctor
* Not replace medical advice
* Not provide treatment recommendations

---

# 12. Human-in-the-Loop Requirement

The mandatory workflow is:

```text
AI prediction
      ↓
Radiologist validation
      ↓
APPROVED / REJECTED
      ↓
APPROVED findings only
      ↓
LLM
```

There is NO automatic approval.

All 12 AI findings require explicit radiologist review.

---

# 13. Safety Validation

Generated reports are passed through a safety validator.

The validator checks:

* Approved findings are present
* Rejected findings are not present
* Report remains `DRAFT`
* Unsupported content is rejected
* Treatment recommendations are rejected

Patient explanations are separately checked by the patient safety validator.

---

# 14. Failure Handling

Gemini/API failures must never result in a fake report.

Recognized unavailable conditions include:

* HTTP 503
* HTTP 429 / quota condition

The LLM service retries temporary 503 failures.

If the LLM remains unavailable:

```text
LLM failure
   ↓
No fake report
   ↓
Error returned to caller
   ↓
Manual workflow can continue safely
```

---

# 15. Gemini Configuration

The Gemini model is centrally configured in:

```text
services/config.py
```

Current configuration:

```python
GEMINI_MODEL = "gemini-3.7-flash"
```

The API key is read using:

```text
GEMINI_API_KEY
```

Both report generation and patient explanation use the shared model configuration.

---

# 16. Testing Evidence

## Offline Unit Tests

```text
ALL MEMBER 2 OFFLINE TESTS PASSED
```

**8/8 tests passed.**

Verified:

1. Structured report contains approved findings only
2. Valid LLM draft accepted
3. Rejected finding detected
4. Missing approved finding detected
5. FINAL report rejected
6. Patient explanation accepted
7. Treatment recommendation detected
8. LLM input contains approved findings only

---

## L1 — Grounding

```text
L1 GROUNDING TEST PASSED
```

Verified:

* Approved finding was included
* Unsupported abnormality was not generated
* Report remained DRAFT
* LLM remained grounded to supplied information

---

## L2 — Human-in-the-Loop

```text
L2 HUMAN-IN-THE-LOOP TEST PASSED
```

Verified:

```text
Unvalidated finding → BLOCKED
Approved finding    → ALLOWED
```

---

## L3 — Safety Constraints

```text
L3 SAFETY CONSTRAINT TEST PASSED
```

Verified:

* Approved MCL finding preserved
* Unsupported ACL tear not generated
* Medication recommendation not generated
* Surgery recommendation not generated
* Physiotherapy recommendation not generated
* Report remains DRAFT

---

## L4 — Failure Handling

```text
L4 FAILURE HANDLING TEST PASSED
```

Verified:

* LLM unavailable condition detected
* No fake report generated
* Exception returned to caller
* Manual workflow can continue safely

---

# 17. Full Offline Pipeline

The complete Member 2 pipeline passed:

```text
AI findings
     ↓
Radiologist validation
     ↓
Approved findings only
     ↓
LLM draft report
     ↓
Safety validation
     ↓
Patient-friendly explanation
     ↓
Radiologist final approval required
```

Final workflow state:

```text
Report = DRAFT
Final approval = PENDING
```

Gemini API was not required for the offline pipeline.

---

# 18. Backend Integration Contract

Member 3 / Backend provides Member 2 with:

```text
study_id
approved_findings
authorized_clinical_context
```

Member 2 returns:

```text
draft_report
patient_explanation
```

The backend remains responsible for:

* Authentication
* Authorization
* RBAC
* Database
* Study linkage
* Radiologist validation state
* Workflow state
* `final_approval`
* Final approval
* API orchestration

---

# 19. Integration Boundary

Final integration:

```text
Backend
   ↓
AI predictions
   ↓
Radiologist validation
   ↓
Approved findings
   ↓
Member 2 LLM pipeline
   ↓
DRAFT report
   ↓
Schema validation
   ↓
Safety validation
   ↓
Patient explanation
   ↓
Backend
   ↓
Radiologist final approval
   ↓
FINAL
```

---

# 20. Member 2 Must Not Modify

Member 2 must not modify:

* Model 1 predictions
* Model architecture
* Model checkpoint
* AI preprocessing
* AI inference
* Grad-CAM
* Canonical abnormality names
* Probability values
* Radiologist validation decisions
* Backend workflow state

Member 2 consumes the approved output of the previous stage.

---

# 21. Current Completion Status

```text
Member 2 LLM Pipeline

Core implementation             ✅
Approved-only filtering         ✅
Grounding                       ✅
Human-in-loop                   ✅
Report generation               ✅
Patient explanation             ✅
Report schema validation        ✅
Safety validation               ✅
Patient safety validation       ✅
Failure handling                ✅
Offline tests                   ✅ 8/8
L1                              ✅
L2                              ✅
L3                              ✅
L4                              ✅
Duplicate folder removed        ✅
Handoff document                ✅

Backend live integration        ⏳ Member 3
Current live Gemini check       ⏳
```

---

# 22. Final Architecture Principle

**The LLM does not diagnose.**

It converts **radiologist-approved clinical information** into:

1. A controlled **DRAFT knee MRI report**
2. A controlled **patient-friendly explanation**

The **radiologist remains the final clinical authority**.

`final_approval` and the transition from `DRAFT` to `FINAL` are **backend/workflow responsibilities**, not Gemini responsibilities.

The real `study_id` is always supplied by the backend and must never be hardcoded by Member 2 or Gemini.
