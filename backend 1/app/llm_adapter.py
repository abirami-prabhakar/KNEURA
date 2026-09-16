"""Backend adapter and integration boundary for Member 2's LLM pipeline.

Normalizes radiologist-validated findings and immutable Model 1 probabilities
into Member 2's canonical input contract, invokes Member 2's prompt and safety
validation pipeline, and serializes the structured DRAFT report for backend persistence.
"""

import json
import os
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable

BACKEND_DIR = Path(__file__).resolve().parent.parent
MEMBER2_DIR = Path(
    os.getenv("KNEE_AI_MEMBER2_PATH", str(BACKEND_DIR.parent / "member2_llm"))
).expanduser().resolve()

try:
    if not MEMBER2_DIR.is_dir():
        raise ModuleNotFoundError(f"Member 2 directory does not exist: {MEMBER2_DIR}")
    if str(MEMBER2_DIR) not in sys.path:
        sys.path.insert(0, str(MEMBER2_DIR))
    from schemas.api_contract import create_llm_input  # type: ignore
    from services.report_schema_validator import validate_report_schema  # type: ignore
    from services.safety_validator import validate_llm_report  # type: ignore
    from services.patient_safety_validator import validate_patient_explanation  # type: ignore
    MEMBER2_IMPORT_ERROR = None
except ImportError as exc:
    create_llm_input = None
    validate_report_schema = None
    validate_llm_report = None
    validate_patient_explanation = None
    MEMBER2_IMPORT_ERROR = exc


class LLMIntegrationError(RuntimeError):
    """A safe, actionable error caused by LLM failure, mapping error, or validation failure."""


def _require_member2_runtime() -> None:
    if MEMBER2_IMPORT_ERROR is not None:
        raise LLMIntegrationError(
            f"Member 2 generation unavailable: expected the original member2_llm "
            f"package at {MEMBER2_DIR}. Extract member2_llm beside backend 1 or "
            "set KNEE_AI_MEMBER2_PATH to its directory, then restart the backend. "
            f"Import error: {MEMBER2_IMPORT_ERROR}"
        ) from MEMBER2_IMPORT_ERROR


CANONICAL_ABNORMALITIES = [
    "ACL",
    "MCL",
    "Medial Meniscus",
    "Lateral Meniscus",
    "Medial OA",
    "Lateral OA",
    "PF OA",
    "Effusion",
    "Synovitis",
    "Baker's",
    "Contusion",
    "Fracture",
]


def canonical_abnormalities_in_text(finding_text: str) -> set[str]:
    """Use the existing canonical aliases for review and boundary validation."""
    if not isinstance(finding_text, str):
        raise LLMIntegrationError(f"Cannot map finding {finding_text!r} to a canonical Model 1 abnormality.")
    cleaned = finding_text.strip().lower().replace("’", "'")

    synonyms = [
        ("anterior cruciate", "ACL"),
        ("medial collateral", "MCL"),
        ("medial meniscus", "Medial Meniscus"),
        ("lateral meniscus", "Lateral Meniscus"),
        ("medial compartment osteoarthritis", "Medial OA"),
        ("medial osteoarthritis", "Medial OA"),
        ("medial oa", "Medial OA"),
        ("lateral compartment osteoarthritis", "Lateral OA"),
        ("lateral osteoarthritis", "Lateral OA"),
        ("lateral oa", "Lateral OA"),
        ("patellofemoral osteoarthritis", "PF OA"),
        ("pf osteoarthritis", "PF OA"),
        ("pf oa", "PF OA"),
        ("joint effusion", "Effusion"),
        ("effusion", "Effusion"),
        ("synovitis", "Synovitis"),
        ("baker's cyst", "Baker's"),
        ("baker cyst", "Baker's"),
        ("bakers", "Baker's"),
        ("baker's", "Baker's"),
        ("baker", "Baker's"),
        ("bone contusion", "Contusion"),
        ("contusion", "Contusion"),
        ("fracture", "Fracture"),
        ("acl", "ACL"),
        ("mcl", "MCL"),
    ]
    return {
        canonical for term, canonical in synonyms
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", cleaned)
    }


def match_canonical_abnormality(finding_text: str) -> str:
    """Matches finding text to one of the 12 canonical KNEE-AI abnormality names."""
    matches = canonical_abnormalities_in_text(finding_text)
    if len(matches) > 1:
        raise LLMIntegrationError(f"Ambiguous canonical abnormality: {finding_text!r}")
    if not matches:
        raise LLMIntegrationError(f"Cannot map finding {finding_text!r} to a canonical Model 1 abnormality.")
    return next(iter(matches))


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


# Reject identifiable input rather than silently changing clinician-authored text.
_DICOM_UID = re.compile(r"(?<![\w.])[012](?:\.\d+){2,}(?![\w.])")
_IDENTIFIER_FIELD = re.compile(
    r"patient[\s_-]*id|study[\s_-]*instance[\s_-]*uid|series[\s_-]*instance[\s_-]*uid",
    re.IGNORECASE,
)
_RAW_PATH = re.compile(r"[A-Za-z]:[\\/]|\\\\[^\s\\]+\\|(?<!\w)/(?:[^\s/]+/)+|\S+\.(?:dcm|dicom)\b", re.IGNORECASE)
_RAW_ARRAY = re.compile(r"\b(?:tensor|array)\s*\(", re.IGNORECASE)


def _validate_provider_text(value: str | None, sensitive_values: tuple[str | None, ...]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise LLMIntegrationError("Member 2 accepts clinical text only, not image or structured raw data.")
    if (
        _DICOM_UID.search(value)
        or _IDENTIFIER_FIELD.search(value)
        or _RAW_PATH.search(value)
        or _RAW_ARRAY.search(value)
        or any(secret and secret.casefold() in value.casefold() for secret in sensitive_values)
    ):
        raise LLMIntegrationError("Member 2 input contains an identifier or raw imaging path; supply de-identified clinical text.")


def _provider_study_id(study_id: str, application_study_id: int | None) -> str:
    if _DICOM_UID.search(study_id) or re.fullmatch(r"[012](?:\.\d+)+", study_id):
        if type(application_study_id) is not int or application_study_id < 1:
            raise LLMIntegrationError("A non-DICOM application study identifier is required for Member 2.")
        return f"study-{application_study_id}"
    return study_id


def map_backend_to_member2(
    study_id: str,
    validated_findings: list[Any],
    predictions: list[Any],
    clinical_context: str | None = None,
    *,
    application_study_id: int | None = None,
    sensitive_values: tuple[str | None, ...] = (),
) -> dict:
    """Maps backend validated findings to Member 2's canonical input contract.

    Enforces:
    - CONFIRMED -> APPROVED
    - EDITED -> APPROVED (matches canonical abnormality; fails if unmappable)
    - REJECTED -> REJECTED (retained in outer object for safety validation, filtered from LLM)
    - Provenance: lookup exact float probability from immutable Prediction rows.
    - Missing or duplicate canonical predictions fail without calling the provider.
    """
    provider_study_id = _provider_study_id(study_id, application_study_id)
    if provider_study_id != study_id:
        sensitive_values = (*sensitive_values, study_id)
    _validate_provider_text(provider_study_id, sensitive_values)
    _validate_provider_text(clinical_context, sensitive_values)
    pred_map: dict[str, float] = {}
    for p in predictions:
        label = _field(p, "label")
        conf = _field(p, "confidence")
        if label not in CANONICAL_ABNORMALITIES:
            continue
        if label in pred_map:
            raise LLMIntegrationError(f"Duplicate Model 1 prediction for '{label}'.")
        if not isinstance(conf, float) or not math.isfinite(conf) or not 0 <= conf <= 1:
            raise LLMIntegrationError(f"Invalid Model 1 confidence for '{label}'.")
        pred_map[label] = conf

    mapped_findings = []
    edited_context = []
    added_context = []
    for vf in validated_findings:
        outcome = _field(vf, "outcome")
        finding_text = _field(vf, "finding")
        is_added = bool(_field(vf, "is_radiologist_added"))

        if outcome in (None, "PENDING"):
            continue

        if outcome in ("CONFIRMED", "EDITED", "APPROVED"):
            status = "APPROVED"
        elif outcome == "REJECTED":
            status = "REJECTED"
        else:
            raise LLMIntegrationError(f"Invalid outcome '{outcome}' for finding '{finding_text}'.")

        if is_added:
            if canonical_abnormalities_in_text(finding_text) & pred_map.keys():
                raise LLMIntegrationError("A radiologist-added finding cannot duplicate a canonical AI prediction.")
            if status == "APPROVED":
                _validate_provider_text(finding_text, sensitive_values)
                _validate_provider_text(_field(vf, "details"), sensitive_values)
                added_context.append({
                    "finding": finding_text,
                    "details": _field(vf, "details"),
                    "source": "radiologist_added",
                })
            continue

        canonical = match_canonical_abnormality(finding_text)
        if canonical not in pred_map:
            raise LLMIntegrationError(
                f"No Model 1 prediction found for canonical abnormality '{canonical}' (finding '{finding_text}')."
            )

        probability = pred_map[canonical]
        if status == "APPROVED":
            _validate_provider_text(finding_text, sensitive_values)
            _validate_provider_text(_field(vf, "details"), sensitive_values)
        if outcome == "EDITED":
            edited_context.append({
                "canonical": canonical,
                "outcome": outcome,
                "finding": finding_text,
                "details": _field(vf, "details"),
            })

        mapped_findings.append({
            "abnormality": canonical,
            "probability": probability,
            "status": status,
        })

    authorized_context = clinical_context or ""
    if edited_context:
        authorized_context += "\nRadiologist-authored edits (authorized provenance):\n" + json.dumps(edited_context)
    if added_context:
        authorized_context += "\nRadiologist-added findings (authorized clinician input):\n" + json.dumps(added_context)
    rejected = {item["abnormality"] for item in mapped_findings if item["status"] == "REJECTED"}
    if canonical_abnormalities_in_text(authorized_context) & rejected:
        raise LLMIntegrationError("Clinical context references a rejected AI finding; resolve the conflicting context before generation.")
    return {
        "study_id": provider_study_id,
        "findings": mapped_findings,
        "clinical_context": authorized_context,
    }


class Member2ClinicalLLMAdapter:
    """Boundary adapter connecting backend review data to Member 2's pipeline."""

    def __init__(self, generate_llm_fn: Callable[[str], dict] | None = None):
        self._generate_llm_fn = generate_llm_fn

    def _call_llm_provider(self, prompt: str) -> dict:
        if self._generate_llm_fn is not None:
            return self._generate_llm_fn(prompt)

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise LLMIntegrationError("GEMINI_API_KEY is not configured")

        try:
            from services.llm_service import generate_llm_report
            return generate_llm_report(prompt)
        except (ImportError, ModuleNotFoundError) as exc:
            raise LLMIntegrationError(f"Member 2 LLM runtime dependencies unavailable: {exc}") from exc
        except Exception as exc:
            raise LLMIntegrationError(f"Member 2 LLM provider failure: {exc}") from exc

    def generate_report(
        self,
        study_id: str,
        validated_findings: list[Any],
        predictions: list[Any],
        clinical_context: str | None = None,
        *,
        application_study_id: int | None = None,
        sensitive_values: tuple[str | None, ...] = (),
    ) -> str:
        """Executes Member 2's pipeline and returns the serialized DRAFT report JSON."""
        _require_member2_runtime()
        # 1. Map to Member 2 canonical outer input object
        member2_outer = map_backend_to_member2(
            study_id=study_id,
            validated_findings=validated_findings,
            predictions=predictions,
            clinical_context=clinical_context,
            application_study_id=application_study_id,
            sensitive_values=sensitive_values,
        )

        # 2. Use Member 2's create_llm_input to filter approved findings
        llm_input = create_llm_input(
            study_id=member2_outer["study_id"],
            validated_findings=member2_outer["findings"],
            clinical_context=member2_outer["clinical_context"],
        )

        # 3. Load and format Member 2 production report prompt
        prompt_file = MEMBER2_DIR / "prompts" / "report_prompt.txt"
        if not prompt_file.is_file():
            raise LLMIntegrationError(f"Member 2 prompt file missing: {prompt_file}")
        try:
            prompt_template = prompt_file.read_text(encoding="utf-8")
            llm_prompt = prompt_template.format(
                study_id=llm_input["study_id"],
                validated_findings=llm_input["approved_findings"],
                clinical_context=llm_input["clinical_context"],
            )
        except (OSError, ValueError, KeyError) as exc:
            raise LLMIntegrationError(f"Member 2 prompt unavailable: {exc}") from exc

        # 4. Call LLM provider (live Gemini or injected test mock)
        try:
            llm_report = self._call_llm_provider(llm_prompt)
        except LLMIntegrationError:
            raise
        except Exception as exc:
            raise LLMIntegrationError(f"Member 2 LLM provider failure: {exc}") from exc

        if isinstance(llm_report, str):
            try:
                llm_report = json.loads(llm_report)
            except json.JSONDecodeError as exc:
                raise LLMIntegrationError("Member 2 LLM returned invalid JSON.") from exc

        if not isinstance(llm_report, dict):
            raise LLMIntegrationError("Member 2 LLM returned invalid report format.")

        # 5. Validate the ACTUAL LLM response schema
        schema_ok, schema_msg = validate_report_schema(llm_report, member2_outer["study_id"])
        if not schema_ok:
            raise LLMIntegrationError(f"Report schema validation failed: {schema_msg}")

        # 6. Validate the ACTUAL LLM response safety
        # Deny non-authorized canonical findings using Member 2's own validator.
        # These validation-only entries never enter the prompt and carry no scores.
        represented = {item["abnormality"] for item in member2_outer["findings"]}
        member2_outer["findings"].extend(
            {"abnormality": name, "status": "REJECTED"}
            for name in CANONICAL_ABNORMALITIES if name not in represented
        )
        safety_ok, safety_msg = validate_llm_report(llm_report, member2_outer)
        if not safety_ok:
            raise LLMIntegrationError(f"Member 2 safety validation failed: {safety_msg}")

        # 7. Construct and serialize structured DRAFT report into JSON string
        final_report = {
            "title": llm_report["title"],
            "study_id": study_id,
            "status": "DRAFT",
            "findings": llm_report["findings"],
            "impression": llm_report["impression"],
            "note": llm_report["note"],
            "final_approval": "PENDING",
        }
        return json.dumps(final_report, indent=2)

    def generate_patient_explanation(
        self,
        study_id: str,
        validated_findings: list[Any],
        predictions: list[Any],
        clinical_context: str | None = None,
        *,
        application_study_id: int | None = None,
        sensitive_values: tuple[str | None, ...] = (),
    ) -> dict:
        """Executes Member 2's patient explanation pipeline and returns the validated explanation dict."""
        _require_member2_runtime()
        # 1. Map to Member 2 canonical outer input object
        member2_outer = map_backend_to_member2(
            study_id=study_id,
            validated_findings=validated_findings,
            predictions=predictions,
            clinical_context=clinical_context,
            application_study_id=application_study_id,
            sensitive_values=sensitive_values,
        )

        # 2. Use Member 2's create_llm_input to filter approved findings
        llm_input = create_llm_input(
            study_id=member2_outer["study_id"],
            validated_findings=member2_outer["findings"],
            clinical_context=member2_outer["clinical_context"],
        )

        # 3. Load and format Member 2 patient prompt
        prompt_file = MEMBER2_DIR / "prompts" / "patient_prompt.txt"
        if not prompt_file.is_file():
            raise LLMIntegrationError(f"Member 2 patient prompt file missing: {prompt_file}")
        try:
            prompt_template = prompt_file.read_text(encoding="utf-8")
            llm_prompt = prompt_template.format(
                study_id=llm_input["study_id"],
                approved_findings=llm_input["approved_findings"],
                clinical_context=llm_input["clinical_context"],
            )
        except (OSError, ValueError, KeyError) as exc:
            raise LLMIntegrationError(f"Member 2 patient prompt unavailable: {exc}") from exc

        # 4. Call LLM provider (live Gemini or injected test mock)
        if self._generate_llm_fn is not None:
            llm_result = self._generate_llm_fn(llm_prompt)
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise LLMIntegrationError("GEMINI_API_KEY is not configured")
            try:
                from services.patient_explanation import generate_patient_explanation as m2_patient_explanation
                llm_result = m2_patient_explanation(llm_prompt)
            except (ImportError, ModuleNotFoundError) as exc:
                raise LLMIntegrationError(f"Member 2 patient explanation runtime dependencies unavailable: {exc}") from exc
            except Exception as exc:
                raise LLMIntegrationError(f"Member 2 patient explanation provider failure: {exc}") from exc

        if isinstance(llm_result, str):
            try:
                llm_result = json.loads(llm_result)
            except json.JSONDecodeError as exc:
                raise LLMIntegrationError("Member 2 patient explanation returned invalid JSON.") from exc

        if not isinstance(llm_result, dict):
            raise LLMIntegrationError("Member 2 patient explanation returned invalid format.")

        # 5. Populate rejected findings in member2_outer so validator catches any leaked rejected findings
        represented = {item["abnormality"] for item in member2_outer["findings"]}
        member2_outer["findings"].extend(
            {"abnormality": name, "status": "REJECTED"}
            for name in CANONICAL_ABNORMALITIES if name not in represented
        )

        # 6. Validate safety with Member 2's patient safety validator
        safety_ok, safety_msg = validate_patient_explanation(llm_result, member2_outer)
        if not safety_ok:
            raise LLMIntegrationError(f"Patient explanation safety validation failed: {safety_msg}")

        if "study_id" in llm_result:
            if llm_result["study_id"] != member2_outer["study_id"]:
                raise LLMIntegrationError("Patient explanation study ID mismatch.")
            llm_result = {**llm_result, "study_id": study_id}
        return llm_result


def get_llm_adapter() -> Member2ClinicalLLMAdapter:
    """FastAPI dependency for the clinical LLM adapter."""
    return Member2ClinicalLLMAdapter()
