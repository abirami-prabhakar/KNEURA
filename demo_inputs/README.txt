KNEE-AI 3.3 — REAL 10-STUDY DEMO INPUT PACKAGE
================================================

Purpose
-------
This package contains real RSNA knee MRI studies selected for
the KNEE-AI 3.3 demonstration.

The DICOM files are the actual MRI inputs used during the
10-study KNEE-AI 3.3 inference demonstration.

Number of studies
-----------------
10

Eligible-series rule
--------------------
Fluid_Sensitive == 1
AND
Fat_Suppression == 1

The package contains ONLY the eligible series used by the
frozen KNEE-AI 3.3 inference pipeline.

Model
-----
KNEE-AI 3.3

Architecture
------------
StandaloneFiveSliceEfficientNet
EfficientNet-B0
5-slice context
224 x 224 input
12 abnormality outputs

12 outputs
----------
ACL
MCL
Medial Meniscus
Lateral Meniscus
Medial OA
Lateral OA
PF OA
Effusion
Synovitis
Baker's
Contusion
Fracture

Important
---------
These are real RSNA dataset studies.

The ground-truth labels are included only for demonstration
and evaluation purposes.

The model output is AI-assisted abnormality identification.
It is NOT an autonomous diagnosis.

Radiologist review is required.

The included REFERENCE_AI_INFERENCE.csv contains the previously
generated KNEE-AI 3.3 inference results for these studies.

Package statistics
------------------
Studies: 10
Eligible series: 38
DICOM files copied: 1107
Missing series: 0

Directory structure
-------------------
KNEE_AI_10_DEMO_INPUTS/
|
+-- DICOM/
|   +-- StudyInstanceUID/
|       +-- SeriesInstanceUID/
|           +-- *.dcm
|
+-- DEMO_STUDY_SELECTION.csv
+-- DEMO_PATIENT_MRI_INFO.csv
+-- ELIGIBLE_SERIES_MANIFEST.csv
+-- GROUND_TRUTH_LABELS.csv
+-- REFERENCE_AI_INFERENCE.csv
+-- README.txt