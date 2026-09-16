import json
import io
import os
import csv
import zipfile
import base64
from functools import lru_cache
from datetime import datetime
from pathlib import Path

import pydicom
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai_adapter import AIIntegrationError, FrozenKneeAIAdapter
from app.authentication import create_access_token, verify_password
from app.database import Base, SessionLocal, engine
from app.models.study import Study
from app.models.prediction import Prediction
from app.models.radiologist_review import RadiologistReview, ValidatedFinding
from app.models.audit_log import AuditLog
from app.models.report import Report, ReportVersion
from app.models.orthopedic_review import OrthopedicReview
from app.models.user import User
from app.llm_adapter import (
    CANONICAL_ABNORMALITIES,
    LLMIntegrationError,
    Member2ClinicalLLMAdapter,
    get_llm_adapter,
    match_canonical_abnormality,
    canonical_abnormalities_in_text,
)
from app.schemas import (
    AnalyzeKneeMRIRequest,
    AnalyzeKneeMRIResponse,
    LoginRequest,
    LoginResponse,
    EditReportRequest,
    GenerateReportResponse,
    GradCAMRequest,
    GradCAMResponse,
    OrthopedicReviewResponse,
    OrthopedicStudyResponse,
    PatientExplanationResponse,
    PatientReleaseRequest,
    PatientReleaseResponse,
    PatientReportResponse,
    ReportResponse,
    ReportVersionResponse,
    StudyDetailResponse,
    StudyModeResponse,
    StudyReviewRequest,
    StudyReviewResponse,
    StudySummaryResponse,
    StudyUploadResponse,
    StudyWorkflowResponse,
    SubmitOrthopedicReviewRequest,
    ValidatedFindingResponse,
)
from app.security import (
    OrthopedicPrincipal,
    PatientPrincipal,
    ReleasePrincipal,
    ReviewPrincipal,
    require_orthopedic,
    require_patient,
    require_radiologist,
    require_release_authority,
    get_current_user,
)
from app.workflow import WorkflowState, can_transition, transition_workflow


Base.metadata.create_all(bind=engine)


def _ensure_study_columns() -> None:
    """Keep the original SQLite database usable after adding study locations."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(studies)"))
        }
        if "study_root" not in columns:
            connection.execute(text("ALTER TABLE studies ADD COLUMN study_root VARCHAR"))
        if "series_metadata_path" not in columns:
            connection.execute(
                text("ALTER TABLE studies ADD COLUMN series_metadata_path VARCHAR")
            )
        if "workflow_state" not in columns:
            connection.execute(
                text("ALTER TABLE studies ADD COLUMN workflow_state VARCHAR")
            )
        if "patient_id" not in columns:
            connection.execute(
                text("ALTER TABLE studies ADD COLUMN patient_id VARCHAR")
            )
        if "data_mode" not in columns:
            connection.execute(
                text("ALTER TABLE studies ADD COLUMN data_mode VARCHAR DEFAULT 'CLINICAL'")
            )

        rep_cols = {row[1] for row in connection.execute(text("PRAGMA table_info(reports)"))}
        if "current_version" not in rep_cols:
            connection.execute(text("ALTER TABLE reports ADD COLUMN current_version INTEGER DEFAULT 1"))
        if "approved_version" not in rep_cols:
            connection.execute(text("ALTER TABLE reports ADD COLUMN approved_version INTEGER"))
        if "patient_explanation" not in rep_cols:
            connection.execute(text("ALTER TABLE reports ADD COLUMN patient_explanation TEXT"))

        vf_cols = {row[1] for row in connection.execute(text("PRAGMA table_info(validated_findings)"))}
        if "is_radiologist_added" not in vf_cols:
            connection.execute(text("ALTER TABLE validated_findings ADD COLUMN is_radiologist_added BOOLEAN DEFAULT 0"))

        ortho_cols = {row[1] for row in connection.execute(text("PRAGMA table_info(orthopedic_reviews)"))}
        if "patient_information_approved" not in ortho_cols:
            connection.execute(text("ALTER TABLE orthopedic_reviews ADD COLUMN patient_information_approved BOOLEAN DEFAULT 1"))
        if "approved_followup_info" not in ortho_cols:
            connection.execute(text("ALTER TABLE orthopedic_reviews ADD COLUMN approved_followup_info TEXT"))


_ensure_study_columns()
Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="KNEE-AI 3.3 Backend",
    description="Backend API for the KNEE-AI system",
    version="3.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "KNEE_AI_FRONTEND_ORIGINS",
            "http://localhost,http://127.0.0.1,http://localhost:8000,http://127.0.0.1:8000,"
            "http://127.0.0.1:5500,http://localhost:5500",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return FileResponse(Path(__file__).resolve().parents[2] / "frontend" / "code.html")


@app.get("/health")
def health():
    return {
        "message": "KNEE-AI 3.3 Backend is running"
    }


@lru_cache(maxsize=20)
def _preview_slices(root: str, metadata: str, study_id: str):
    root_path = Path(root).expanduser().resolve()
    with Path(metadata).expanduser().resolve().open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row["StudyInstanceUID"] != study_id or float(row["Fluid_Sensitive"]) != 1 or float(row["Fat_Suppression"]) != 1:
            continue
        directory = (root_path / study_id / row["SeriesInstanceUID"]).resolve()
        if not directory.is_relative_to(root_path):
            continue
        files = list(directory.glob("*.dcm"))
        if files:
            return tuple(sorted(files, key=lambda f: int(pydicom.dcmread(f, stop_before_pixels=True).InstanceNumber)))
    raise HTTPException(status_code=404, detail="No eligible DICOM series is available for preview.")


@app.get("/studies/{study_id}/mri-preview")
def mri_preview(study_id: str, slice_index: int = 0,
                current_user: User = Depends(get_current_user)):
    if current_user.role not in ("RADIOLOGIST", "ORTHOPEDIC", "ORTHOPEDIC_SURGEON"):
        raise HTTPException(status_code=403, detail="Clinical role required.")
    with SessionLocal() as db:
        study = db.query(Study).filter_by(study_id=study_id).first()
        if study is None:
            raise HTTPException(status_code=404, detail="Study not found.")
        if current_user.role != "RADIOLOGIST" and study.workflow_state not in ("RADIOLOGIST_APPROVED", "ORTHOPEDIC_REVIEW", "PATIENT_RELEASED"):
            raise HTTPException(status_code=403, detail="Approved study required.")
        if not study.study_root or not study.series_metadata_path:
            raise HTTPException(status_code=404, detail="Study imaging paths are unavailable.")
        files = _preview_slices(study.study_root, study.series_metadata_path, study_id)
        if not 0 <= slice_index < len(files):
            raise HTTPException(status_code=422, detail="Slice index is out of range.")
        try:
            import numpy as np
            from PIL import Image
            from pydicom.pixels import apply_voi_lut, apply_modality_lut
            ds = pydicom.dcmread(files[slice_index])
            pixels = np.asarray(apply_voi_lut(apply_modality_lut(ds.pixel_array, ds), ds), dtype=float)
            pixels = (pixels - pixels.min()) / max(float(np.ptp(pixels)), 1) * 255
            if ds.PhotometricInterpretation == "MONOCHROME1":
                pixels = 255 - pixels
            image = Image.fromarray(pixels.astype("uint8"))
            output = io.BytesIO()
            image.save(output, format="PNG")
        except Exception as exc:
            raise HTTPException(status_code=422, detail="DICOM preview could not be decoded.") from exc
        return {"image": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode(),
                "slice_index": slice_index, "slice_count": len(files), "instance_number": int(ds.InstanceNumber)}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.email == request.email).one_or_none()
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    db.add(AuditLog(action="LOGIN", actor_id=str(user.id), study_id="", details="Authenticated session; no study selected"))
    db.commit()
    return LoginResponse(
        access_token=create_access_token(user.id, user.role),
        user_id=user.id,
        email=user.email,
        role=user.role,
    )


def _upload_flag(text_value: str, keywords: tuple[str, ...]) -> int:
    normalized = text_value.casefold().replace("-", " ").replace("_", " ")
    return int(any(keyword in normalized for keyword in keywords))


@app.post("/studies/upload", response_model=StudyUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_study(
    files: list[UploadFile] = File(..., min_length=1),
    principal: ReviewPrincipal = Depends(require_radiologist),
    db: Session = Depends(get_db),
) -> StudyUploadResponse:
    """Ingest real DICOM files into the existing frozen inference layout."""
    configured_root = os.getenv("KNEE_AI_STUDY_ROOT")
    if not configured_root:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MRI upload unavailable: KNEE_AI_STUDY_ROOT is not configured.",
        )
    upload_root = Path(configured_root).expanduser()
    upload_root.mkdir(parents=True, exist_ok=True)

    study_id: str | None = None
    records: dict[str, dict[str, object]] = {}
    staged_files: list[tuple[Path, bytes]] = []
    try:
        for upload in files:
            if not upload.filename:
                continue
            upload.file.seek(0)
            is_zip = upload.filename.casefold().endswith(".zip")
            if is_zip:
                try:
                    archive = zipfile.ZipFile(upload.file)
                    sources = ((member.filename, archive.read(member)) for member in archive.infolist() if not member.is_dir())
                except zipfile.BadZipFile as exc:
                    raise HTTPException(status_code=422, detail=f"Invalid DICOM ZIP: {upload.filename}") from exc
            else:
                sources = ((upload.filename, upload.file.read()),)

            valid_in_upload = 0
            for source_name, file_bytes in sources:
                try:
                    dataset = pydicom.dcmread(io.BytesIO(file_bytes), stop_before_pixels=True, force=False)
                except Exception as exc:
                    if is_zip:
                        continue
                    raise HTTPException(status_code=422, detail=f"Invalid DICOM file: {source_name}") from exc
                file_study_id = str(getattr(dataset, "StudyInstanceUID", "")).strip()
                series_id = str(getattr(dataset, "SeriesInstanceUID", "")).strip()
                sop_id = str(getattr(dataset, "SOPInstanceUID", "")).strip()
                if not file_study_id or not series_id or not sop_id:
                    if is_zip:
                        continue
                    raise HTTPException(status_code=422, detail=f"DICOM file {source_name} is missing required UIDs.")
                if study_id is None:
                    study_id = file_study_id
                if file_study_id != study_id:
                    raise HTTPException(status_code=422, detail="All uploaded files must belong to one StudyInstanceUID.")

                description = " ".join(
                    str(getattr(dataset, field, ""))
                    for field in ("SeriesDescription", "ProtocolName", "SequenceName")
                ).strip()
                records.setdefault(
                    series_id,
                    {
                        "StudyInstanceUID": study_id,
                        "SeriesInstanceUID": series_id,
                        "Fluid_Sensitive": _upload_flag(description, ("t2", "pd", "dp", "stir", "cube", "fluid")),
                        "Fat_Suppression": _upload_flag(description, ("fs", "fat sat", "fat saturation", "spair", "spir", "stir", "fatsat")),
                        "SeriesDescription": description,
                        "Anatomical_Plane": str(getattr(dataset, "ScanningSequence", "")),
                    },
                )
                staged_files.append((upload_root / study_id / series_id / f"{sop_id}.dcm", file_bytes))
                valid_in_upload += 1
            if is_zip and valid_in_upload == 0:
                raise HTTPException(status_code=422, detail=f"No valid DICOM files found in {upload.filename}.")

        if not study_id or not staged_files:
            raise HTTPException(status_code=422, detail="At least one valid DICOM file is required.")

        study_directory = upload_root / study_id
        study_directory.mkdir(parents=True, exist_ok=True)
        for destination, file_bytes in staged_files:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as output:
                output.write(file_bytes)

        metadata_path = study_directory / "series_metadata.csv"
        with metadata_path.open("w", newline="", encoding="utf-8") as manifest:
            writer = csv.DictWriter(manifest, fieldnames=[
                "StudyInstanceUID", "SeriesInstanceUID", "Fluid_Sensitive",
                "Fat_Suppression", "SeriesDescription", "Anatomical_Plane",
            ])
            writer.writeheader()
            writer.writerows(records.values())

        study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
        if study is None:
            study = Study(study_id=study_id, data_mode="CLINICAL")
            db.add(study)
        study.study_root = str(upload_root)
        study.series_metadata_path = str(metadata_path)
        db.commit()
        return StudyUploadResponse(
            study_id=study_id,
            file_count=len(staged_files),
            series_count=len(records),
            study_root=str(upload_root),
            series_metadata_path=str(metadata_path),
            message="DICOM study uploaded and registered for KNEE-AI analysis.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="DICOM upload could not be registered.") from exc


@app.post(
    "/api/v1/ai/analyze",
    response_model=AnalyzeKneeMRIResponse,
    status_code=status.HTTP_200_OK,
)
def analyze_knee_mri(
    request: AnalyzeKneeMRIRequest,
    db: Session = Depends(get_db),
    current_user: ReviewPrincipal = Depends(require_radiologist),
) -> AnalyzeKneeMRIResponse:
    study = db.query(Study).filter(Study.study_id == request.study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=404, detail="Study was not found.")

    if study.workflow_state is not None and not can_transition(study.workflow_state, WorkflowState.AI_COMPLETE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal workflow transition from {study.workflow_state} to {WorkflowState.AI_COMPLETE.value}.",
        )

    try:
        result = FrozenKneeAIAdapter().analyze(study)
    except AIIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        # Do not leak paths, model details, or a traceback to API clients.
        raise HTTPException(status_code=500, detail="KNEE-AI inference failed.")

    probabilities = result["probabilities"]
    # One row per output preserves the frozen labels and their full float values.
    db.query(Prediction).filter(Prediction.study_id == study.study_id).delete()
    db.add_all(
        [
            Prediction(study_id=study.study_id, label=label, confidence=probability)
            for label, probability in probabilities.items()
        ]
    )
    transition_workflow(
        db=db,
        study=study,
        next_state=WorkflowState.AI_COMPLETE,
        actor_id="system",
    )
    db.commit()

    return AnalyzeKneeMRIResponse(
        study_id=study.study_id,
        action=request.action,
        status="completed",
        model_version=result["model"]["name"],
        architecture=result["model"]["architecture"],
        series_evaluated=result["study"]["series_evaluated"],
        windows_evaluated=result["study"]["windows_evaluated"],
        probabilities=probabilities,
        requires_radiologist_review=True,
        data_mode=study.data_mode or "CLINICAL",
    )


@app.post(
    "/api/v1/ai/gradcam",
    response_model=GradCAMResponse,
    status_code=status.HTTP_200_OK,
)
def generate_gradcam_explanation(
    request: GradCAMRequest,
    principal: ReviewPrincipal = Depends(require_radiologist),
    db: Session = Depends(get_db),
) -> GradCAMResponse:
    study = db.query(Study).filter(Study.study_id == request.study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=404, detail="Study was not found.")

    if request.abnormality not in CANONICAL_ABNORMALITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Abnormality '{request.abnormality}' is not one of the 12 canonical abnormalities.",
        )

    try:
        result = FrozenKneeAIAdapter().generate_gradcam(
            study=study,
            abnormality=request.abnormality,
            series_instance_uid=request.series_instance_uid,
            window_index=request.window_index,
        )
    except AIIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="KNEE-AI Grad-CAM generation failed.") from exc

    db.add(
        AuditLog(
            action="GRADCAM_GENERATED",
            actor_id=principal.user_id,
            study_id=study.study_id,
            details=f"abnormality={request.abnormality}; window_index={result.get('window_index')}",
        )
    )
    db.commit()

    return GradCAMResponse(
        model_version=result["model_version"],
        abnormality=result["abnormality"],
        class_index=result["class_index"],
        probability=result["probability"],
        plane=result.get("plane"),
        series_instance_uid=result.get("series_instance_uid"),
        window_index=result.get("window_index"),
        instance_numbers=result["instance_numbers"],
        heatmap=result["heatmap"],
    )


@app.post("/studies/{study_id}/review", response_model=StudyReviewResponse, status_code=status.HTTP_201_CREATED)
def submit_study_review(
    study_id: str,
    request: StudyReviewRequest,
    principal: ReviewPrincipal = Depends(require_radiologist),
    db: Session = Depends(get_db),
) -> StudyReviewResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")

    # Retrieve, but do not alter, the original frozen AI output.  The review
    # below records only clinician-authored findings in separate tables.
    ai_predictions = (
        db.query(Prediction)
        .filter(Prediction.study_id == study.study_id)
        .order_by(Prediction.id)
        .all()
    )
    if not ai_predictions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No AI result exists for this study.")

    if request.decision != "MIXED":
        if any(
            finding.outcome != request.decision
            and not (request.decision == "CONFIRMED" and finding.outcome == "APPROVED")
            for finding in request.validated_findings
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Each validated finding outcome must match the review decision.",
            )
    else:
        outcomes = {
            "CONFIRMED" if finding.outcome == "APPROVED" else finding.outcome
            for finding in request.validated_findings
        }
        if len(outcomes) < 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A MIXED review decision must contain more than one distinct outcome.",
            )

    seen_canonicals = set()
    for f in request.validated_findings:
        if f.is_radiologist_added and canonical_abnormalities_in_text(f.finding) & {
            prediction.label for prediction in ai_predictions
        }:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A radiologist-added finding cannot duplicate a canonical AI finding; review or edit that AI finding instead.",
            )
        if not f.is_radiologist_added:
            try:
                can = match_canonical_abnormality(f.finding)
                if can in seen_canonicals:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=f"Duplicate decision for AI finding '{can}'.",
                    )
                seen_canonicals.add(can)
            except LLMIntegrationError:
                pass

    review = RadiologistReview(
        study_id=study.study_id,
        reviewer_id=principal.user_id,
        decision=request.decision,
        notes=request.notes,
    )
    db.add(review)
    db.flush()
    findings = [
        ValidatedFinding(
            review_id=review.id,
            finding=finding.finding,
            outcome=finding.outcome,
            details=finding.details,
            is_radiologist_added=finding.is_radiologist_added,
        )
        for finding in request.validated_findings
    ]
    db.add_all(findings)
    if not can_transition(study.workflow_state, WorkflowState.RADIOLOGIST_REVIEW):
        current_display = study.workflow_state or "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal workflow transition from {current_display} to {WorkflowState.RADIOLOGIST_REVIEW.value}.",
        )

    db.add(
        AuditLog(
            action="RADIOLOGIST_REVIEW_SUBMITTED",
            actor_id=principal.user_id,
            study_id=study.study_id,
            details=f"decision={request.decision}; findings={len(findings)}",
        )
    )
    transition_workflow(
        db=db,
        study=study,
        next_state=WorkflowState.RADIOLOGIST_REVIEW,
        actor_id=principal.user_id,
    )
    db.commit()
    db.refresh(review)

    return StudyReviewResponse(
        review_id=review.id,
        study_id=review.study_id,
        reviewer_id=review.reviewer_id,
        decision=review.decision,
        notes=review.notes,
        created_at=review.created_at,
        validated_findings=[
            ValidatedFindingResponse(
                finding=row.finding,
                outcome=row.outcome,
                details=row.details,
            )
            for row in review.validated_findings
        ],
    )


@app.post(
    "/studies/{study_id}/generate-report",
    response_model=GenerateReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_draft_report(
    study_id: str,
    principal: ReviewPrincipal = Depends(require_radiologist),
    llm_adapter: Member2ClinicalLLMAdapter = Depends(get_llm_adapter),
    db: Session = Depends(get_db),
) -> GenerateReportResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")

    review = (
        db.query(RadiologistReview)
        .filter(RadiologistReview.study_id == study.study_id)
        .order_by(RadiologistReview.id.desc())
        .first()
    )
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No radiologist review exists for this study.",
        )

    if not can_transition(study.workflow_state, WorkflowState.REPORT_DRAFT):
        current_display = study.workflow_state or "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal workflow transition from {current_display} to {WorkflowState.REPORT_DRAFT.value}.",
        )

    validated_findings = (
        db.query(ValidatedFinding)
        .filter(ValidatedFinding.review_id == review.id)
        .order_by(ValidatedFinding.id)
        .all()
    )
    if not validated_findings:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No validated findings exist for this study.",
        )

    predictions = (
        db.query(Prediction)
        .filter(Prediction.study_id == study.study_id)
        .order_by(Prediction.id)
        .all()
    )

    # Completeness depends on the AI predictions, never the overall review decision.
    if set(CANONICAL_ABNORMALITIES).issubset({p.label for p in predictions}):
        reviewed_ai_findings = set()
        for vf in validated_findings:
            if not getattr(vf, "is_radiologist_added", False):
                if vf.outcome not in ("CONFIRMED", "APPROVED", "EDITED", "REJECTED"):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Every AI finding must have an explicit radiologist decision.",
                    )
                try:
                    can = match_canonical_abnormality(vf.finding)
                    if can in reviewed_ai_findings:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=f"Duplicate decision for AI finding '{can}'.",
                        )
                    reviewed_ai_findings.add(can)
                except LLMIntegrationError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Every AI decision must identify one canonical abnormality.",
                    ) from exc
        missing = set(CANONICAL_ABNORMALITIES) - reviewed_ai_findings
        if missing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"All 12 AI findings must receive an explicit radiologist decision before generating a report. Missing decisions for: {sorted(missing)}",
            )

    try:
        draft_content = llm_adapter.generate_report(
            study_id=study.study_id,
            validated_findings=validated_findings,
            predictions=predictions,
            clinical_context=review.notes,
            application_study_id=study.id,
            sensitive_values=(study.patient_id, study.study_root, study.series_metadata_path),
        )
    except LLMIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Clinical report generation failed: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clinical report generation encountered an unexpected error.",
        ) from exc

    report = Report(
        study_id=study.study_id,
        author_id=principal.user_id,
        status="DRAFT",
        draft_content=draft_content,
        current_version=1,
    )
    db.add(report)
    db.flush()

    v1 = ReportVersion(
        report_id=report.id,
        version_number=1,
        content=draft_content,
        author_id=principal.user_id,
        status="DRAFT",
    )
    db.add(v1)

    db.add(
        AuditLog(
            action="DRAFT_REPORT_GENERATED",
            actor_id=principal.user_id,
            study_id=study.study_id,
            details=f"report_id={report.id}; status=DRAFT",
        )
    )
    transition_workflow(
        db=db,
        study=study,
        next_state=WorkflowState.REPORT_DRAFT,
        actor_id=principal.user_id,
    )
    db.commit()
    db.refresh(report)

    return GenerateReportResponse(
        report_id=report.id,
        study_id=report.study_id,
        status="DRAFT",
        draft_content=report.draft_content,
        current_version=report.current_version,
        created_at=report.created_at,
    )


@app.put("/reports/{report_id}", response_model=ReportResponse)
def edit_report(
    report_id: int,
    request: EditReportRequest,
    principal: ReviewPrincipal = Depends(require_radiologist),
    db: Session = Depends(get_db),
) -> ReportResponse:
    report = db.query(Report).filter(Report.id == report_id).one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report was not found.")

    study = db.query(Study).filter(Study.study_id == report.study_id).one_or_none()
    if study is None or study.workflow_state != WorkflowState.REPORT_DRAFT.value:
        current_display = study.workflow_state if study and study.workflow_state else "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report cannot be edited in workflow state {current_display}.",
        )

    if report.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only DRAFT reports can be edited.")

    # Ensure version 1 exists in report_versions if created externally in test fixtures
    existing_v1 = (
        db.query(ReportVersion)
        .filter(ReportVersion.report_id == report.id, ReportVersion.version_number == 1)
        .one_or_none()
    )
    if existing_v1 is None:
        db.add(
            ReportVersion(
                report_id=report.id,
                version_number=1,
                content=report.draft_content,
                author_id=report.author_id,
                status="DRAFT",
            )
        )
        db.flush()

    try:
        content = json.loads(request.draft_content)
    except (ValueError, TypeError):
        content = None
    if isinstance(content, dict):
        content["status"] = "DRAFT"
        content["final_approval"] = "PENDING"
        request.draft_content = json.dumps(content, indent=2)
    report.patient_explanation = None
    new_version_num = (report.current_version or 1) + 1
    report.current_version = new_version_num
    report.draft_content = request.draft_content

    db.add(
        ReportVersion(
            report_id=report.id,
            version_number=new_version_num,
            content=request.draft_content,
            author_id=principal.user_id,
            status="DRAFT",
        )
    )

    db.add(AuditLog(
        action="REPORT_EDITED", actor_id=principal.user_id,
        study_id=report.study_id, details=f"report_id={report_id}",
    ))
    db.commit()
    db.refresh(report)
    return ReportResponse(
        report_id=report.id,
        study_id=report.study_id,
        status=report.status,
        draft_content=report.draft_content,
        current_version=report.current_version,
        approved_version=report.approved_version,
        created_at=report.created_at,
    )


@app.post("/reports/{report_id}/approve", response_model=ReportResponse)
def approve_report(
    report_id: int,
    principal: ReviewPrincipal = Depends(require_radiologist),
    db: Session = Depends(get_db),
) -> ReportResponse:
    report = db.query(Report).filter(Report.id == report_id).one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report was not found.")

    study = db.query(Study).filter(Study.study_id == report.study_id).one_or_none()
    if study is None or not can_transition(study.workflow_state, WorkflowState.RADIOLOGIST_APPROVED):
        current_display = study.workflow_state if study and study.workflow_state else "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal workflow transition from {current_display} to {WorkflowState.RADIOLOGIST_APPROVED.value}.",
        )

    if report.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Only DRAFT reports can be approved.")

    review = db.query(RadiologistReview).filter_by(study_id=study.study_id).order_by(RadiologistReview.id.desc()).first()
    decisions = db.query(ValidatedFinding).filter_by(review_id=review.id).all() if review else []
    reviewed = {v.finding for v in decisions if not v.is_radiologist_added and v.outcome in ("CONFIRMED", "EDITED", "REJECTED", "APPROVED")}
    if not set(CANONICAL_ABNORMALITIES).issubset(reviewed):
        raise HTTPException(status_code=409, detail="Complete all 12 finding decisions before approval.")

    try:
        report.status = "APPROVED"
        try:
            signed = json.loads(report.draft_content)
        except (ValueError, TypeError):
            signed = None
        if isinstance(signed, dict):
            signed["status"] = "APPROVED"
            signed["final_approval"] = "APPROVED"
            report.draft_content = json.dumps(signed, indent=2)
        report.approved_version = report.current_version or 1

        # Mark current version row as APPROVED
        current_v = (
            db.query(ReportVersion)
            .filter(ReportVersion.report_id == report.id, ReportVersion.version_number == report.approved_version)
            .one_or_none()
        )
        if current_v is not None:
            current_v.status = "APPROVED"
            current_v.content = report.draft_content

        db.add(AuditLog(
            action="REPORT_APPROVED", actor_id=principal.user_id,
            study_id=report.study_id, details=f"report_id={report_id}",
        ))
        transition_workflow(
            db=db,
            study=study,
            next_state=WorkflowState.RADIOLOGIST_APPROVED,
            actor_id=principal.user_id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(report)
    return ReportResponse(
        report_id=report.id,
        study_id=report.study_id,
        status=report.status,
        draft_content=report.draft_content,
        current_version=report.current_version,
        approved_version=report.approved_version,
        created_at=report.created_at,
    )


@app.get(
    "/reports/{report_id}/versions",
    response_model=list[ReportVersionResponse],
    status_code=status.HTTP_200_OK,
)
def get_report_versions(
    report_id: int,
    principal: ReviewPrincipal = Depends(require_radiologist),
    db: Session = Depends(get_db),
) -> list[ReportVersionResponse]:
    report = db.query(Report).filter(Report.id == report_id).one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report was not found.")

    versions = (
        db.query(ReportVersion)
        .filter(ReportVersion.report_id == report_id)
        .order_by(ReportVersion.version_number.asc())
        .all()
    )
    return [
        ReportVersionResponse(
            id=v.id,
            report_id=v.report_id,
            version_number=v.version_number,
            content=v.content,
            author_id=v.author_id,
            status=v.status,
            created_at=v.created_at,
        )
        for v in versions
    ]


@app.get(
    "/studies",
    response_model=list[StudySummaryResponse],
    status_code=status.HTTP_200_OK,
)
def list_studies(
    db: Session = Depends(get_db),
    current_user: ReviewPrincipal = Depends(require_radiologist),
) -> list[StudySummaryResponse]:
    studies = db.query(Study).order_by(Study.id).all()
    results = []
    for study in studies:
        report = (
            db.query(Report)
            .filter(Report.study_id == study.study_id)
            .order_by(Report.id.desc())
            .first()
        )
        predictions = (
            db.query(Prediction)
            .filter(Prediction.study_id == study.study_id)
            .order_by(Prediction.id)
            .all()
        )
        results.append(
            StudySummaryResponse(
                study_id=study.study_id,
                workflow_state=study.workflow_state,
                patient_id=study.patient_id,
                data_mode=study.data_mode or "CLINICAL",
                ai_available=bool(predictions),
                report_available=report is not None,
                report_status=report.status if report else None,
            )
        )
    return results


@app.get(
    "/studies/{study_id}",
    response_model=StudyDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_study_detail(
    study_id: str,
    db: Session = Depends(get_db),
    current_user: ReviewPrincipal = Depends(require_radiologist),
) -> StudyDetailResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")

    predictions = (
        db.query(Prediction)
        .filter(Prediction.study_id == study.study_id)
        .order_by(Prediction.id)
        .all()
    )
    ai_probabilities = {prediction.label: prediction.confidence for prediction in predictions}

    latest_review = (
        db.query(RadiologistReview)
        .filter(RadiologistReview.study_id == study.study_id)
        .order_by(RadiologistReview.id.desc())
        .first()
    )
    validated_findings = None
    if latest_review is not None:
        findings = (
            db.query(ValidatedFinding)
            .filter(ValidatedFinding.review_id == latest_review.id)
            .order_by(ValidatedFinding.id)
            .all()
        )
        validated_findings = [
            {
                "finding": finding.finding,
                "outcome": finding.outcome,
                "details": finding.details,
                "is_radiologist_added": bool(finding.is_radiologist_added),
            }
            for finding in findings
        ]

    latest_report = (
        db.query(Report)
        .filter(Report.study_id == study.study_id)
        .order_by(Report.id.desc())
        .first()
    )
    report = None
    if latest_report is not None:
        report = {
            "report_id": latest_report.id,
            "study_id": latest_report.study_id,
            "status": latest_report.status,
            "draft_content": latest_report.draft_content,
            "patient_explanation": latest_report.patient_explanation,
            "current_version": latest_report.current_version,
            "approved_version": latest_report.approved_version,
            "created_at": latest_report.created_at,
        }

    latest_ortho_review = (
        db.query(OrthopedicReview)
        .filter(OrthopedicReview.study_id == study.study_id)
        .order_by(OrthopedicReview.id.desc())
        .first()
    )
    orthopedic_review = None
    if latest_ortho_review is not None:
        orthopedic_review = {
            "id": latest_ortho_review.id,
            "study_id": latest_ortho_review.study_id,
            "reviewer_id": latest_ortho_review.reviewer_id,
            "assessment": latest_ortho_review.assessment,
            "recommendation": latest_ortho_review.recommendation,
            "notes": latest_ortho_review.notes,
            "patient_information_approved": latest_ortho_review.patient_information_approved,
            "approved_followup_info": latest_ortho_review.approved_followup_info,
            "created_at": latest_ortho_review.created_at,
            "workflow_state": study.workflow_state,
        }

    released_audit = (
        db.query(AuditLog)
        .filter(AuditLog.study_id == study.study_id, AuditLog.action == "PATIENT_RELEASED")
        .order_by(AuditLog.id.desc())
        .first()
    )

    db.add(AuditLog(action="STUDY_VIEWED", actor_id=current_user.user_id, study_id=study_id, details="Radiologist study view"))
    db.commit()
    return StudyDetailResponse(
        study_id=study.study_id,
        workflow_state=study.workflow_state,
        patient_id=study.patient_id,
        data_mode=study.data_mode or "CLINICAL",
        study_root=study.study_root,
        series_metadata_path=study.series_metadata_path,
        ai_probabilities=ai_probabilities or None,
        validated_findings=validated_findings,
        report=report,
        orthopedic_review=orthopedic_review,
        released_at=released_audit.created_at if released_audit else None,
    )


@app.get(
    "/studies/{study_id}/workflow",
    response_model=StudyWorkflowResponse,
    status_code=status.HTTP_200_OK,
)
def get_study_workflow(
    study_id: str,
    db: Session = Depends(get_db),
    current_user: ReviewPrincipal = Depends(require_radiologist),
) -> StudyWorkflowResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")
    return StudyWorkflowResponse(
        study_id=study.study_id,
        state=study.workflow_state,
    )


@app.get(
    "/studies/{study_id}/mode",
    response_model=StudyModeResponse,
    status_code=status.HTTP_200_OK,
)
def get_study_mode(
    study_id: str,
    db: Session = Depends(get_db),
    current_user: ReviewPrincipal = Depends(require_radiologist),
) -> StudyModeResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")
    return StudyModeResponse(
        study_id=study.study_id,
        data_mode=study.data_mode or "CLINICAL",
    )


@app.post(
    "/studies/{study_id}/patient-explanation",
    response_model=PatientExplanationResponse,
    status_code=status.HTTP_200_OK,
)
def generate_patient_explanation_endpoint(
    study_id: str,
    principal: ReviewPrincipal = Depends(require_radiologist),
    llm_adapter: Member2ClinicalLLMAdapter = Depends(get_llm_adapter),
    db: Session = Depends(get_db),
) -> PatientExplanationResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=404, detail="Study was not found.")

    report = (
        db.query(Report)
        .filter(Report.study_id == study.study_id)
        .order_by(Report.id.desc())
        .first()
    )
    if report is None:
        raise HTTPException(status_code=409, detail="No report exists for this study.")

    if report.status != "APPROVED" or study.workflow_state != WorkflowState.RADIOLOGIST_APPROVED.value:
        raise HTTPException(status_code=409, detail="Generate an explanation from a signed report before orthopedic review.")
    try:
        signed = json.loads(report.draft_content)
        authorized_text = "\n".join(signed["findings"]) + "\n" + signed["impression"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=409, detail="Patient explanation requires structured signed findings and impression.")

    review = (
        db.query(RadiologistReview)
        .filter(RadiologistReview.study_id == study.study_id)
        .order_by(RadiologistReview.id.desc())
        .first()
    )
    if review is None:
        raise HTTPException(status_code=409, detail="No radiologist review exists for this study.")

    validated_findings = (
        db.query(ValidatedFinding)
        .filter(ValidatedFinding.review_id == review.id)
        .order_by(ValidatedFinding.id)
        .all()
    )
    predictions = (
        db.query(Prediction)
        .filter(Prediction.study_id == study.study_id)
        .order_by(Prediction.id)
        .all()
    )

    try:
        explanation = llm_adapter.generate_patient_explanation(
            study_id=study.study_id,
            validated_findings=[{"finding": name, "outcome": "CONFIRMED", "details": None}
                                for name in canonical_abnormalities_in_text(authorized_text)],
            predictions=predictions,
            clinical_context=authorized_text,
            application_study_id=study.id,
            sensitive_values=(study.patient_id, study.study_root, study.series_metadata_path),
        )
    except LLMIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Patient explanation generation failed: {exc}",
        ) from exc
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Patient explanation generation encountered an unexpected error.",
        )

    explanation_str = json.dumps(explanation) if isinstance(explanation, dict) else str(explanation)
    report.patient_explanation = explanation_str
    db.add(
        AuditLog(
            action="PATIENT_EXPLANATION_GENERATED",
            actor_id=principal.user_id,
            study_id=study.study_id,
            details=f"report_id={report.id}",
        )
    )
    db.commit()

    return PatientExplanationResponse(
        study_id=study.study_id,
        patient_explanation=explanation,
        created_at=datetime.utcnow(),
    )


@app.get(
    "/orthopedic/studies",
    response_model=list[OrthopedicStudyResponse],
    status_code=status.HTTP_200_OK,
)
def list_orthopedic_studies(
    principal: OrthopedicPrincipal = Depends(require_orthopedic),
    db: Session = Depends(get_db),
) -> list[OrthopedicStudyResponse]:
    studies = (
        db.query(Study)
        .filter(Study.workflow_state.in_([WorkflowState.RADIOLOGIST_APPROVED.value, WorkflowState.ORTHOPEDIC_REVIEW.value, WorkflowState.PATIENT_RELEASED.value]))
        .order_by(Study.id)
        .all()
    )
    results = []
    for study in studies:
        report = (
            db.query(Report)
            .filter(Report.study_id == study.study_id, Report.status == "APPROVED")
            .order_by(Report.id.desc())
            .first()
        )
        if report is not None:
            results.append(
                OrthopedicStudyResponse(
                    study_id=study.study_id,
                    workflow_state=study.workflow_state,
                    approved_report=report.draft_content,
                    approved_radiology_report=report.draft_content,
                    clinical_context=None,
                )
            )
    return results


@app.get(
    "/orthopedic/studies/{study_id}",
    response_model=OrthopedicStudyResponse,
    status_code=status.HTTP_200_OK,
)
def get_orthopedic_study(
    study_id: str,
    principal: OrthopedicPrincipal = Depends(require_orthopedic),
    db: Session = Depends(get_db),
) -> OrthopedicStudyResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")

    if study.workflow_state in (
        WorkflowState.AI_COMPLETE.value,
        WorkflowState.RADIOLOGIST_REVIEW.value,
        WorkflowState.REPORT_DRAFT.value,
        None,
    ):
        current_display = study.workflow_state or "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Study is not eligible for orthopedic review; current workflow state is {current_display}.",
        )

    report = (
        db.query(Report)
        .filter(Report.study_id == study.study_id, Report.status == "APPROVED")
        .order_by(Report.id.desc())
        .first()
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No approved radiology report exists for this study.",
        )

    ortho = db.query(OrthopedicReview).filter_by(study_id=study_id).order_by(OrthopedicReview.id.desc()).first()
    return OrthopedicStudyResponse(
        study_id=study.study_id,
        workflow_state=study.workflow_state,
        approved_report=report.draft_content,
        approved_radiology_report=report.draft_content,
        clinical_context=None,
        patient_id=study.patient_id,
        data_mode=study.data_mode,
        patient_explanation=report.patient_explanation,
        orthopedic_review={"assessment": ortho.assessment, "recommendation": ortho.recommendation,
                           "notes": ortho.notes, "patient_information_approved": ortho.patient_information_approved,
                           "approved_followup_info": ortho.approved_followup_info} if ortho else None,
    )


@app.post(
    "/orthopedic/{study_id}/review",
    response_model=OrthopedicReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_orthopedic_review(
    study_id: str,
    request: SubmitOrthopedicReviewRequest,
    principal: OrthopedicPrincipal = Depends(require_orthopedic),
    db: Session = Depends(get_db),
) -> OrthopedicReviewResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")

    if study.workflow_state == WorkflowState.ORTHOPEDIC_REVIEW.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Study has already undergone orthopedic review.",
        )

    if not can_transition(study.workflow_state, WorkflowState.ORTHOPEDIC_REVIEW):
        current_display = study.workflow_state or "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal workflow transition from {current_display} to {WorkflowState.ORTHOPEDIC_REVIEW.value}.",
        )

    report = (
        db.query(Report)
        .filter(Report.study_id == study.study_id, Report.status == "APPROVED")
        .order_by(Report.id.desc())
        .first()
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No approved radiology report exists for this study.",
        )

    if request.patient_information_approved and not report.patient_explanation:
        raise HTTPException(status_code=409, detail="Radiologist must generate the patient explanation before patient-information approval.")

    patient_info_approved = (
        request.patient_information_approved is True
    )

    try:
        ortho_review = OrthopedicReview(
            study_id=study.study_id,
            reviewer_id=principal.user_id,
            assessment=request.assessment,
            recommendation=request.recommendation,
            notes=request.notes,
            patient_information_approved=patient_info_approved,
            approved_followup_info=request.approved_followup_info,
        )
        db.add(ortho_review)
        db.flush()

        db.add(
            AuditLog(
                action="ORTHOPEDIC_REVIEW_SUBMITTED",
                actor_id=principal.user_id,
                study_id=study.study_id,
                details=f"review_id={ortho_review.id}",
            )
        )

        transition_workflow(
            db=db,
            study=study,
            next_state=WorkflowState.ORTHOPEDIC_REVIEW,
            actor_id=principal.user_id,
        )

        db.commit()
        db.refresh(ortho_review)
    except Exception:
        db.rollback()
        raise

    return OrthopedicReviewResponse(
        id=ortho_review.id,
        study_id=ortho_review.study_id,
        reviewer_id=ortho_review.reviewer_id,
        assessment=ortho_review.assessment,
        recommendation=ortho_review.recommendation,
        notes=ortho_review.notes,
        patient_information_approved=ortho_review.patient_information_approved,
        approved_followup_info=ortho_review.approved_followup_info,
        created_at=ortho_review.created_at,
        workflow_state=study.workflow_state,
    )


@app.post(
    "/studies/{study_id}/patient-release",
    response_model=PatientReleaseResponse,
    status_code=status.HTTP_200_OK,
)
def release_study_to_patient(
    study_id: str,
    request: PatientReleaseRequest | None = None,
    principal: ReleasePrincipal = Depends(require_release_authority),
    db: Session = Depends(get_db),
) -> PatientReleaseResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")

    if study.workflow_state == WorkflowState.PATIENT_RELEASED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Study has already been released to the patient.",
        )

    if not can_transition(study.workflow_state, WorkflowState.PATIENT_RELEASED):
        current_display = study.workflow_state or "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal workflow transition from {current_display} to {WorkflowState.PATIENT_RELEASED.value}.",
        )

    # 1. Study must have an APPROVED report
    report = (
        db.query(Report)
        .filter(Report.study_id == study.study_id, Report.status == "APPROVED")
        .order_by(Report.id.desc())
        .first()
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot release study to patient without an approved radiology report.",
        )

    if not report.patient_explanation:
        raise HTTPException(status_code=409, detail="Patient explanation is required before release.")

    # 2. Study must have undergone orthopedic review
    ortho_review = (
        db.query(OrthopedicReview)
        .filter(OrthopedicReview.study_id == study.study_id)
        .order_by(OrthopedicReview.id.desc())
        .first()
    )
    if ortho_review is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot release study to patient without an orthopedic clinical review.",
        )

    # 3. Explicit persisted patient-information approval is REQUIRED before release.
    # The gate strictly checks the persisted value in orthopedic_review.
    # A request payload must NEVER be able to turn a persisted False or absent into True.
    if not getattr(ortho_review, "patient_information_approved", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot release study to patient without explicit patient-information approval.",
        )
    if request and request.patient_information_approved is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot release study to patient without explicit patient-information approval.",
        )

    # 4. Patient release requires Study.patient_id to already be populated by a trusted server-side association
    if not study.patient_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot release study to patient: study has no associated patient ID.",
        )

    try:
        transition_workflow(
            db=db,
            study=study,
            next_state=WorkflowState.PATIENT_RELEASED,
            actor_id=principal.user_id,
        )

        audit = AuditLog(
            action="PATIENT_RELEASED",
            actor_id=principal.user_id,
            study_id=study.study_id,
            details=f"released_to={study.patient_id}",
        )
        db.add(audit)
        db.commit()
        db.refresh(study)
        db.refresh(audit)
    except Exception:
        db.rollback()
        raise

    return PatientReleaseResponse(
        study_id=study.study_id,
        workflow_state=study.workflow_state,
        released_by=principal.user_id,
        released_at=audit.created_at,
        patient_id=study.patient_id,
        message="Study successfully released to patient.",
    )


@app.get(
    "/patient/reports",
    response_model=list[PatientReportResponse],
    status_code=status.HTTP_200_OK,
)
def list_patient_reports(
    principal: PatientPrincipal = Depends(require_patient),
    db: Session = Depends(get_db),
) -> list[PatientReportResponse]:
    studies = (
        db.query(Study)
        .filter(
            Study.patient_id == principal.user_id,
            Study.workflow_state == WorkflowState.PATIENT_RELEASED.value,
        )
        .order_by(Study.id)
        .all()
    )

    results = []
    for study in studies:
        report = (
            db.query(Report)
            .filter(Report.study_id == study.study_id, Report.status == "APPROVED")
            .order_by(Report.id.desc())
            .first()
        )
        if report is not None:
            audit = (
                db.query(AuditLog)
                .filter(AuditLog.study_id == study.study_id, AuditLog.action == "PATIENT_RELEASED")
                .order_by(AuditLog.id.desc())
                .first()
            )
            released_at = audit.created_at if audit else report.created_at

            explanation_data = None
            if report.patient_explanation:
                try:
                    explanation_data = json.loads(report.patient_explanation)
                except Exception:
                    explanation_data = report.patient_explanation

            ortho_review = (
                db.query(OrthopedicReview)
                .filter(OrthopedicReview.study_id == study.study_id)
                .order_by(OrthopedicReview.id.desc())
                .first()
            )
            followup = ortho_review.approved_followup_info if ortho_review else None

            results.append(
                PatientReportResponse(
                    study_id=study.study_id,
                    status="RELEASED",
                    approved_report=report.draft_content,
                    patient_explanation=explanation_data,
                    approved_followup_info=followup,
                    data_mode=study.data_mode or "CLINICAL",
                    released_at=released_at,
                )
            )
    return results


@app.get(
    "/patient/reports/{study_id}",
    response_model=PatientReportResponse,
    status_code=status.HTTP_200_OK,
)
def get_patient_report(
    study_id: str,
    principal: PatientPrincipal = Depends(require_patient),
    db: Session = Depends(get_db),
) -> PatientReportResponse:
    study = db.query(Study).filter(Study.study_id == study_id).one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study was not found.")

    if study.patient_id is not None and study.patient_id != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: you do not have permission to access this patient report.",
        )

    if study.patient_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: study is not linked to this patient account.",
        )

    if study.workflow_state != WorkflowState.PATIENT_RELEASED.value:
        current_display = study.workflow_state or "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report is not released to patient; current workflow state is {current_display}.",
        )

    report = (
        db.query(Report)
        .filter(Report.study_id == study.study_id, Report.status == "APPROVED")
        .order_by(Report.id.desc())
        .first()
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No approved radiology report exists for this study.",
        )

    audit = (
        db.query(AuditLog)
        .filter(AuditLog.study_id == study.study_id, AuditLog.action == "PATIENT_RELEASED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    released_at = audit.created_at if audit else report.created_at

    explanation_data = None
    if report.patient_explanation:
        try:
            explanation_data = json.loads(report.patient_explanation)
        except Exception:
            explanation_data = report.patient_explanation

    ortho_review = (
        db.query(OrthopedicReview)
        .filter(OrthopedicReview.study_id == study.study_id)
        .order_by(OrthopedicReview.id.desc())
        .first()
    )
    followup = ortho_review.approved_followup_info if ortho_review else None

    return PatientReportResponse(
        study_id=study.study_id,
        status="RELEASED",
        approved_report=report.draft_content,
        patient_explanation=explanation_data,
        approved_followup_info=followup,
        data_mode=study.data_mode or "CLINICAL",
        released_at=released_at,
    )

