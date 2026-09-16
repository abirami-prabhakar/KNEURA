# Member 2 integration verification

## Delivered

- Extracted `backend 1/` from `pytest_cache.zip` and `member2_llm/` from `mem2.zip` as siblings. Bundled virtual environments and caches were excluded.
- All 25 original Member 2 source, prompt, documentation, and test files match the archive byte-for-byte.
- The adapter normalizes the default or `KNEE_AI_MEMBER2_PATH` override with `expanduser().resolve()` and checks the directory before imports.
- Missing directories or import failures produce a controlled `LLMIntegrationError` with the expected location, override name, and restart instructions. Authenticated API calls return HTTP 503 without persisting generated output.
- Original generation functions, validators, prompts, model configuration, and retries remain unchanged. Backend production changes are limited to the adapter's import/path boundary. Authentication, radiologist review, patient release, and model inference code match the supplied archive.
- Updated the Member 2 test fixture to create a database user and use a signed bearer token, matching the application's existing authentication. No application authentication bypass was added.

## Results

**78 focused tests passed** on Python 3.12.14 with pytest 8.3.5 and google-genai 2.23.0.

From `backend 1/`, using the verification environment created at project-root `.venv/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:KNEE_AI_DATABASE_URL = 'sqlite:///:memory:'
..\.venv\Scripts\python.exe -m pytest tests/test_member2_runtime.py tests/test_member2_integration.py -q -p no:cacheprovider
```

Coverage includes sibling resolution from a different working directory; absolute, relative, and home-directory overrides; missing, non-directory, and incomplete packages; original report and patient generation functions with a mocked Gemini SDK client; response validation; rejected findings; treatment restrictions; controlled API errors; persistence; DRAFT/PENDING preservation; and the complete AI review gate.

The following four original offline scripts also completed successfully from `member2_llm/`:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
..\.venv\Scripts\python.exe tests/test_cases.py
..\.venv\Scripts\python.exe tests/full_pipeline_test.py
..\.venv\Scripts\python.exe tests/L2_human_in_loop_test.py
..\.venv\Scripts\python.exe tests/patient_explanation_test.py
```

## Limits and existing test issues

- No live Gemini request was made. The original service functions were exercised through a mocked SDK client; credentials, provider availability, quota, and the configured model's live availability remain unverified.
- The broader patient workflow, patient release, and radiologist review suites were attempted. Their legacy fixtures send `X-User-Role` headers and receive HTTP 401 from the existing bearer authentication. Those unrelated fixtures remain unchanged; the full backend suite is not verified green.
- Frozen model/golden-case checks require the separate canonical package/data referenced by those tests. Model inference was outside this Member 2 verification; PyTorch was not installed in the focused verification environment.
- Tests emitted existing Starlette/AnyIO and UTC datetime deprecation warnings.

## Live setup

Use the backend's existing Python 3.12 setup and install `backend 1/requirements.txt` for the full application. It already includes `google-genai`. Export `GEMINI_API_KEY` into the server process. Keep the sibling layout or set `KNEE_AI_MEMBER2_PATH` before startup, then restart after changes. `.env.example` is documentation and is not automatically loaded.

The accepted Member 2 model configuration and safety rules were preserved; generation still requires the application's existing clinician authentication and review workflow.
