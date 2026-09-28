# KNEE-AI 3.3 — Grad-CAM Explainability

## Purpose

Grad-CAM is an explainability layer around the frozen KNEE-AI 3.3
MRI abnormality model.

It provides class-specific heatmaps showing regions of the selected
MRI input that contributed to the selected model output.

## Model

- Model: KNEE-AI 3.3
- Architecture: StandaloneFiveSliceEfficientNet
- Backbone: EfficientNet-B0
- Input: 5 consecutive MRI slices
- Input size: 224 x 224
- Outputs: 12 abnormalities

## Grad-CAM

Target layer:

`backbone.features.8.0`

Target layer type:

`Conv2d`

Target layer output channels:

`1280`

Grad-CAM is class-specific and generated for an individual
5-slice inference window.

## Important Safety Rule

Grad-CAM is an EXPLANATION, not a diagnosis.

It must NOT be interpreted as:

- proof of pathology
- ground-truth lesion localization
- segmentation
- an independent diagnostic result

It does not replace radiologist review.

## Prediction Pipeline

Grad-CAM does not modify:

- model weights
- model architecture
- model probabilities
- study-level aggregation
- clinical threshold policy

The official KNEE-AI study prediction remains:

`mean_probability_across_study_windows`

## Clinical Workflow

MRI
  ->
KNEE-AI 3.3
  ->
12 abnormality probabilities
  ->
Radiologist review
  ->
Class-specific Grad-CAM explanation
  ->
Approved findings
  ->
LLM report drafting
  ->
Radiologist final approval

## Included

- KNEE_AI_GRADCAM_CONTRACT.json
- GRADCAM_ALL_12_RESULTS.csv
- GRADCAM_ALL_12_RESULTS.json
- VISUALIZATIONS/

The visualization directory contains 12 MRI + Grad-CAM overlays,
one for each abnormality.

## Frontend

Frontend may display the MRI with the corresponding Grad-CAM
overlay for an abnormality selected by the user.

## Backend

Backend should preserve:

- model version
- abnormality
- probability
- series identifier
- window index
- five slice instance numbers

The frozen KNEE-AI prediction pipeline remains authoritative.
