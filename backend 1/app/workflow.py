"""Centralized clinical workflow state machine for KNEE-AI 3.3 backend.

All clinical workflow state definitions and transition rules are centralized
here. Workflow state represents the overarching clinical study progression,
separate from the report's own DRAFT/APPROVED status.
"""

from enum import Enum
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.study import Study


class WorkflowState(str, Enum):
    AI_COMPLETE = "AI_COMPLETE"
    RADIOLOGIST_REVIEW = "RADIOLOGIST_REVIEW"
    REPORT_DRAFT = "REPORT_DRAFT"
    RADIOLOGIST_APPROVED = "RADIOLOGIST_APPROVED"
    ORTHOPEDIC_REVIEW = "ORTHOPEDIC_REVIEW"
    PATIENT_RELEASED = "PATIENT_RELEASED"


INITIAL_WORKFLOW_STATE = WorkflowState.AI_COMPLETE

# Authoritative transition rules. Only these transitions are legal.
LEGAL_TRANSITIONS: dict[WorkflowState, list[WorkflowState]] = {
    WorkflowState.AI_COMPLETE: [WorkflowState.RADIOLOGIST_REVIEW],
    WorkflowState.RADIOLOGIST_REVIEW: [WorkflowState.REPORT_DRAFT],
    WorkflowState.REPORT_DRAFT: [WorkflowState.RADIOLOGIST_APPROVED],
    WorkflowState.RADIOLOGIST_APPROVED: [WorkflowState.ORTHOPEDIC_REVIEW],
    WorkflowState.ORTHOPEDIC_REVIEW: [WorkflowState.PATIENT_RELEASED],
    WorkflowState.PATIENT_RELEASED: [],
}


def parse_workflow_state(state: WorkflowState | str | None) -> WorkflowState | None:
    """Safely parse state into a WorkflowState enum or return None if empty/invalid."""
    if state is None:
        return None
    if isinstance(state, WorkflowState):
        return state
    try:
        return WorkflowState(state)
    except ValueError:
        return None


def can_transition(
    current_state: WorkflowState | str | None,
    next_state: WorkflowState | str,
) -> bool:
    """Check whether transitioning from current_state to next_state is legally allowed."""
    current = parse_workflow_state(current_state)
    target = parse_workflow_state(next_state)
    if target is None:
        return False

    # A study without workflow state may only transition to the initial state (AI_COMPLETE)
    if current is None:
        return target == INITIAL_WORKFLOW_STATE

    # Allow idempotent re-running of AI inference before radiologist review
    if current == WorkflowState.AI_COMPLETE and target == WorkflowState.AI_COMPLETE:
        return True

    allowed_next_states = LEGAL_TRANSITIONS.get(current, [])
    return target in allowed_next_states


def transition_workflow(
    db: Session,
    study: Study,
    next_state: WorkflowState | str,
    actor_id: str,
) -> WorkflowState:
    """Authoritative transition function.

    Validates transition legality, updates the study workflow state, and emits
    an audit log entry. Raises HTTP 409 Conflict if the transition is illegal.
    """
    target = parse_workflow_state(next_state)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invalid target workflow state: {next_state}",
        )

    current = parse_workflow_state(study.workflow_state)

    if not can_transition(current, target):
        current_display = current.value if current else "UNINITIALIZED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Illegal workflow transition from {current_display} to {target.value}.",
        )

    from_state_str = current.value if current else "None"
    study.workflow_state = target.value

    db.add(
        AuditLog(
            action="WORKFLOW_TRANSITION",
            actor_id=actor_id,
            study_id=study.study_id,
            details=f"from_state={from_state_str}; to_state={target.value}",
        )
    )

    return target
