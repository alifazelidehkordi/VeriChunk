"""Boundary planning session for host-agent LLM decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from doc_splitter.structure_analyzer import analyze_structure, page_range_for_elements
from doc_splitter.topic_reviews import find_topic_change_candidates

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
        )


def session_path(output_dir: Path) -> Path:
    return output_dir / SESSION_FILE


def save_session(session: SplitSession, output_dir: Path) -> None:
    save_json(session.to_dict(), session_path(output_dir))


def record_chunk_read(output_dir: Path, chunk_id: int) -> None:
    session = load_session(output_dir)
    if chunk_id not in session.chunks_read:
        session.chunks_read.append(chunk_id)
        save_session(session, output_dir)


def load_session(output_dir: Path) -> SplitSession:
    return SplitSession.from_dict(load_json(session_path(output_dir)))


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
        _is_page_number_artifact(el)
        for el in ir.elements[start_index : end_index + 1]
    )


def _within_page_limit(
    ir: DocumentIR,
    start_index: int,
    candidate: SafeCandidate,
    element_pages: dict[str, int],
    max_pages: int,
) -> bool:
    start_page, end_page = page_range_for_elements(
        ir, start_index, candidate.index, element_pages
    )
    return (
        start_page is None
        or end_page is None
        or end_page - start_page + 1 <= max_pages
    )


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


def commit_topic_change_reviews(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
    reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist independent semantic review verdicts from parallel host agents."""
    candidates = {
        candidate.review_id: candidate
        for candidate in find_topic_change_candidates(ir, config)
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
        stored = session.topic_change_reviews.setdefault(
            review_id,
            {
                "heading_element_id": candidate.heading_element_id,
                "heading_text": candidate.heading_text,
                "boundary_element_id": candidate.boundary_element_id,
                "boundary_index": candidate.boundary_index,
                "votes": {},
                "consensus": "pending",
            },
        )
        votes = stored.setdefault("votes", {})
        votes[reviewer_id] = {"decision": decision, "reason": reason}
        split_votes = sum(
            1 for vote in votes.values() if vote.get("decision") == "split"
        )
        merge_votes = sum(
            1 for vote in votes.values() if vote.get("decision") == "merge"
        )
        if split_votes >= config.topic_change_min_votes:
            stored["consensus"] = "split"
        elif merge_votes >= config.topic_change_min_votes:
            stored["consensus"] = "merge"
        else:
            stored["consensus"] = "pending"
        committed += 1
    save_session(session, Path(session.output_dir))
    split_count = sum(
        1
        for review in session.topic_change_reviews.values()
        if review.get("consensus") == "split"
    )
    return {
        "status": "topic_reviews_committed",
        "committed": committed,
        "confirmed_topic_boundaries": split_count,
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


def get_boundary_context(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
) -> dict[str, Any]:
    if session.cursor_index >= len(ir.elements):
        return {"status": "complete", "boundaries": session.boundaries}

    structure = analyze_structure(ir, config)
    window_words = session.window_pages * config.words_per_page
    end_index, candidates = candidates_in_word_window(
        ir,
        session.cursor_index,
        window_words,
        config.min_chunk_words(),
    )
    normal_page_cap = min(config.max_pages, config.hard_max_pages)
    page_cap = (
        normal_page_cap
        if session.window_pages <= normal_page_cap
        else config.hard_max_pages
    )
    if page_cap:
        candidates = [
            candidate
            for candidate in candidates
            if _within_page_limit(
                ir,
                session.cursor_index,
                candidate,
                structure.element_pages,
                page_cap,
            )
        ]

    required_topic_boundary = _next_confirmed_topic_boundary(
        session, session.cursor_index
    )
    if (
        required_topic_boundary
        and int(required_topic_boundary["boundary_index"]) <= end_index
    ):
        boundary_index = int(required_topic_boundary["boundary_index"])
        candidates = [candidate for candidate in candidates if candidate.index <= boundary_index]
        if not any(candidate.index == boundary_index for candidate in candidates):
            matching = find_safe_candidates(ir, boundary_index, boundary_index)
            candidates.extend(matching)
        end_index = boundary_index

    requires_oversize_permission = (
        not candidates and end_index < len(ir.elements) - 1
    )
    if not candidates and not requires_oversize_permission:
        tail_end = len(ir.elements) - 2
        if tail_end >= session.cursor_index:
            end_index = max(end_index, tail_end)
            candidates = find_safe_candidates(ir, session.cursor_index, tail_end)

    start_page, _ = page_range_for_elements(
        ir, session.cursor_index, end_index, structure.element_pages
    )

    prompt_path = Path(__file__).parent / "prompts" / "boundary.md"
    return {
        "status": (
            "needs_oversize_permission"
            if requires_oversize_permission
            else "needs_agent_decision"
        ),
        "chunk_number": len(session.boundaries) + 1,
        "cursor_index": session.cursor_index,
        "window_pages": session.window_pages,
        "estimated_start_page": start_page,
        "content_window": _element_text_window(ir, session.cursor_index, end_index),
        "safe_candidates": [
            {
                "element_id": c.element_id,
                "index": c.index,
                "after_type": c.after_type,
                "snippet": c.snippet,
                "cumulative_word_count": c.cumulative_word_count,
            }
            for c in candidates
        ],
        "instructions": prompt_path.read_text(encoding="utf-8"),
        "min_pages": config.min_pages,
        "max_pages": config.max_pages,
        "requires_oversize_permission": requires_oversize_permission,
        "required_topic_boundary": required_topic_boundary,
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
) -> dict[str, Any]:
    if action == "extend":
        if not allow_oversize:
            raise ValueError(
                "Extending beyond max_pages requires allow_oversize=True. "
                "Use it only when no safe conceptual boundary exists within the target size."
            )
        if session.window_pages >= config.hard_max_pages:
            raise ValueError(
                f"Cannot extend beyond hard_max_pages={config.hard_max_pages}. "
                "Choose a smaller coherent unit."
            )
        session.window_pages = min(
            config.hard_max_pages,
            session.window_pages + config.boundary_window_extension_pages,
        )
        save_session(session, Path(session.output_dir))
        return {
            "status": "extended",
            "window_pages": session.window_pages,
            "message": reason or "Window extended for concept completion.",
        }

    if not element_id:
        raise ValueError("element_id is required for action=cut")

    validate_boundary_reason(reason)

    end_index = ir.index_of(element_id)
    confirmed_topic_boundaries = [
        review
        for review in session.topic_change_reviews.values()
        if review.get("consensus") == "split"
        and session.cursor_index <= int(review.get("boundary_index", -1)) < end_index
    ]
    if confirmed_topic_boundaries and not allow_topic_merge:
        nearest = min(
            confirmed_topic_boundaries,
            key=lambda review: int(review["boundary_index"]),
        )
        raise ValueError(
            "Cut would cross a confirmed topic change before "
            f"{nearest['heading_text']}. Cut at {nearest['boundary_element_id']} "
            "or set allow_topic_merge=True with a specific reason."
        )
    structure = analyze_structure(ir, config)
    _, candidates = candidates_in_word_window(
        ir,
        session.cursor_index,
        session.window_pages * config.words_per_page,
        0,
    )
    normal_page_cap = min(config.max_pages, config.hard_max_pages)
    page_cap = (
        normal_page_cap
        if session.window_pages <= normal_page_cap
        else config.hard_max_pages
    )
    if page_cap:
        candidates = [
            candidate
            for candidate in candidates
            if _within_page_limit(
                ir,
                session.cursor_index,
                candidate,
                structure.element_pages,
                page_cap,
            )
        ]
    allowed = {c.element_id for c in candidates}
    start_page, end_page = page_range_for_elements(
        ir, session.cursor_index, end_index, structure.element_pages
    )
    if (
        start_page is not None
        and end_page is not None
        and end_page - start_page + 1 > config.hard_max_pages
    ):
        raise ValueError(
            f"Boundary would create {end_page - start_page + 1} pages, exceeding "
            f"hard_max_pages={config.hard_max_pages}."
        )
    is_final_element = end_index == len(ir.elements) - 1
    if element_id not in allowed and not is_final_element:
        raise ValueError(
            f"element_id {element_id} is not among safe candidates for the current window"
        )

    if (
        end_index == len(ir.elements) - 1
        and session.boundaries
        and _is_trailing_page_number_range(ir, session.cursor_index, end_index)
    ):
        previous = session.boundaries[-1]
        previous_start = int(previous["start_index"])
        start_page, end_page = page_range_for_elements(
            ir, previous_start, end_index, structure.element_pages
        )
        previous["end_element_id"] = element_id
        previous["end_index"] = end_index
        previous["end_page"] = end_page
        previous["est_pages"] = (
            end_page - start_page + 1
            if start_page is not None and end_page is not None
            else None
        )
        previous["trailing_page_number_merged"] = True
        session.cursor_index = end_index + 1
        session.window_pages = config.boundary_window_pages
        save_session(session, Path(session.output_dir))
        return {"status": "complete", "boundaries": session.boundaries}

    start_page, end_page = page_range_for_elements(
        ir, session.cursor_index, end_index, structure.element_pages
    )
    est_pages = None
    if start_page is not None and end_page is not None:
        est_pages = end_page - start_page + 1

    session.boundaries.append(
        {
            "end_element_id": element_id,
            "end_index": end_index,
            "reason": reason,
            "start_index": session.cursor_index,
            "est_pages": est_pages,
            "start_page": start_page,
            "end_page": end_page,
        }
    )
    session.cursor_index = end_index + 1
    session.window_pages = config.boundary_window_pages
    save_session(session, Path(session.output_dir))

    if session.cursor_index >= len(ir.elements):
        return {"status": "complete", "boundaries": session.boundaries}
    return {"status": "continue", "cursor_index": session.cursor_index}
