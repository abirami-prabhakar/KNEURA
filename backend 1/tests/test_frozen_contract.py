import hashlib
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT.parent / "KNEE_AI_COMPLETE_BACKEND_PACKAGE"
LABELS = [
    "ACL", "MCL", "Medial Meniscus", "Lateral Meniscus", "Medial OA",
    "Lateral OA", "PF OA", "Effusion", "Synovitis", "Baker's",
    "Contusion", "Fracture",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_inference_file_is_byte_identical_to_canonical_copy():
    assert _sha256(ROOT / "ai" / "knee_ai_inference.py") == _sha256(
        PACKAGE / "01_MODEL_DEPLOYMENT" / "knee_ai_inference.py"
    )


def test_checkpoint_matches_official_hash():
    checkpoint = PACKAGE / "01_MODEL_DEPLOYMENT" / "best_5slice_model.pth"
    assert _sha256(checkpoint) == "ac59d8ce17a0b35c15189d691f7c6aa828f31a3dfe14601a02036a6c3b892a82"


def test_golden_case_contract_has_required_counts_and_order():
    golden = json.loads((PACKAGE / "04_GOLDEN_CASE" / "KNEE_AI_GOLDEN_CASE.json").read_text(encoding="utf-8"))
    assert golden["mri"]["series_evaluated"] == 3
    assert golden["mri"]["windows_evaluated"] == 44
    assert list(golden["ai"]["probabilities"]) == LABELS


@pytest.mark.skipif(not os.getenv("KNEE_AI_GOLDEN_STUDY_ROOT") or not os.getenv("KNEE_AI_GOLDEN_SERIES_METADATA_PATH"), reason="Canonical Golden Case DICOM data and metadata were not supplied.")
def test_golden_case_real_frozen_inference():
    """Runs only when the provider supplies the canonical Golden Case DICOM data."""
    import pandas as pd
    from ai import knee_ai_inference

    golden = json.loads((PACKAGE / "04_GOLDEN_CASE" / "KNEE_AI_GOLDEN_CASE.json").read_text(encoding="utf-8"))
    result = knee_ai_inference.analyze_study(
        golden["mri"]["study_instance_uid"],
        os.environ["KNEE_AI_GOLDEN_STUDY_ROOT"],
        pd.read_csv(os.environ["KNEE_AI_GOLDEN_SERIES_METADATA_PATH"]),
        os.environ.get("KNEE_AI_CHECKPOINT_PATH", str(PACKAGE / "01_MODEL_DEPLOYMENT" / "best_5slice_model.pth")),
        device="cpu",
    )
    assert result["study"]["series_evaluated"] == 3
    assert result["study"]["windows_evaluated"] == 44
    assert list(result["probabilities"]) == LABELS
    for label, expected in golden["ai"]["probabilities"].items():
        assert result["probabilities"][label] == pytest.approx(expected, abs=1.2e-7)
