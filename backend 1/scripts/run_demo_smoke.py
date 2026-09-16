"""Run one real KNEE-AI demo study through the FastAPI endpoint.

The reference CSV is used only to compare an already-computed API response;
it is never used as an inference input or response source.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


LABELS = [
    "ACL", "MCL", "Medial Meniscus", "Lateral Meniscus", "Medial OA",
    "Lateral OA", "PF OA", "Effusion", "Synovitis", "Baker's",
    "Contusion", "Fracture",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-root", type=Path, required=True)
    parser.add_argument("--study-id", required=True)
    args = parser.parse_args()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ai/analyze",
            json={"study_id": args.study_id, "action": "ANALYZE_KNEE_MRI"},
        )
    print(f"HTTP {response.status_code}")
    body = response.json()
    print(json.dumps(body, indent=2))
    response.raise_for_status()

    reference = pd.read_csv(args.demo_root / "REFERENCE_AI_INFERENCE.csv")
    expected = reference.loc[
        reference["StudyInstanceUID"].astype(str) == args.study_id
    ].iloc[0]
    max_difference = max(
        abs(body["probabilities"][label] - float(expected[label]))
        for label in LABELS
    )
    print(f"Maximum absolute difference from reference: {max_difference:.12g}")


if __name__ == "__main__":
    main()
