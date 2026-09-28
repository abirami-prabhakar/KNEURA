KNEE-AI 3.3 — FINAL AI TEAM HANDOFF
====================================

Purpose
-------
This package contains the frozen KNEE-AI 3.3 AI inference
implementation and the contracts required for integration
with the backend, frontend, and LLM components.

AUTHORITATIVE AI MODULE
-----------------------
AI/knee_ai_inference.py

Model
-----
Architecture:
StandaloneFiveSliceEfficientNet

Backbone:
EfficientNet-B0

Input:
5 consecutive MRI slices

Output:
12 abnormality probabilities

Series selection:
Fluid_Sensitive == 1 AND Fat_Suppression == 1

Slice ordering:
InstanceNumber ascending

Study aggregation:
Mean probability across study windows

Clinical safety
---------------
The AI produces probability outputs for clinician review.

There is NO validated clinical decision threshold.

The AI does NOT make an autonomous final diagnosis.

Radiologist review is required.

LLM workflow
------------
Only radiologist-approved AI findings should be passed
to the LLM.

The LLM generates a draft report.

Final radiologist approval is required.

Validation
----------
Champion checkpoint fingerprint verified.

Standalone reproduction:
PASS

Clean-process deployment:
PASS

Target study:
3 eligible series
44 windows
12 outputs

Maximum probability reproduction difference:
1.1920928955078125e-07

Contracts
---------
CONTRACTS/KNEE_AI_FINAL_AI_BACKEND_HANDOFF.json
CONTRACTS/KNEE_AI_PATIENT_DETAILS_SCHEMA.json

Demo
----
DEMO/KNEE_AI_COMPLETE_DEMO_CASE.json

Validation evidence
-------------------
VALIDATION/VALIDATION_SUMMARY.json

IMPORTANT
---------
Do not modify the model architecture, preprocessing,
checkpoint identity, windowing, ordering, or aggregation
without re-running the validation process and updating
the model version.


INTEGRATION
-----------

Canonical integration test case:

INTEGRATION/KNEE_AI_GOLDEN_CASE.json

Integration manifest:

INTEGRATION/INTEGRATION_MANIFEST.json

Golden case SHA256:
26c55fd96e9752b1a2cd5a885fe2dc3be554b6dfc668bb3c97eb486f75bb45df

This golden case is the canonical reference for
frontend, backend, AI and LLM integration testing.

Do not modify the golden case without creating
a new version and re-running validation.
