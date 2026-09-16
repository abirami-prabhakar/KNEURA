"""Run the ORIGINAL backend 2 frozen model and compare unmodified probabilities."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend 1"))
import pandas as pd
import torch
from app.ai_adapter import EXPECTED_CHECKPOINT_SHA256
from app.llm_adapter import CANONICAL_ABNORMALITIES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    data = ROOT / "demo_inputs"
    checkpoint = ROOT / "backend 2/ai/best_5slice_model.pth"
    source = ROOT / "backend 2/ai/knee_ai_inference.py"
    actual_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert actual_hash == EXPECTED_CHECKPOINT_SHA256
    assert source.read_bytes() == (ROOT / "backend 1/ai/knee_ai_inference.py").read_bytes()
    spec = importlib.util.spec_from_file_location("original_backend2_inference", source)
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    assert model.ABNORMALITIES == CANONICAL_ABNORMALITIES
    torch.set_num_threads(2)
    manifest = pd.read_csv(data / "ELIGIBLE_SERIES_MANIFEST.csv")
    reference = pd.read_csv(data / "REFERENCE_AI_INFERENCE.csv", float_precision="round_trip")
    assert list(reference.columns[3:]) == CANONICAL_ABNORMALITIES
    assert len(reference) == manifest.StudyInstanceUID.nunique() == 10
    assert len(list((data / "DICOM").rglob("*.dcm"))) == 1107
    assert len(manifest) == 38
    assert ((manifest.Fluid_Sensitive == 1) & (manifest.Fat_Suppression == 1)).all()
    output = ROOT / "verification"
    output.mkdir(exist_ok=True)
    rows = []
    results = []
    for index, ref in reference.head(args.limit).iterrows():
        start = time.monotonic()
        uid = ref.StudyInstanceUID
        result = model.analyze_study(uid, str(data / "DICOM" / uid), manifest, str(checkpoint), device="cpu")
        assert list(result["probabilities"]) == CANONICAL_ABNORMALITIES
        differences = {label: abs(result["probabilities"][label] - float(ref[label])) for label in CANONICAL_ABNORMALITIES}
        count_match = all(result["study"][field] == int(ref[field]) for field in ("series_evaluated", "windows_evaluated"))
        maximum = max(differences.values())
        elapsed = round(time.monotonic() - start, 2)
        results.append({"case": int(index) + 1, "study_id": uid, "counts_match": count_match,
                        "max_absolute_difference": maximum, "bit_exact": maximum == 0,
                        "within_1e_6": maximum <= 1e-6, "elapsed_seconds": elapsed,
                        "series_evaluated": result["study"]["series_evaluated"],
                        "windows_evaluated": result["study"]["windows_evaluated"]})
        for label in CANONICAL_ABNORMALITIES:
            rows.append({"case": int(index) + 1, "StudyInstanceUID": uid, "class": label,
                         "reference": float(ref[label]), "actual": result["probabilities"][label], "absolute_difference": differences[label]})
        summary = {"checkpoint_sha256": actual_hash, "studies_detected": 10, "dicom_files": 1107,
                   "eligible_series": 38, "implementation": str(source.relative_to(ROOT)),
                   "tolerance": 1e-6, "torch": torch.__version__, "results": results,
                   "maximum_probability_difference": max(r["max_absolute_difference"] for r in results)}
        (output / "model1_results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        pd.DataFrame(rows).to_csv(output / "model1_probability_comparison.csv", index=False)
        print(f"Case {index + 1}: {elapsed}s; series/windows={result['study']['series_evaluated']}/{result['study']['windows_evaluated']}; max difference={maximum:.12g}; counts match={count_match}", flush=True)
    assert all(r["counts_match"] and r["within_1e_6"] for r in results), "Reference mismatch; inspect saved comparison, do not alter model outputs."


if __name__ == "__main__":
    main()
