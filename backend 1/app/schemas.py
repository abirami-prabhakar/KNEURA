from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    role: str


class AnalyzeKneeMRIRequest(BaseModel):
    study_id: str = Field(min_length=1, max_length=255)
    action: Literal["ANALYZE_KNEE_MRI"]


class AnalyzeKneeMRIResponse(BaseModel):
    success: bool = True
    study_id: str
    action: Literal["ANALYZE_KNEE_MRI"]
    status: Literal["completed"]
    model_version: str
    architecture: str
    series_evaluated: int
    windows_evaluated: int
    probabilities: dict[str, float]
    requires_radiologist_review: bool
    data_mode: str | None = None


class StudyUploadResponse(BaseModel):
    study_id: str
    file_count: int
    series_count: int
    study_root: str
    series_metadata_path: str
    message: str


class GradCAMRequest(BaseModel):
    study_id: str = Field(min_length=1, max_length=255)
    abnormality: str = Field(min_length=1, max_length=255)
    series_instance_uid: str | None = None
    window_index: int | None = None


class GradCAMResponse(BaseModel):
    model_version: str
    abnormality: str
    class_index: int
    probability: float
    plane: str | None = None
    series_instance_uid: str | None = None
    window_index: int | None = None
    instance_numbers: list[int]
    heatmap: list[list[float]] | Any


ReviewDecision = Literal["CONFIRMED", "REJECTED", "EDITED", "APPROVED", "MIXED"]
FindingOutcome = Literal["CONFIRMED", "REJECTED", "EDITED", "APPROVED"]


class ValidatedFindingRequest(BaseModel):
    finding: str = Field(min_length=1, max_length=255)
    outcome: FindingOutcome
    details: str | None = Field(default=None, max_length=4000)
    is_radiologist_added: bool = False


class StudyReviewRequest(BaseModel):
    decision: ReviewDecision
    validated_findings: list[ValidatedFindingRequest] = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=4000)


class ValidatedFindingResponse(BaseModel):
    finding: str
    outcome: str
    details: str | None = None


class StudyReviewResponse(BaseModel):
    review_id: int
    study_id: str
    reviewer_id: str
    decision: ReviewDecision
    notes: str | None
    created_at: datetime
    validated_findings: list[ValidatedFindingResponse]


class ReportVersionResponse(BaseModel):
    id: int
    report_id: int
    version_number: int
    content: str
    author_id: str
    status: str
    created_at: datetime


class GenerateReportResponse(BaseModel):
    report_id: int
    study_id: str
    status: Literal["DRAFT"]
    draft_content: str
    current_version: int = 1
    created_at: datetime


class EditReportRequest(BaseModel):
    draft_content: str = Field(min_length=1, pattern=r"\S")


class ReportResponse(BaseModel):
    report_id: int
    study_id: str
    status: Literal["DRAFT", "APPROVED"]
    draft_content: str
    current_version: int = 1
    approved_version: int | None = None
    created_at: datetime


class StudyWorkflowResponse(BaseModel):
    study_id: str
    state: str | None


class StudyModeResponse(BaseModel):
    study_id: str
    data_mode: str


class StudySummaryResponse(BaseModel):
    study_id: str
    workflow_state: str | None = None
    patient_id: str | None = None
    data_mode: str | None = None
    ai_available: bool = False
    report_available: bool = False
    report_status: str | None = None


class StudyDetailResponse(BaseModel):
    study_id: str
    workflow_state: str | None = None
    patient_id: str | None = None
    data_mode: str | None = None
    study_root: str | None = None
    series_metadata_path: str | None = None
    ai_probabilities: dict[str, float] | None = None
    validated_findings: list[dict[str, Any]] | None = None
    report: dict[str, Any] | None = None
    orthopedic_review: dict[str, Any] | None = None
    released_at: datetime | None = None


class OrthopedicStudyResponse(BaseModel):
    study_id: str
    workflow_state: str
    approved_report: str
    approved_radiology_report: str | None = None
    clinical_context: str | None = None
    patient_id: str | None = None
    data_mode: str | None = None
    patient_explanation: str | dict | None = None
    orthopedic_review: dict | None = None


class SubmitOrthopedicReviewRequest(BaseModel):
    assessment: str = Field(min_length=1, pattern=r"\S")
    recommendation: str = Field(min_length=1, pattern=r"\S")
    notes: str | None = None
    patient_information_approved: bool | None = None
    approved_followup_info: str | None = None


class OrthopedicReviewResponse(BaseModel):
    id: int
    study_id: str
    reviewer_id: str
    assessment: str
    recommendation: str
    notes: str | None = None
    patient_information_approved: bool = False
    approved_followup_info: str | None = None
    created_at: datetime
    workflow_state: str


class PatientReleaseRequest(BaseModel):
    patient_information_approved: bool | None = None


class PatientReleaseResponse(BaseModel):
    study_id: str
    workflow_state: str
    released_by: str
    released_at: datetime
    patient_id: str | None = None
    message: str


class PatientReportResponse(BaseModel):
    study_id: str
    status: Literal["RELEASED"]
    approved_report: str
    patient_explanation: str | dict | None = None
    approved_followup_info: str | None = None
    data_mode: str | None = None
    released_at: datetime


class PatientExplanationResponse(BaseModel):
    study_id: str
    patient_explanation: str | dict
    created_at: datetime



