"""Semantic topic-change review tasks for parallel agent work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, Element
from doc_splitter.semantic import build_semantic_map, find_semantic_change_points


@dataclass(frozen=True)
class TopicChangeCandidate:
    review_id: str
    heading_element_id: str
    heading_index: int
    heading_text: str
    boundary_element_id: str
    boundary_index: int
    boundary_page: int | None
    heading_page: int | None
    candidate_kind: str = "semantic_shift"
    semantic_score: float = 0.0
    lexical_discontinuity: float = 0.0
    before_element_ids: tuple[str, ...] = ()
    after_element_ids: tuple[str, ...] = ()
    shared_terms: tuple[str, ...] = ()
    before_terms: tuple[str, ...] = ()
    after_terms: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()


def _text_excerpt(elements: list[Element], limit: int) -> str:
    parts: list[str] = []
    size = 0
    for el in elements:
        if el.type in {"heading", "paragraph"}:
            value = el.text
        elif el.type == "list":
            value = "; ".join(el.items)
        elif el.type == "table":
            value = " | ".join(" ".join(row) for row in el.rows)
        else:
            value = el.caption or el.ref or ""
        value = " ".join(value.split())
        if not value:
            continue
        prefix = f"[{el.id}] "
        remaining = limit - size
        if remaining <= len(prefix):
            break
        rendered = prefix + value[: max(0, remaining - len(prefix))]
        parts.append(rendered)
        size += len(rendered)
        if size >= limit:
            break
    return "\n\n".join(parts)


def find_topic_change_candidates(
    ir: DocumentIR,
    config: SplitConfig,
) -> list[TopicChangeCandidate]:
    """Find heading and heading-free semantic change points.

    This function deliberately returns candidates, not final boundaries. Every
    result must still be resolved by independent review consensus.
    """
    candidates: list[TopicChangeCandidate] = []
    for score in find_semantic_change_points(ir, config):
        candidates.append(
            TopicChangeCandidate(
                review_id=f"topic-change:{score.marker_element_id}",
                heading_element_id=score.marker_element_id,
                heading_index=score.marker_index,
                heading_text=score.marker_text,
                boundary_element_id=score.boundary_element_id,
                boundary_index=score.boundary_index,
                boundary_page=score.boundary_page,
                heading_page=score.marker_page,
                candidate_kind=score.marker_kind,
                semantic_score=score.score,
                lexical_discontinuity=score.lexical_discontinuity,
                before_element_ids=score.before_element_ids,
                after_element_ids=score.after_element_ids,
                shared_terms=score.shared_terms,
                before_terms=score.before_terms,
                after_terms=score.after_terms,
                signals=score.signals,
            )
        )
    return candidates


def _review_role(slot: int) -> str:
    roles = ("transition_reviewer", "continuity_reviewer", "adjudicator")
    return roles[(slot - 1) % len(roles)]


def build_topic_change_review_batch(
    ir: DocumentIR,
    config: SplitConfig,
    workers: int,
) -> dict[str, Any]:
    """Return review tasks distributed across actual worker slots.

    ``workers`` controls concurrency. ``topic_change_reviewers`` controls how
    many independent verdicts each boundary receives.
    """
    workers = max(1, workers)
    candidates = find_topic_change_candidates(ir, config)
    semantic_map = build_semantic_map(ir, config)
    outline = semantic_map["outline"]
    tasks: list[dict[str, Any]] = []
    for candidate in candidates:
        before_indices = [ir.index_of(element_id) for element_id in candidate.before_element_ids]
        after_indices = [ir.index_of(element_id) for element_id in candidate.after_element_ids]
        before_elements = [ir.elements[index] for index in before_indices]
        after_elements = [ir.elements[index] for index in after_indices]
        nearby_outline = sorted(
            outline,
            key=lambda item: abs(int(item["index"]) - candidate.boundary_index),
        )[:6]
        nearby_outline.sort(key=lambda item: int(item["index"]))
        base_task = {
            "review_id": candidate.review_id,
            "document_summary": semantic_map["document"],
            "nearby_document_outline": nearby_outline,
            "proposed_boundary_element_id": candidate.boundary_element_id,
            "proposed_boundary_index": candidate.boundary_index,
            "topic_marker_element_id": candidate.heading_element_id,
            "topic_marker": candidate.heading_text,
            "candidate_kind": candidate.candidate_kind,
            "semantic_score": candidate.semantic_score,
            "lexical_discontinuity": candidate.lexical_discontinuity,
            "signals": list(candidate.signals),
            "shared_terms": list(candidate.shared_terms),
            "before_terms": list(candidate.before_terms),
            "after_terms": list(candidate.after_terms),
            "before_element_ids": list(candidate.before_element_ids),
            "after_element_ids": list(candidate.after_element_ids),
            "boundary_page": candidate.boundary_page,
            "topic_marker_page": candidate.heading_page,
            "before_context": _text_excerpt(before_elements, config.semantic_context_chars),
            "after_context": _text_excerpt(after_elements, config.semantic_context_chars),
            "instructions": (
                "Decide whether the learning objective after the proposed boundary "
                "is independently studyable from the material before it. Topic change "
                "overrides minimum chunk size. Return split for a genuine objective or "
                "domain change; return merge for an example, continuation, application, "
                "or subtopic of the same objective. Cite element IDs from both sides."
            ),
        }
        for reviewer_slot in range(1, config.topic_change_reviewers + 1):
            tasks.append(
                {
                    **base_task,
                    "reviewer_slot": reviewer_slot,
                    "review_role": _review_role(reviewer_slot),
                }
            )

    batches = [[] for _ in range(min(workers, len(tasks)))] if tasks else []
    for index, task in enumerate(tasks):
        batches[index % len(batches)].append(task)

    return {
        "status": "needs_parallel_topic_review" if tasks else "no_topic_candidates",
        "recommended_workers": len(batches),
        "reviewers_per_task": config.topic_change_reviewers if tasks else 0,
        "minimum_consensus_votes": config.topic_change_min_votes,
        "total_boundaries": len(candidates),
        "total_tasks": len(tasks),
        "batches": batches,
        "response_schema": {
            "review_id": "Stable review ID from the task",
            "reviewer_id": "Stable identifier for the independent reviewing agent",
            "decision": "split | merge",
            "confidence": "Number from 0 to 1",
            "reason": "Specific semantic justification",
            "evidence_before": "One or more element IDs before the boundary",
            "evidence_after": "One or more element IDs after the boundary",
        },
    }
