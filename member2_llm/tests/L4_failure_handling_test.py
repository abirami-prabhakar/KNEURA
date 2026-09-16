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

from services.llm_service import generate_llm_report


# ============================================================
# KNEE-AI 3.3 — L4 LLM FAILURE HANDLING TEST
# ============================================================

print("\n" + "=" * 60)
print("KNEE-AI 3.3 — L4 LLM FAILURE HANDLING TEST")
print("=" * 60)


test_prompt = """
Generate a KNEE-AI 3.3 draft report.

Approved finding:
MCL abnormality confirmed.

Return valid JSON only.
"""


try:

    result = generate_llm_report(
        test_prompt
    )

    # If Gemini happens to be available, the intended
    # failure condition was not triggered.
    print("\nGemini responded successfully.")

    print("\nGenerated result:")
    print(result)

    print("\n⚠️ L4 FAILURE CONDITION WAS NOT TRIGGERED.")
    print("The LLM was available during this test.")

    print("\n" + "=" * 60)
    print("L4 FAILURE HANDLING TEST FAILED")
    print("=" * 60)

    raise SystemExit(1)


except Exception as error:

    error_text = str(error)

    print("\nLLM ERROR:")
    print(error_text)


    # --------------------------------------------------------
    # Verify graceful handling
    # --------------------------------------------------------

    if "503" in error_text or "429" in error_text:

        if "503" in error_text:
            print("\n503 UNAVAILABLE DETECTED.")

        elif "429" in error_text:
            print("\n429 QUOTA/UNAVAILABLE CONDITION DETECTED.")

        print("\nPASS — LLM failure was detected.")
        print("No fake report was generated.")
        print("The LLM exception was returned to the caller.")
        print("Manual workflow can continue safely.")

        print("\n" + "=" * 60)
        print("L4 FAILURE HANDLING TEST PASSED")
        print("=" * 60)

    else:

        print("\n❌ Unexpected error type.")
        print("Error was not a recognized Gemini unavailable condition.")

        print("\n" + "=" * 60)
        print("L4 FAILURE HANDLING TEST FAILED")
        print("=" * 60)

        raise SystemExit(1)