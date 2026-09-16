from google import genai
from google.genai import types
import os
import json
import time

from services.config import GEMINI_MODEL


def generate_llm_report(prompt):

    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY")
    )

    for attempt in range(3):

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            return json.loads(response.text)

        except Exception as error:

            error_text = str(error)

            # Temporary Gemini server problem
            if "503" in error_text and attempt < 2:
                print(
                    f"Gemini temporarily unavailable. "
                    f"Retrying... ({attempt + 1}/2)"
                )
                time.sleep(5)

            # Gemini quota exceeded
            elif "429" in error_text:
                raise RuntimeError(
                    "Gemini API quota exceeded. "
                    "Please wait for the quota to reset or check "
                    "your Gemini API billing/quota."
                )

            else:
                raise error