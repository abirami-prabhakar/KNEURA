"""Real package loading and provider wiring, without network calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ORIGINAL = BACKEND.parent / "member2_llm"


@pytest.mark.parametrize("location", ["default", "absolute", "relative", "home", "missing", "file", "incomplete"])
def test_package_location_in_fresh_process(tmp_path, location):
    env = dict(os.environ, PYTHONPATH=str(BACKEND), PYTHONDONTWRITEBYTECODE="1")
    env.pop("KNEE_AI_MEMBER2_PATH", None)
    expected = ORIGINAL
    if location != "default":
        expected = tmp_path / "original member2"
        if location in {"absolute", "relative", "home"}:
            shutil.copytree(ORIGINAL, expected, ignore=shutil.ignore_patterns("__pycache__"))
        elif location == "file":
            expected.write_text("not a directory")
        elif location == "incomplete":
            expected.mkdir()
        env["KNEE_AI_MEMBER2_PATH"] = str(expected)
        if location == "relative":
            env["KNEE_AI_MEMBER2_PATH"] = "original member2/../original member2"
        elif location == "home":
            env["USERPROFILE"] = env["HOME"] = str(tmp_path)
            env["KNEE_AI_MEMBER2_PATH"] = "~/original member2"
    script = '''
import inspect, json
from app import llm_adapter as a
errors = []
for method in ("generate_report", "generate_patient_explanation"):
    try:
        a._require_member2_runtime()
    except a.LLMIntegrationError:
        try:
            getattr(a.Member2ClinicalLLMAdapter(), method)("synthetic", [], [])
        except a.LLMIntegrationError as exc:
            errors.append(str(exc))
print(json.dumps({"path": str(a.MEMBER2_DIR), "errors": errors,
    "source": inspect.getfile(a.create_llm_input) if a.create_llm_input else None}))
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                            env=env, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert Path(data["path"]) == expected.resolve()
    if location in {"missing", "file", "incomplete"}:
        assert len(data["errors"]) == 2
        assert all(str(expected) in error and "KNEE_AI_MEMBER2_PATH" in error
                   for error in data["errors"])
        assert data["source"] is None
    else:
        assert data["errors"] == []
        assert Path(data["source"]).is_relative_to(expected)


@pytest.mark.parametrize("patient", [False, True])
@pytest.mark.parametrize("unsafe", [False, True])
def test_original_provider_and_validators(monkeypatch, patient, unsafe):
    from app.llm_adapter import Member2ClinicalLLMAdapter, LLMIntegrationError
    from google import genai
    from services.config import GEMINI_MODEL

    result = {
        "title": "Knee MRI Report", "study_id": "synthetic", "status": "DRAFT",
        "findings": ["Effusion."], "impression": "Effusion.",
        "note": "Requires radiologist review and final approval.",
    }
    if patient:
        result = {"title": "Patient-Friendly MRI Explanation", "study_id": "synthetic",
                  "approved_findings": "Effusion.", "what_this_means": "Fluid in the joint.",
                  "important_note": "Based on radiologist-approved information. Discuss with your doctor."}
    if unsafe:
        result["extra"] = "ACL tear."
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps(result))

    def client(**kwargs):
        assert kwargs == {"api_key": "synthetic-key-not-sent"}
        return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key-not-sent")
    monkeypatch.setattr(genai, "Client", client)
    adapter = Member2ClinicalLLMAdapter()
    method = adapter.generate_patient_explanation if patient else adapter.generate_report
    args = ("synthetic", [{"finding": "Effusion", "outcome": "CONFIRMED"}],
            [{"label": "Effusion", "confidence": 0.6}])
    if unsafe:
        with pytest.raises(LLMIntegrationError, match="safety validation failed"):
            method(*args)
    else:
        output = method(*args)
        if patient:
            assert output == result
        else:
            assert json.loads(output) == dict(result, final_approval="PENDING")
    assert len(calls) == 1
    assert calls[0]["model"] == GEMINI_MODEL
    assert "Effusion" in calls[0]["contents"]
    assert calls[0]["config"].response_mime_type == "application/json"
