"""Backend adapter for the frozen KNEE-AI 3.3 implementation.

This file deliberately contains no model, DICOM, preprocessing, filtering, or
windowing logic.  Those behaviours remain solely in ai/knee_ai_inference.py.
"""

import hashlib
import importlib.util
import math
import os
from pathlib import Path
from types import ModuleType
from numbers import Real

import pandas as pd

from app.models.study import Study


EXPECTED_CHECKPOINT_SHA256 = "ac59d8ce17a0b35c15189d691f7c6aa828f31a3dfe14601a02036a6c3b892a82"
BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINT_PATH = (
    BACKEND_ROOT.parent
    / "KNEE_AI_COMPLETE_BACKEND_PACKAGE"
    / "01_MODEL_DEPLOYMENT"
    / "best_5slice_model.pth"
)
BACKEND_2_CHECKPOINT_PATH = BACKEND_ROOT.parent / "backend 2" / "ai" / "best_5slice_model.pth"


class AIIntegrationError(RuntimeError):
    """A safe, actionable error caused by unavailable or invalid AI inputs."""


def _configured_path(name: str, fallback: Path | None = None) -> Path | None:
    value = os.getenv(name)
    return Path(value).expanduser() if value else fallback


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FrozenKneeAIAdapter:
    def _load_module(self) -> ModuleType:
        module_path = BACKEND_ROOT / "ai" / "knee_ai_inference.py"
        if not module_path.is_file():
            raise AIIntegrationError("Frozen KNEE-AI inference module is unavailable.")
        spec = importlib.util.spec_from_file_location("knee_ai_inference", module_path)
        if spec is None or spec.loader is None:
            raise AIIntegrationError("Frozen KNEE-AI inference module could not be loaded.")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except (ImportError, OSError) as exc:
            raise AIIntegrationError(
                "KNEE-AI runtime dependencies are unavailable. See README.md setup instructions."
            ) from exc
        return module

    def analyze(self, study: Study) -> dict:
        if not isinstance(study.study_id, str) or not study.study_id.strip():
            raise AIIntegrationError("Study ID is invalid.")
        study_root = Path(study.study_root) if study.study_root else _configured_path("KNEE_AI_STUDY_ROOT")
        metadata_path = (
            Path(study.series_metadata_path)
            if study.series_metadata_path
            else _configured_path("KNEE_AI_SERIES_METADATA_PATH")
        )
        checkpoint_path = _configured_path("KNEE_AI_CHECKPOINT_PATH")
        if checkpoint_path is None:
            checkpoint_path = next(
                (
                    path
                    for path in (DEFAULT_CHECKPOINT_PATH, BACKEND_2_CHECKPOINT_PATH)
                    if path.is_file()
                ),
                DEFAULT_CHECKPOINT_PATH,
            )

        if study_root is None or not study_root.is_dir():
            raise AIIntegrationError("MRI study root is not configured or unavailable.")
        if metadata_path is None or not metadata_path.is_file():
            raise AIIntegrationError("Series metadata CSV is not configured or unavailable.")
        if checkpoint_path is None or not checkpoint_path.is_file():
            raise AIIntegrationError("Official KNEE-AI checkpoint is not configured or unavailable.")
        if _sha256(checkpoint_path) != EXPECTED_CHECKPOINT_SHA256:
            raise AIIntegrationError("Checkpoint integrity verification failed.")

        try:
            metadata = pd.read_csv(metadata_path)
        except Exception as exc:
            raise AIIntegrationError("Series metadata CSV could not be read.") from exc
        required = {"StudyInstanceUID", "SeriesInstanceUID", "Fluid_Sensitive", "Fat_Suppression"}
        if not required.issubset(metadata.columns):
            raise AIIntegrationError("Series metadata CSV is missing required KNEE-AI columns.")

        # The frozen module expects a directory containing SeriesInstanceUID
        # folders. A global dataset root may instead be arranged as
        # <dataset>/<StudyInstanceUID>/<SeriesInstanceUID>; resolve that
        # backend-side layout difference without changing frozen inference.
        study_directory = study_root / study.study_id
        inference_study_root = study_directory if study_directory.is_dir() else study_root

        module = self._load_module()
        if module.select_eligible_series(metadata, study.study_id).empty:
            raise AIIntegrationError(
                "No eligible fluid-sensitive, fat-suppressed MRI series was found. "
                "Supply suitable DICOM series and verify the series metadata CSV."
            )
        try:
            result = module.analyze_study(
                study.study_id,
                str(inference_study_root),
                metadata,
                str(checkpoint_path),
                device="cpu",
            )
        except (ValueError, RuntimeError) as exc:
            raise AIIntegrationError(
                "Frozen inference could not process this study. Verify readable DICOM pixels, "
                "InstanceNumber ordering, and at least five slices in an eligible MRI series."
            ) from exc
        if not isinstance(result, dict):
            raise AIIntegrationError("Frozen KNEE-AI returned an invalid result.")
        model_metadata = result.get("model")
        if not isinstance(model_metadata, dict) or (
            model_metadata.get("name") != "KNEE-AI 3.3"
            or model_metadata.get("architecture") != "StandaloneFiveSliceEfficientNet"
        ):
            raise AIIntegrationError("Frozen KNEE-AI returned unexpected model metadata.")

        probabilities = result.get("probabilities")
        labels = getattr(module, "ABNORMALITIES", ())
        if not isinstance(probabilities, dict) or list(probabilities) != list(labels):
            raise AIIntegrationError("Frozen KNEE-AI returned an invalid probability contract.")
        if len(probabilities) != 12:
            raise AIIntegrationError("Frozen KNEE-AI did not return all 12 probabilities.")
        if any(
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(float(value))
            or not 0.0 <= float(value) <= 1.0
            for value in probabilities.values()
        ):
            raise AIIntegrationError("Frozen KNEE-AI returned probabilities outside the valid range.")
        return result

    def generate_gradcam(
        self,
        study: Study,
        abnormality: str,
        series_instance_uid: str | None = None,
        window_index: int | None = None,
    ) -> dict:
        if not isinstance(study.study_id, str) or not study.study_id.strip():
            raise AIIntegrationError("Study ID is invalid.")

        module = self._load_module()
        labels = getattr(module, "ABNORMALITIES", ())
        if abnormality not in labels:
            raise AIIntegrationError(f"Abnormality '{abnormality}' is not one of the 12 canonical abnormalities.")
        class_index = list(labels).index(abnormality)

        gradcam_module_path = BACKEND_ROOT / "ai" / "knee_ai_gradcam.py"
        if not gradcam_module_path.is_file():
            raise AIIntegrationError("Grad-CAM module is unavailable.")
        gspec = importlib.util.spec_from_file_location("knee_ai_gradcam", gradcam_module_path)
        if gspec is None or gspec.loader is None:
            raise AIIntegrationError("Grad-CAM module could not be loaded.")
        gradcam_module = importlib.util.module_from_spec(gspec)
        try:
            gspec.loader.exec_module(gradcam_module)
        except Exception as exc:
            raise AIIntegrationError("Grad-CAM module failed to execute.") from exc

        study_root = Path(study.study_root) if study.study_root else _configured_path("KNEE_AI_STUDY_ROOT")
        metadata_path = (
            Path(study.series_metadata_path)
            if study.series_metadata_path
            else _configured_path("KNEE_AI_SERIES_METADATA_PATH")
        )
        checkpoint_path = _configured_path("KNEE_AI_CHECKPOINT_PATH")
        if checkpoint_path is None:
            checkpoint_path = next(
                (
                    path
                    for path in (DEFAULT_CHECKPOINT_PATH, BACKEND_2_CHECKPOINT_PATH)
                    if path.is_file()
                ),
                DEFAULT_CHECKPOINT_PATH,
            )

        if study_root is None or not study_root.is_dir():
            raise AIIntegrationError("MRI study root is not configured or unavailable.")
        if metadata_path is None or not metadata_path.is_file():
            raise AIIntegrationError("Series metadata CSV is not configured or unavailable.")
        if checkpoint_path is None or not checkpoint_path.is_file():
            raise AIIntegrationError("Official KNEE-AI checkpoint is not configured or unavailable.")
        if _sha256(checkpoint_path) != EXPECTED_CHECKPOINT_SHA256:
            raise AIIntegrationError("Checkpoint integrity verification failed.")

        try:
            metadata = pd.read_csv(metadata_path)
        except Exception as exc:
            raise AIIntegrationError("Series metadata CSV could not be read.") from exc

        import torch

        study_directory = study_root / study.study_id
        inference_study_root = study_directory if study_directory.is_dir() else study_root

        model = module.load_model(str(checkpoint_path), device="cpu")
        eligible = module.select_eligible_series(metadata, study.study_id)
        if eligible.empty:
            raise AIIntegrationError("No eligible series found for this study.")

        target_series_row = None
        if series_instance_uid is not None:
            matches = eligible[eligible["SeriesInstanceUID"] == series_instance_uid]
            if matches.empty:
                raise AIIntegrationError(f"SeriesInstanceUID {series_instance_uid} is not eligible or not in study.")
            target_series_row = matches.iloc[0]

        selected_tensor = None
        selected_prob = None
        selected_series_uid = None
        selected_window_idx = None
        selected_instance_numbers = None
        selected_plane = None

        series_to_scan = [target_series_row] if target_series_row is not None else [row for _, row in eligible.iterrows()]

        best_prob = -1.0
        for s_row in series_to_scan:
            s_uid = str(s_row["SeriesInstanceUID"])
            s_path = os.path.join(inference_study_root, s_uid)
            if not os.path.isdir(s_path):
                continue
            plane = s_row.get("Anatomical_Plane", None) if "Anatomical_Plane" in s_row else None
            if not plane and "SeriesDescription" in s_row:
                desc = str(s_row["SeriesDescription"]).lower()
                if "sag" in desc:
                    plane = "Sagittal"
                elif "cor" in desc:
                    plane = "Coronal"
                elif "ax" in desc:
                    plane = "Axial"
            ordered_records = module.load_ordered_series(s_path)
            windows = module.create_windows(ordered_records)
            for w_idx, win in enumerate(windows):
                if window_index is not None and target_series_row is not None and w_idx != window_index:
                    continue
                x = module.window_to_tensor(win)
                with torch.no_grad():
                    logits = model(x)
                    prob = float(torch.sigmoid(logits[0, class_index]).item())
                if target_series_row is not None and window_index is not None:
                    selected_tensor = x
                    selected_prob = prob
                    selected_series_uid = s_uid
                    selected_window_idx = w_idx
                    selected_instance_numbers = [rec["InstanceNumber"] for rec in win]
                    selected_plane = plane
                    break
                elif prob > best_prob:
                    best_prob = prob
                    selected_tensor = x
                    selected_prob = prob
                    selected_series_uid = s_uid
                    selected_window_idx = w_idx
                    selected_instance_numbers = [rec["InstanceNumber"] for rec in win]
                    selected_plane = plane
            if selected_tensor is not None and target_series_row is not None and window_index is not None:
                break

        if selected_tensor is None:
            raise AIIntegrationError("No valid 5-slice window found for Grad-CAM generation.")

        heatmap, cam_prob = gradcam_module.generate_gradcam(model, selected_tensor, class_index)

        return {
            "model_version": "KNEE-AI 3.3",
            "abnormality": abnormality,
            "class_index": class_index,
            "probability": selected_prob,
            "plane": selected_plane or "Unknown",
            "series_instance_uid": selected_series_uid,
            "window_index": selected_window_idx,
            "instance_numbers": selected_instance_numbers,
            "heatmap": heatmap.tolist(),
        }
