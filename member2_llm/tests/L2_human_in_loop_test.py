import sys
import os

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)

from schemas.api_contract import create_llm_input


# ============================================================
# KNEE-AI 3.3 — L2 HUMAN-IN-THE-LOOP TEST
# ============================================================


print("\n" + "=" * 60)
print("KNEE-AI 3.3 — L2 HUMAN-IN-THE-LOOP TEST")
print("=" * 60)


# ------------------------------------------------------------
# TEST 1 — AI prediction NOT validated
# ------------------------------------------------------------

unvalidated_findings = [
    {
        "abnormality": "ACL",
        "probability": 0.86,
        "status": "PENDING"
    }
]


print("\nTEST 1 — UNVALIDATED AI PREDICTION")

print("\nInput:")
print(unvalidated_findings)


llm_input = create_llm_input(
    study_id="KNEE-AI-L2-001",
    validated_findings=unvalidated_findings,
    clinical_context="Persistent knee pain."
)


print("\nLLM input produced:")
print(llm_input)


# ------------------------------------------------------------
# The LLM input MUST contain no findings
# ------------------------------------------------------------

if len(llm_input["approved_findings"]) == 0:

    print("\nPASS — No unvalidated finding was sent to the LLM.")

else:

    print("\nFAIL — Unvalidated finding reached the LLM.")
    raise SystemExit(1)


# ------------------------------------------------------------
# TEST 2 — Radiologist validates finding
# ------------------------------------------------------------

validated_findings = [
    {
        "abnormality": "ACL",
        "probability": 0.86,
        "status": "APPROVED"
    }
]


print("\n" + "-" * 60)
print("TEST 2 — RADIOLOGIST APPROVED FINDING")

print("\nInput:")
print(validated_findings)


llm_input = create_llm_input(
    study_id="KNEE-AI-L2-001",
    validated_findings=validated_findings,
    clinical_context="Persistent knee pain."
)


print("\nLLM input produced:")
print(llm_input)


# ------------------------------------------------------------
# Approved finding MUST reach LLM
# ------------------------------------------------------------

if len(llm_input["approved_findings"]) == 1:

    print("\nPASS — Approved finding was allowed to reach the LLM.")

else:

    print("\nFAIL — Approved finding was not sent to the LLM.")
    raise SystemExit(1)


# ------------------------------------------------------------
# Final result
# ------------------------------------------------------------

print("\n" + "=" * 60)
print("L2 HUMAN-IN-THE-LOOP TEST PASSED")
print("=" * 60)

print("\nVerified:")
print("AI prediction → Radiologist validation → LLM")
print("Unvalidated finding → BLOCKED from LLM input")
print("Approved finding → ALLOWED to LLM")
print("=" * 60)