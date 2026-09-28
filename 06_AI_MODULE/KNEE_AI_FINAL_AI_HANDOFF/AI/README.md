
# KNEE-AI 3.3 Standalone Inference Module

This module implements the validated KNEE-AI 3.3 inference pipeline.

## Model

StandaloneFiveSliceEfficientNet
EfficientNet-B0
5-slice input
12 abnormality outputs

## Preprocessing

- DICOM pixel array
- MONOCHROME1 inversion
- 1st–99th percentile normalization
- clipping
- 224 × 224 resize
- bilinear interpolation
- float32 tensor

## Series selection

Fluid_Sensitive == 1
AND
Fat_Suppression == 1

## Slice ordering

InstanceNumber ascending.

## Windows

5 consecutive slices
Stride = 1

## Study aggregation

Mean probability across all study windows.

## Clinical safety

AI probabilities are not final diagnoses.
No validated clinical threshold is implemented.
Clinician review is required.
