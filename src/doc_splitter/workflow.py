"""Explicit workflow state machine for the document splitting pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

TOPIC_REVIEW = "topic_review"
BOUNDARY = "boundary"
BOUNDARY_COMPLETE = "boundary_complete"
WRITING = "writing"
VERIFICATION = "verification"
CONTENT_ANALYSIS = "content_analysis"
BOUNDARY_REPAIR = "boundary_repair"
INDEX = "index"
COMPLETE = "complete"
FAILED = "failed"

ALL_STAGES = frozenset(
    {
        TOPIC_REVIEW,
        BOUNDARY,
        BOUNDARY_COMPLETE,
        WRITING,
        VERIFICATION,
        CONTENT_ANALYSIS,
        BOUNDARY_REPAIR,
        INDEX,
        COMPLETE,
        FAILED,
    }
)

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    TOPIC_REVIEW: frozenset({BOUNDARY, FAILED}),
    BOUNDARY: frozenset({BOUNDARY_COMPLETE, FAILED}),
    BOUNDARY_COMPLETE: frozenset({WRITING, FAILED}),
    WRITING: frozenset({VERIFICATION, FAILED}),
    VERIFICATION: frozenset({CONTENT_ANALYSIS, FAILED}),
    CONTENT_ANALYSIS: frozenset({INDEX, BOUNDARY_REPAIR, FAILED}),
    BOUNDARY_REPAIR: frozenset({WRITING, FAILED}),
    INDEX: frozenset({COMPLETE, FAILED}),
    COMPLETE: frozenset(),
    FAILED: frozenset({WRITING, VERIFICATION}),
}


class WorkflowStateError(RuntimeError):
    """Raised when an operation attempts to bypass the pipeline state machine."""


def normalize_stage(stage: str) -> str:
    # Old sessions used only "boundary"; preserve that compatible spelling.
    value = str(stage or BOUNDARY)
    if value not in ALL_STAGES:
        raise WorkflowStateError(f"Unknown workflow stage: {value}")
    return value


def require_stage(session: Any, allowed: str | Iterable[str], operation: str) -> None:
    allowed_set = {allowed} if isinstance(allowed, str) else set(allowed)
    current = normalize_stage(session.stage)
    if current not in allowed_set:
        expected = ", ".join(sorted(allowed_set))
        raise WorkflowStateError(
            f"Cannot {operation} while stage={current}. Required stage: {expected}."
        )


def transition_stage(session: Any, target: str) -> None:
    current = normalize_stage(session.stage)
    target = normalize_stage(target)
    if target == current:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise WorkflowStateError(f"Invalid workflow transition: {current} -> {target}.")
    session.stage = target
    session.last_error = None
    session.failed_from = None


def mark_failed(session: Any, *, failed_from: str, message: str) -> None:
    current = normalize_stage(session.stage)
    if current != FAILED:
        if FAILED not in _ALLOWED_TRANSITIONS[current]:
            raise WorkflowStateError(f"Stage {current} cannot transition to failed.")
        session.stage = FAILED
    session.failed_from = failed_from
    session.last_error = message
