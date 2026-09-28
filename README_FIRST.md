# KNEE-AI 3.3 — FINAL AI TEAM HANDOFF

This is the frozen AI integration package for KNEE-AI.

============================================================
MODEL
============================================================

Model:
KNEE-AI 3.3

Architecture:
StandaloneFiveSliceEfficientNet

Backbone:
EfficientNet-B0

Input:
5 consecutive MRI slices

Input size:
224 x 224

Outputs:
12 abnormality probabilities

Checkpoint SHA256:

ac59d8ce17a0b35c15189d691f7c6aa828f31a3dfe14601a02036a6c3b892a82


============================================================
EXACT CLASS ORDER
============================================================

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

DO NOT rename or reorder these classes.


============================================================
MRI INPUT PIPELINE
============================================================

Eligible series:

Fluid_Sensitive == 1
AND
Fat_Suppression == 1

Slices:
InstanceNumber ascending

Window:
5 consecutive slices

Study output:
Mean probability across study windows


============================================================
PREPROCESSING
============================================================

- DICOM pixel array -> float32
- MONOCHROME1 inversion when applicable
- 1st-99th percentile robust normalization
- clipping
- resize to 224x224
- bilinear interpolation
- learned 5 -> 3 slice projection
- EfficientNet-B0


============================================================
VALIDATED PERFORMANCE
============================================================

Validation studies:
9

Validation windows:
844

Validation series:
27

Study-level Macro AUROC:

0.713624338624339

See 02_PERFORMANCE for the complete evidence.


============================================================
CLINICAL SAFETY
============================================================

The model provides AI-assisted abnormality identification.

It does NOT provide autonomous diagnosis.

There is NO validated clinical threshold.

0.50 is exploratory display only.

Radiologist review is required.

The LLM receives only radiologist-approved findings.

Final reports require explicit radiologist approval.


============================================================
BACKEND
============================================================

Primary endpoint:

POST /api/v1/ai/analyze

See 04_BACKEND for the frozen backend contract.


============================================================
GOLDEN CASE
============================================================

Canonical integration case:

05_GOLDEN_CASE/KNEE_AI_GOLDEN_CASE.json

Expected:

3 eligible series
44 windows
12 AI outputs


============================================================
TEAM RULE
============================================================

Treat this package as the frozen AI contract.

Do not change:

- model outputs
- class names
- class order
- probability semantics
- clinical threshold assumptions
- radiologist review requirement
- approved-only LLM gate

If another component needs a new field,
discuss it with the AI/model owner before changing the contract.

---

# 🔥 GRAD-CAM EXPLAINABILITY — KNEE-AI 3.3

Grad-CAM has been added as a **validated explainability layer**
around the frozen KNEE-AI 3.3 model.

## What it provides

Class-specific Grad-CAM visualizations are available for all
12 abnormalities:

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

## Grad-CAM configuration

Target layer:

`backbone.features.8.0`

Input:

5-slice MRI window, 224 × 224

Output:

224 × 224 normalized heatmap

Grad-CAM is generated for an individual 5-slice inference
window and selected abnormality.

## Important clinical safety rule

Grad-CAM is a **model explanation**, not a diagnosis.

It must NOT be interpreted as:

- proof that a pathology is present
- ground-truth lesion localization
- segmentation
- an independent diagnostic result

Radiologist review remains mandatory.

## Prediction pipeline is unchanged

Grad-CAM does NOT modify:

- model weights
- model architecture
- preprocessing
- slice ordering
- class order
- probability values
- study-level aggregation
- clinical threshold policy

The authoritative KNEE-AI study prediction remains:

`mean_probability_across_study_windows`

## Grad-CAM artifacts

See:

`07_GRADCAM/`

It contains:

- `README.md`
- `KNEE_AI_GRADCAM_CONTRACT.json`
- `GRADCAM_ALL_12_RESULTS.csv`
- `GRADCAM_ALL_12_RESULTS.json`
- `VISUALIZATIONS/`

The visualization directory contains 12 MRI + Grad-CAM overlays.

---

# 👥 TEAM INTEGRATION GUIDE

## 🧠 AI / MRI

The frozen KNEE-AI 3.3 model is the authoritative AI component.

Do not modify:

- `.pth`
- preprocessing
- 5-slice context
- model architecture
- class order
- probability aggregation
- clinical threshold policy

The actual trained model weights are provided separately in:

`KNEE_AI_MODEL_DEPLOYMENT`

---

## 🔌 BACKEND

Backend should use BOTH:

1. `KNEE_AI_FINAL_TEAM_HANDOFF`
2. `KNEE_AI_MODEL_DEPLOYMENT`

The deployment package contains the actual trained checkpoint.

The team handoff contains the contracts and integration specifications.

Primary AI endpoint:

`POST /api/v1/ai/analyze`

Backend must preserve all 12 probability values and must not
convert them into an autonomous diagnosis.

Backend must enforce the radiologist-review workflow.

Relevant artifacts:

`04_BACKEND/`

---

## 🎨 FRONTEND

Frontend does NOT need the `.pth` model.

Frontend communicates with Backend through the defined APIs.

The interface should support:

- patient details
- MRI/study information
- 12 AI probabilities
- radiologist review of all 12 findings
- Grad-CAM visualization
- approved findings
- draft report
- final approval status

Grad-CAM resources are available under:

`07_GRADCAM/`

The frontend should display Grad-CAM as an explanation/heatmap,
not as confirmed pathology.

---

## 🤖 LLM

LLM does NOT need the `.pth` model.

LLM receives:

- radiologist-approved AI findings
- relevant clinical context

LLM must NOT receive rejected findings as reportable findings.

LLM must not independently create diagnoses from the AI output.

The generated report remains a DRAFT until explicit radiologist
final approval.

---

# 🔄 COMPLETE CLINICAL WORKFLOW

MRI
  ↓
KNEE-AI 3.3
  ↓
12 abnormality probabilities
  ↓
Grad-CAM explanation when required
  ↓
Radiologist reviews all 12 findings
  ↓
Approved findings only
  ↓
LLM generates DRAFT report
  ↓
Radiologist final approval
  ↓
FINAL clinical report

---

# 📦 PACKAGE DISTRIBUTION

## Main integration package

`KNEE_AI_FINAL_TEAM_HANDOFF.zip`

Contains:

- model reproducibility evidence
- performance evidence
- MRI provenance
- backend contracts
- golden case
- AI module
- patient schema
- Grad-CAM contract/results/visualizations
- integration documentation

## Separate model deployment package

`KNEE_AI_MODEL_DEPLOYMENT`

Contains:

- `best_5slice_model.pth`
- `knee_ai_inference.py`
- `MODEL_DEPLOYMENT_MANIFEST.json`
- deployment README

### Who needs what?

| Team | Required package |
|---|---|
| AI | Model deployment + team handoff |
| Backend | **Both packages** |
| Frontend | Team handoff |
| LLM | Team handoff |

The `.pth` model is intentionally kept separate from the main
integration handoff.

---

# 🚨 FROZEN AI RULE

The KNEE-AI 3.3 model and its validated inference pipeline are
FROZEN.

Integration teams should build around the contracts rather than
modify the AI implementation.

Do not introduce an unvalidated 0.50 clinical threshold.

AI probabilities are not final diagnoses.

Radiologist review and final report approval remain mandatory.
