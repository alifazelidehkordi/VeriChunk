"""Independent topic-change review tasks for parallel host-agent work."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from doc_splitter.boundary.safe_candidates import find_safe_candidates
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, Element
from doc_splitter.section_titles import looks_like_section_title, normalize_title_text
from doc_splitter.structure_analyzer import analyze_structure


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


_BOLD_SPAN_RE = re.compile(r"\*\*([^*]+)\*\*")


def _uppercase_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isupper() for char in letters) / len(letters)


def _major_title(text: str, level: int | None) -> str | None:
    title = normalize_title_text(text)
    if not title:
        return None
    # Uppercase headings are the most reliable chapter signal in PDF extraction,
    # including long headings that intentionally exceed section-title heuristics.
    if 5 <= len(title) <= 320 and _uppercase_ratio(title) >= 0.6:
        return title
    if not looks_like_section_title(title):
        return None
    # Level 1/2 titles are document-level structure. PDFs often label major
    # chapters as level 3, where all-caps is the more reliable signal.
    if level is not None and level <= 2:
        return title
    if _uppercase_ratio(title) >= 0.6:
        return title
    return None


def _topic_marker_text(el: Element) -> str | None:
    if el.type == "heading":
        return _major_title(el.text, el.level)
    if el.type != "paragraph":
        return None
    # Some PDF extractors append a bold chapter title to the preceding line.
    for match in reversed(_BOLD_SPAN_RE.findall(el.text)):
        title = _major_title(match, None)
        if title:
            return title
    return None


def _text_excerpt(elements: list[Element], limit: int = 900) -> str:
    parts: list[str] = []
    for el in elements:
        if el.type == "heading":
            value = el.text
        elif el.type == "paragraph":
            value = el.text
        elif el.type == "list":
            value = "; ".join(el.items[:4])
        elif el.type == "table":
            value = " | ".join(" ".join(row) for row in el.rows[:2])
        else:
            value = el.caption or el.ref or ""
        value = " ".join(value.split())
        if value:
            parts.append(value)
        if sum(len(part) for part in parts) >= limit:
            break
    text = "\n\n".join(parts)
    return text[:limit]


def find_topic_change_candidates(
    ir: DocumentIR,
    config: SplitConfig,
) -> list[TopicChangeCandidate]:
    """Find likely major topic changes and the safe cut immediately before each."""
    structure = analyze_structure(ir, config)
    candidates: list[TopicChangeCandidate] = []
    seen_boundaries: set[int] = set()

    for heading_index, el in enumerate(ir.elements):
        heading_text = _topic_marker_text(el)
        if heading_index == 0 or not heading_text:
            continue
        safe_before = find_safe_candidates(ir, 0, heading_index - 1)
        if not safe_before:
            continue
        boundary = safe_before[-1]
        if boundary.index in seen_boundaries:
            continue
        seen_boundaries.add(boundary.index)
        candidates.append(
            TopicChangeCandidate(
                review_id=f"topic-change:{el.id}",
                heading_element_id=el.id,
                heading_index=heading_index,
                heading_text=heading_text,
                boundary_element_id=boundary.element_id,
                boundary_index=boundary.index,
                boundary_page=structure.element_pages.get(boundary.element_id),
                heading_page=structure.element_pages.get(el.id),
            )
        )
    return candidates


def build_topic_change_review_batch(
    ir: DocumentIR,
    config: SplitConfig,
    workers: int,
) -> dict[str, Any]:
    """Return independent review tasks that a host can send to agents in parallel."""
    workers = max(1, workers)
    candidates = find_topic_change_candidates(ir, config)
    tasks: list[dict[str, Any]] = []
    for candidate in candidates:
        before_start = max(0, candidate.boundary_index - 8)
        after_end = min(len(ir.elements), candidate.heading_index + 9)
        tasks.append(
            {
                "review_id": candidate.review_id,
                "proposed_boundary_element_id": candidate.boundary_element_id,
                "proposed_boundary_index": candidate.boundary_index,
                "topic_marker_element_id": candidate.heading_element_id,
                "topic_marker": candidate.heading_text,
                "boundary_page": candidate.boundary_page,
                "topic_marker_page": candidate.heading_page,
                "before_context": _text_excerpt(
                    ir.elements[before_start : candidate.boundary_index + 1]
                ),
                "after_context": _text_excerpt(
                    ir.elements[candidate.heading_index : after_end]
                ),
                "instructions": (
                    "Decide whether the content after the marker begins an independent "
                    "study topic. Return decision='split' when it does; use 'merge' only "
                    "when the marker is a true subtopic of the same session. Include a "
                    "specific semantic reason."
                ),
            }
        )

    batches = [[] for _ in range(workers)] if tasks else []
    # ``workers`` controls concurrency, not vote count. Even one worker must
    # receive every independent reviewer slot required for consensus.
    reviewers_per_task = config.topic_change_min_votes if tasks else 0
    for index, task in enumerate(tasks):
        for reviewer_slot in range(reviewers_per_task):
            if batches:
                batches[(index + reviewer_slot) % len(batches)].append(
                    {**task, "reviewer_slot": reviewer_slot + 1}
                )

    return {
        "status": "needs_parallel_topic_review",
        "recommended_workers": len(batches),
        "reviewers_per_task": reviewers_per_task,
        "total_tasks": len(tasks),
        "batches": batches,
        "response_schema": {
            "review_id": "topic-change:<heading-element-id>",
            "reviewer_id": "Stable identifier for the independent reviewing agent",
            "decision": "split | merge",
            "reason": "Specific semantic justification",
        },
    }
