"""Boundary planning session for host-agent LLM decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from doc_splitter.boundary.safe_candidates import (
    SafeCandidate,
    candidates_in_word_window,
    find_safe_candidates,
)
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import load_json, save_json
from doc_splitter.section_titles import validate_boundary_reason
from doc_splitter.storage import file_lock
from doc_splitter.structure_analyzer import analyze_structure, page_range_for_elements
from doc_splitter.topic_reviews import find_topic_change_candidates
from doc_splitter.workflow import (
    BOUNDARY,
    BOUNDARY_COMPLETE,
    TOPIC_REVIEW,
    require_stage,
    transition_stage,
)

SESSION_FILE = ".split-session.json"


@dataclass
class BoundaryDecision:
    end_element_id: str
    end_index: int
    reason: str
    est_pages: float | None = None


@dataclass
class SplitSession:
    source_file: str
    output_dir: str
    config: dict[str, Any]
    stage: str = "boundary"
    cursor_index: int = 0
    window_pages: int = 10
    boundaries: list[dict[str, Any]] = field(default_factory=list)
    topic_change_reviews: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_analyses: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunks_read: list[int] = field(default_factory=list)
    extensions: list[dict[str, Any]] = field(default_factory=list)
    repair_queue: list[dict[str, Any]] = field(default_factory=list)
    active_repair: dict[str, Any] | None = None
    repair_history: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 0
    updated_at: str | None = None
    last_error: str | None = None
    failed_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "output_dir": self.output_dir,
            "config": self.config,
            "stage": self.stage,
            "cursor_index": self.cursor_index,
            "window_pages": self.window_pages,
            "boundaries": self.boundaries,
            "topic_change_reviews": self.topic_change_reviews,
            "chunk_analyses": self.chunk_analyses,
            "chunks_read": self.chunks_read,
            "extensions": self.extensions,
            "repair_queue": self.repair_queue,
            "active_repair": self.active_repair,
            "repair_history": self.repair_history,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
            "failed_from": self.failed_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SplitSession:
        return cls(
            source_file=data["source_file"],
            output_dir=data["output_dir"],
            config=data.get("config", {}),
            stage=data.get("stage", "boundary"),
            cursor_index=int(data.get("cursor_index", 0)),
            window_pages=int(data.get("window_pages", 10)),
            boundaries=list(data.get("boundaries", [])),
            topic_change_reviews=dict(data.get("topic_change_reviews", {})),
            chunk_analyses=dict(data.get("chunk_analyses", {})),
            chunks_read=list(data.get("chunks_read", [])),
            extensions=list(data.get("extensions", [])),
            repair_queue=list(data.get("repair_queue", [])),
            active_repair=data.get("active_repair"),
            repair_history=list(data.get("repair_history", [])),
            revision=int(data.get("revision", 0)),
            updated_at=data.get("updated_at"),
            last_error=data.get("last_error"),
            failed_from=data.get("failed_from"),
        )


def session_path(output_dir: Path) -> Path:
    return output_dir / SESSION_FILE


class SessionConflictError(RuntimeError):
    """Raised when a stale in-memory session would overwrite newer state."""


def _session_lock_path(output_dir: Path) -> Path:
    return output_dir / f"{SESSION_FILE}.lock"


def save_session(session: SplitSession, output_dir: Path) -> None:
    output_dir = output_dir.expanduser().resolve()
    path = session_path(output_dir)
    with file_lock(_session_lock_path(output_dir)):
        current_revision: int | None = None
        if path.exists():
            current_revision = int(load_json(path).get("revision", 0))
            if current_revision != session.revision:
                raise SessionConflictError(
                    "Session changed since it was loaded "
                    f"(expected revision {session.revision}, found {current_revision}). "
                    "Reload the session and retry the operation."
                )
        elif session.revision != 0:
            raise SessionConflictError(
                f"Session file is missing but in-memory revision is {session.revision}."
            )

        next_revision = (current_revision or 0) + 1
        payload = session.to_dict()
        payload["revision"] = next_revision
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload["output_dir"] = str(output_dir)
        save_json(payload, path)
        session.revision = next_revision
        session.updated_at = payload["updated_at"]
        session.output_dir = str(output_dir)


def record_chunk_read(output_dir: Path, chunk_id: int, *, retries: int = 5) -> None:
    """Record a read without silently losing a concurrent agent update."""
    last_conflict: SessionConflictError | None = None
    for _ in range(max(1, retries)):
        session = load_session(output_dir)
        if chunk_id in session.chunks_read:
            return
        session.chunks_read.append(chunk_id)
        try:
            save_session(session, output_dir)
            return
        except SessionConflictError as exc:
            last_conflict = exc
    assert last_conflict is not None
    raise last_conflict


def load_session(output_dir: Path) -> SplitSession:
    output_dir = output_dir.expanduser().resolve()
    session = SplitSession.from_dict(load_json(session_path(output_dir)))
    # The command's current --out path is authoritative; sessions remain movable.
    session.output_dir = str(output_dir)
    return session


def _is_page_number_artifact(el: Any) -> bool:
    """Recognize extracted page footers without discarding legitimate content."""
    if el.type != "paragraph" or not el.page_number:
        return False
    text = el.text.strip()
    return text.isdecimal() and int(text) == el.page_number


def _is_trailing_page_number_range(
    ir: DocumentIR,
    start_index: int,
    end_index: int,
) -> bool:
    return start_index <= end_index and all(
        _is_page_number_artifact(el) for el in ir.elements[start_index : end_index + 1]
    )


def _within_page_limit(
    ir: DocumentIR,
    start_index: int,
    candidate: SafeCandidate,
    element_pages: dict[str, int],
    max_pages: int,
) -> bool:
    start_page, end_page = page_range_for_elements(ir, start_index, candidate.index, element_pages)
    return start_page is None or end_page is None or end_page - start_page + 1 <= max_pages


def _next_confirmed_topic_boundary(
    session: SplitSession,
    cursor_index: int,
) -> dict[str, Any] | None:
    confirmed = [
        review
        for review in session.topic_change_reviews.values()
        if review.get("consensus") == "split"
        and int(review.get("boundary_index", -1)) >= cursor_index
    ]
    if not confirmed:
        return None
    return min(confirmed, key=lambda review: int(review["boundary_index"]))


def get_topic_review_progress(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
) -> dict[str, Any]:
    candidates = find_topic_change_candidates(ir, config)
    unresolved: list[dict[str, Any]] = []
    resolved = 0
    for candidate in candidates:
        stored = session.topic_change_reviews.get(candidate.review_id)
        consensus = stored.get("consensus") if stored else None
        votes = stored.get("votes", {}) if stored else {}
        matching_votes = sum(1 for vote in votes.values() if vote.get("decision") == consensus)
        required_votes = (
            config.topic_change_min_votes
            if consensus == "split"
            else config.topic_change_merge_min_votes
        )
        if consensus in {"split", "merge"} and matching_votes >= required_votes:
            resolved += 1
        else:
            unresolved.append(
                {
                    "review_id": candidate.review_id,
                    "heading_element_id": candidate.heading_element_id,
                    "heading_text": candidate.heading_text,
                    "boundary_element_id": candidate.boundary_element_id,
                    "boundary_index": candidate.boundary_index,
                    "consensus": consensus or "missing",
                }
            )
    return {
        "total": len(candidates),
        "resolved": resolved,
        "unresolved": unresolved,
        "complete": not unresolved,
    }


def commit_topic_change_reviews(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist evidence-backed semantic verdicts from independent reviewers."""
    require_stage(session, TOPIC_REVIEW, "commit topic-change reviews")
    candidates = {
        candidate.review_id: candidate for candidate in find_topic_change_candidates(ir, config)
    }
    committed = 0
    for review in reviews:
        review_id = str(review.get("review_id", ""))
        decision = str(review.get("decision", ""))
        reason = str(review.get("reason", ""))
        reviewer_id = str(review.get("reviewer_id", "")).strip()
        candidate = candidates.get(review_id)
        if candidate is None:
            raise ValueError(f"Unknown topic-change review: {review_id}")
        if decision not in {"split", "merge"}:
            raise ValueError(f"Review {review_id} must choose split or merge")
        if not reviewer_id:
            raise ValueError(f"Review {review_id} must include reviewer_id")
        validate_boundary_reason(reason)
        try:
            confidence = float(review.get("confidence", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Review {review_id} confidence must be numeric") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"Review {review_id} confidence must be between 0 and 1")

        evidence_before = [str(value) for value in review.get("evidence_before", [])]
        evidence_after = [str(value) for value in review.get("evidence_after", [])]
        if not evidence_before or not evidence_after:
            raise ValueError(
                f"Review {review_id} must cite evidence_before and evidence_after element IDs"
            )
        invalid_before = set(evidence_before) - set(candidate.before_element_ids)
        invalid_after = set(evidence_after) - set(candidate.after_element_ids)
        if invalid_before or invalid_after:
            raise ValueError(
                f"Review {review_id} cites evidence outside its context: "
                f"before={sorted(invalid_before)}, after={sorted(invalid_after)}"
            )

        stored = session.topic_change_reviews.setdefault(
            review_id,
            {
                "heading_element_id": candidate.heading_element_id,
                "heading_text": candidate.heading_text,
                "boundary_element_id": candidate.boundary_element_id,
                "boundary_index": candidate.boundary_index,
                "candidate_kind": candidate.candidate_kind,
                "semantic_score": candidate.semantic_score,
                "votes": {},
                "consensus": "pending",
            },
        )
        votes = stored.setdefault("votes", {})
        votes[reviewer_id] = {
            "decision": decision,
            "reason": reason,
            "confidence": confidence,
            "evidence_before": evidence_before,
            "evidence_after": evidence_after,
        }
        split_votes = sum(1 for vote in votes.values() if vote.get("decision") == "split")
        merge_votes = sum(1 for vote in votes.values() if vote.get("decision") == "merge")
        # Split is intentionally asymmetric: a credible split minority prevents
        # an automatic merge until an adjudicator resolves the disagreement.
        if split_votes >= config.topic_change_min_votes:
            stored["consensus"] = "split"
        elif merge_votes >= config.topic_change_merge_min_votes and split_votes == 0:
            stored["consensus"] = "merge"
        else:
            stored["consensus"] = "pending"
        committed += 1
    progress = get_topic_review_progress(ir, session, config)
    if progress["complete"]:
        transition_stage(session, BOUNDARY)
    save_session(session, Path(session.output_dir))
    split_count = sum(
        1 for review in session.topic_change_reviews.values() if review.get("consensus") == "split"
    )
    return {
        "status": ("topic_reviews_complete" if progress["complete"] else "topic_reviews_committed"),
        "committed": committed,
        "confirmed_topic_boundaries": split_count,
        "review_progress": progress,
        "next_stage": session.stage,
    }


def _element_text_window(ir: DocumentIR, start: int, end: int) -> str:
    parts: list[str] = []
    for el in ir.elements[start : end + 1]:
        if el.type == "heading":
            parts.append(f"{'#' * (el.level or 1)} {el.text}")
        elif el.type == "paragraph":
            parts.append(el.text)
        elif el.type == "list":
            parts.extend(f"- {item}" for item in el.items)
        elif el.type == "table":
            for row in el.rows:
                parts.append("| " + " | ".join(row) + " |")
        elif el.type == "image":
            parts.append(f"[image: {el.ref}] {el.caption or ''}")
    return "\n\n".join(parts)


def _page_count_for_range(
    ir: DocumentIR,
    start_index: int,
    end_index: int,
    element_pages: dict[str, int],
) -> int | None:
    start_page, end_page = page_range_for_elements(ir, start_index, end_index, element_pages)
    if start_page is None or end_page is None:
        return None
    return end_page - start_page + 1


def _last_index_within_page_limit(
    ir: DocumentIR,
    start_index: int,
    page_limit: int,
    element_pages: dict[str, int],
) -> int:
    end_index = start_index
    for index in range(start_index, len(ir.elements)):
        pages = _page_count_for_range(ir, start_index, index, element_pages)
        if pages is not None and pages > page_limit:
            break
        end_index = index
    return end_index


def _topic_boundary_within_page_limit(
    ir: DocumentIR,
    session: SplitSession,
    structure: Any,
    page_limit: int,
) -> dict[str, Any] | None:
    candidates = []
    for review in session.topic_change_reviews.values():
        if review.get("consensus") != "split":
            continue
        boundary_index = int(review.get("boundary_index", -1))
        if boundary_index < session.cursor_index:
            continue
        pages = _page_count_for_range(
            ir, session.cursor_index, boundary_index, structure.element_pages
        )
        if pages is None or pages <= page_limit:
            candidates.append(review)
    if not candidates:
        return None
    return min(candidates, key=lambda review: int(review["boundary_index"]))


def _validate_continuity_evidence(
    ir: DocumentIR,
    config: SplitConfig,
    *,
    evidence: list[str] | None,
    reviewers: list[str] | None,
    current_end_index: int,
    next_end_index: int,
) -> tuple[list[str], list[str]]:
    evidence_ids = list(dict.fromkeys(str(value) for value in (evidence or [])))
    reviewer_ids = list(
        dict.fromkeys(str(value).strip() for value in (reviewers or []) if str(value).strip())
    )
    if len(reviewer_ids) < config.continuity_min_reviewers:
        raise ValueError(
            f"Extending beyond soft_max_pages={config.soft_max_pages} requires "
            f"at least {config.continuity_min_reviewers} independent continuity reviewers."
        )
    if len(evidence_ids) < 2:
        raise ValueError(
            "Extending beyond the soft maximum requires at least two evidence element IDs."
        )
    invalid = [element_id for element_id in evidence_ids if ir.element_by_id(element_id) is None]
    if invalid:
        raise ValueError(f"Unknown continuity evidence element IDs: {invalid}")
    evidence_indices = [ir.index_of(element_id) for element_id in evidence_ids]
    if any(index > next_end_index for index in evidence_indices):
        raise ValueError("Continuity evidence must be inside the proposed extended window.")
    if not any(index <= current_end_index for index in evidence_indices) or not any(
        current_end_index < index <= next_end_index for index in evidence_indices
    ):
        raise ValueError(
            "Continuity evidence must cite content on both sides of the one-page extension."
        )
    return evidence_ids, reviewer_ids


def get_boundary_context(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
) -> dict[str, Any]:
    require_stage(
        session,
        {BOUNDARY, BOUNDARY_COMPLETE},
        "request boundary context",
    )
    if session.cursor_index >= len(ir.elements):
        if session.stage == BOUNDARY:
            transition_stage(session, BOUNDARY_COMPLETE)
            save_session(session, Path(session.output_dir))
        return {
            "status": "complete",
            "stage": session.stage,
            "boundaries": session.boundaries,
        }
    require_stage(session, BOUNDARY, "request the next boundary decision")

    structure = analyze_structure(ir, config)
    session.window_pages = min(session.window_pages, config.hard_max_pages)
    word_end, _ = candidates_in_word_window(
        ir,
        session.cursor_index,
        session.window_pages * config.words_per_page,
        0,
    )

    page_end = _last_index_within_page_limit(
        ir, session.cursor_index, session.window_pages, structure.element_pages
    )
    end_index = min(word_end, page_end)
    all_candidates = find_safe_candidates(ir, session.cursor_index, end_index)

    start_words = (
        ir.elements[session.cursor_index - 1].cumulative_word_count
        if session.cursor_index > 0
        else 0
    )
    min_target = start_words + config.min_chunk_words()
    candidates = [
        candidate for candidate in all_candidates if candidate.cumulative_word_count >= min_target
    ]
    # A short final remainder is still a valid explicit final boundary.
    if not candidates and end_index == len(ir.elements) - 1:
        candidates = all_candidates

    required_topic_boundary = _topic_boundary_within_page_limit(
        ir, session, structure, session.window_pages
    )
    if required_topic_boundary:
        boundary_index = int(required_topic_boundary["boundary_index"])
        end_index = min(end_index, boundary_index)
        candidates = [candidate for candidate in candidates if candidate.index == boundary_index]
        if not candidates:
            candidates = find_safe_candidates(ir, boundary_index, boundary_index)

    document_continues = end_index < len(ir.elements) - 1
    forced_size_split = (
        session.window_pages >= config.hard_max_pages
        and document_continues
        and required_topic_boundary is None
    )
    next_window = min(
        config.hard_max_pages,
        session.window_pages + config.boundary_window_extension_pages,
    )
    extension_requires_evidence = next_window > config.soft_max_pages
    next_topic_boundary = _topic_boundary_within_page_limit(ir, session, structure, next_window)
    can_extend = (
        document_continues
        and session.window_pages < config.hard_max_pages
        and next_topic_boundary is None
    )

    start_page, _ = page_range_for_elements(
        ir, session.cursor_index, end_index, structure.element_pages
    )
    prompt_path = Path(__file__).parent / "prompts" / "boundary.md"
    return {
        "status": ("requires_forced_size_split" if forced_size_split else "needs_agent_decision"),
        "chunk_number": len(session.boundaries) + 1,
        "cursor_index": session.cursor_index,
        "window_pages": session.window_pages,
        "estimated_start_page": start_page,
        "content_window": _element_text_window(ir, session.cursor_index, end_index),
        "safe_candidates": [
            {
                "element_id": candidate.element_id,
                "index": candidate.index,
                "after_type": candidate.after_type,
                "snippet": candidate.snippet,
                "cumulative_word_count": candidate.cumulative_word_count,
                "estimated_pages": _page_count_for_range(
                    ir, session.cursor_index, candidate.index, structure.element_pages
                ),
            }
            for candidate in candidates
        ],
        "instructions": prompt_path.read_text(encoding="utf-8"),
        "page_policy": {
            "target_min_pages": config.min_pages,
            "preferred_max_pages": config.max_pages,
            "soft_max_pages": config.soft_max_pages,
            "hard_max_pages": config.hard_max_pages,
            "topic_change_overrides_minimum": True,
        },
        # Legacy fields retained for MCP/CLI clients.
        "min_pages": config.min_pages,
        "max_pages": config.max_pages,
        "soft_max_pages": config.soft_max_pages,
        "hard_max_pages": config.hard_max_pages,
        "can_extend": can_extend,
        "next_window_pages": next_window if can_extend else None,
        "extension_requires_semantic_evidence": extension_requires_evidence,
        "forced_size_split": forced_size_split,
        "required_topic_boundary": required_topic_boundary,
        "blocking_topic_boundary_for_extension": next_topic_boundary,
    }


def commit_boundary(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
    *,
    action: Literal["cut", "extend"],
    element_id: str | None = None,
    reason: str = "",
    allow_oversize: bool = False,
    allow_topic_merge: bool = False,
    continuity_evidence: list[str] | None = None,
    continuity_reviewers: list[str] | None = None,
) -> dict[str, Any]:
    require_stage(session, BOUNDARY, "commit a boundary decision")
    structure = analyze_structure(ir, config)

    if action == "extend":
        if not allow_oversize:
            raise ValueError(
                "Extending beyond preferred_max_pages requires allow_oversize=True. "
                "Use it only when the same topic demonstrably continues."
            )
        validate_boundary_reason(reason)
        if session.window_pages >= config.hard_max_pages:
            raise ValueError(
                f"Cannot extend beyond hard_max_pages={config.hard_max_pages}. "
                "Choose the best safe boundary and mark a forced continuation."
            )
        next_window = min(
            config.hard_max_pages,
            session.window_pages + config.boundary_window_extension_pages,
        )
        blocking_topic = _topic_boundary_within_page_limit(ir, session, structure, next_window)
        if blocking_topic is not None:
            raise ValueError(
                "Cannot extend across a confirmed topic change before "
                f"{blocking_topic['heading_text']}. Cut at "
                f"{blocking_topic['boundary_element_id']}."
            )

        evidence_ids: list[str] = []
        reviewer_ids: list[str] = []
        if next_window > config.soft_max_pages:
            current_end_index = _last_index_within_page_limit(
                ir, session.cursor_index, session.window_pages, structure.element_pages
            )
            next_end_index = _last_index_within_page_limit(
                ir, session.cursor_index, next_window, structure.element_pages
            )
            evidence_ids, reviewer_ids = _validate_continuity_evidence(
                ir,
                config,
                evidence=continuity_evidence,
                reviewers=continuity_reviewers,
                current_end_index=current_end_index,
                next_end_index=next_end_index,
            )

        previous_window = session.window_pages
        session.window_pages = next_window
        extension_record = {
            "chunk_number": len(session.boundaries) + 1,
            "cursor_index": session.cursor_index,
            "from_pages": previous_window,
            "to_pages": next_window,
            "reason": reason,
            "evidence_element_ids": evidence_ids,
            "reviewer_ids": reviewer_ids,
            "semantic_evidence_required": next_window > config.soft_max_pages,
        }
        session.extensions.append(extension_record)
        save_session(session, Path(session.output_dir))
        return {
            "status": "extended",
            "window_pages": session.window_pages,
            "extension": extension_record,
        }

    if not element_id:
        raise ValueError("element_id is required for action=cut")
    validate_boundary_reason(reason)
    end_index = ir.index_of(element_id)
    if end_index < session.cursor_index:
        raise ValueError("Boundary cannot move backwards before the current cursor")

    confirmed_topic_boundaries = [
        review
        for review in session.topic_change_reviews.values()
        if review.get("consensus") == "split"
        and session.cursor_index <= int(review.get("boundary_index", -1)) < end_index
    ]
    if confirmed_topic_boundaries:
        nearest = min(
            confirmed_topic_boundaries,
            key=lambda review: int(review["boundary_index"]),
        )
        raise ValueError(
            "Cut would cross a confirmed topic change before "
            f"{nearest['heading_text']}. Cut at {nearest['boundary_element_id']}; "
            "confirmed topic changes cannot be overridden."
        )

    start_page, end_page = page_range_for_elements(
        ir, session.cursor_index, end_index, structure.element_pages
    )
    est_pages = (
        end_page - start_page + 1 if start_page is not None and end_page is not None else None
    )
    if est_pages is not None and est_pages > config.hard_max_pages:
        raise ValueError(
            f"Boundary would create {est_pages} pages, exceeding "
            f"hard_max_pages={config.hard_max_pages}."
        )
    if est_pages is not None and est_pages > session.window_pages:
        raise ValueError(
            f"Boundary is outside the approved {session.window_pages}-page window. "
            "Extend the window with the required semantic evidence first."
        )

    allowed = {
        candidate.element_id
        for candidate in find_safe_candidates(ir, session.cursor_index, end_index)
        if _within_page_limit(
            ir,
            session.cursor_index,
            candidate,
            structure.element_pages,
            session.window_pages,
        )
    }
    is_final_element = end_index == len(ir.elements) - 1
    if element_id not in allowed and not is_final_element:
        raise ValueError(
            f"element_id {element_id} is not a structurally safe candidate "
            "inside the approved window"
        )

    if (
        is_final_element
        and session.boundaries
        and _is_trailing_page_number_range(ir, session.cursor_index, end_index)
    ):
        previous = session.boundaries[-1]
        previous_start = int(previous["start_index"])
        merged_start_page, merged_end_page = page_range_for_elements(
            ir, previous_start, end_index, structure.element_pages
        )
        previous["end_element_id"] = element_id
        previous["end_index"] = end_index
        previous["end_page"] = merged_end_page
        previous["est_pages"] = (
            merged_end_page - merged_start_page + 1
            if merged_start_page is not None and merged_end_page is not None
            else None
        )
        previous["trailing_page_number_merged"] = True
        session.cursor_index = end_index + 1
        session.window_pages = config.max_pages
        transition_stage(session, BOUNDARY_COMPLETE)
        save_session(session, Path(session.output_dir))
        return {
            "status": "complete",
            "stage": session.stage,
            "boundaries": session.boundaries,
        }

    topic_boundary_here = any(
        review.get("consensus") == "split" and int(review.get("boundary_index", -1)) == end_index
        for review in session.topic_change_reviews.values()
    )
    document_continues = end_index < len(ir.elements) - 1
    forced_size_split = (
        document_continues
        and session.window_pages >= config.hard_max_pages
        and not topic_boundary_here
    )
    previous_continues = bool(
        session.boundaries and session.boundaries[-1].get("continues_to_next")
    )
    relevant_extensions = [
        extension
        for extension in session.extensions
        if int(extension.get("cursor_index", -1)) == session.cursor_index
    ]

    boundary_record = {
        "end_element_id": element_id,
        "end_index": end_index,
        "reason": reason,
        "start_index": session.cursor_index,
        "est_pages": est_pages,
        "start_page": start_page,
        "end_page": end_page,
        "split_type": (
            "topic_change"
            if topic_boundary_here
            else "forced_size_split"
            if forced_size_split
            else "conceptual"
        ),
        "continues_to_next": forced_size_split,
        "continues_from_previous": previous_continues,
        "extension_evidence": relevant_extensions,
    }
    session.boundaries.append(boundary_record)
    session.cursor_index = end_index + 1
    session.window_pages = config.max_pages
    if session.cursor_index >= len(ir.elements):
        transition_stage(session, BOUNDARY_COMPLETE)
    save_session(session, Path(session.output_dir))

    if session.cursor_index >= len(ir.elements):
        return {
            "status": "complete",
            "stage": session.stage,
            "boundaries": session.boundaries,
        }
    return {
        "status": "continue",
        "stage": session.stage,
        "cursor_index": session.cursor_index,
        "boundary": boundary_record,
    }
