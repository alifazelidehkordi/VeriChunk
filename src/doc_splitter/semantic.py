"""Lightweight semantic change-point detection over document IR.

The detector is intentionally provider-independent. It does not make the final
split decision; it finds plausible boundaries that independent reviewers must
resolve. Unlike the old heading-only pass, every structurally safe transition is
scored using context on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, Element
from doc_splitter.section_titles import looks_like_section_title, normalize_title_text
from doc_splitter.structure_analyzer import analyze_structure

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_BOLD_SPAN_RE = re.compile(r"\*\*([^*]+)\*\*")

# Function words and generic document vocabulary otherwise create misleading
# continuity between unrelated subjects. Persian entries cover common connective
# words without attempting language-specific stemming.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "from",
    "with", "by", "as", "at", "is", "are", "was", "were", "be", "been", "this",
    "that", "these", "those", "it", "its", "into", "also", "can", "may", "will",
    "would", "should", "through", "between", "after", "before", "during", "using",
    "used", "page", "section", "chapter", "topic", "example", "study", "unit",
    "و", "در", "به", "از", "که", "این", "آن", "با", "برای", "یا", "یک", "را",
    "است", "هست", "شد", "شود", "می", "های", "ها", "بر", "تا", "اما", "نیز",
    "بخش", "فصل", "موضوع", "مثال", "صفحه",
}

_GENERIC_CONTINUATION_HEADINGS = {
    "worked example", "example", "examples", "case example", "practice",
    "exercise", "exercises", "summary", "review", "key points", "discussion",
    "application", "applications", "notes", "note", "continued", "continuation",
    "مثال", "مثال حل شده", "تمرین", "خلاصه", "مرور", "نکات کلیدی", "ادامه",
}

_CONCLUSION_MARKERS = (
    "this concludes", "in conclusion", "to summarize", "therefore", "finally",
    "در نتیجه", "در پایان", "جمع بندی", "خلاصه",
)

_NEW_TOPIC_MARKERS = (
    "a valid", "we now turn", "next topic", "in contrast", "separately",
    "موضوع بعد", "در ادامه به", "از سوی دیگر",
)


@dataclass(frozen=True)
class SemanticBoundaryScore:
    boundary_index: int
    boundary_element_id: str
    marker_index: int
    marker_element_id: str
    marker_text: str
    marker_kind: str
    score: float
    lexical_discontinuity: float
    shared_terms: tuple[str, ...]
    before_terms: tuple[str, ...]
    after_terms: tuple[str, ...]
    before_element_ids: tuple[str, ...]
    after_element_ids: tuple[str, ...]
    boundary_page: int | None
    marker_page: int | None
    signals: tuple[str, ...]


def element_text(el: Element) -> str:
    if el.type in {"heading", "paragraph"}:
        return el.text
    if el.type == "list":
        return " ".join(el.items)
    if el.type == "table":
        return " ".join(cell for row in el.rows for cell in row)
    return " ".join(part for part in (el.caption, el.ref) if part)


def _normalize_token(token: str) -> str:
    token = token.casefold().strip("‌-")
    # Conservative English morphology normalization improves continuity without
    # requiring a heavyweight NLP dependency.
    if token.isascii() and len(token) > 5:
        for suffix in ("ingly", "edly", "ation", "ments", "ment", "ness", "ing", "ed", "es", "s"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                token = token[: -len(suffix)]
                break
    return token


def semantic_tokens(text: str) -> set[str]:
    tokens = {_normalize_token(match.group(0)) for match in _WORD_RE.finditer(text)}
    return {token for token in tokens if len(token) >= 3 and token not in _STOPWORDS}


def _uppercase_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum(char.isupper() for char in letters) / len(letters)


def major_title(text: str, level: int | None) -> str | None:
    title = normalize_title_text(text)
    if not title:
        return None
    normalized = title.casefold()
    if normalized in _GENERIC_CONTINUATION_HEADINGS:
        return None
    if 5 <= len(title) <= 320 and _uppercase_ratio(title) >= 0.6:
        return title
    if not looks_like_section_title(title):
        return None
    if level is not None and level <= 2:
        return title
    if _uppercase_ratio(title) >= 0.6:
        return title
    return None


def topic_marker_text(el: Element) -> tuple[str | None, str]:
    if el.type == "heading":
        title = major_title(el.text, el.level)
        if title:
            return title, "major_heading"
        normalized = normalize_title_text(el.text)
        return (normalized or None), "subheading"
    if el.type == "paragraph":
        for match in reversed(_BOLD_SPAN_RE.findall(el.text)):
            title = major_title(match, None)
            if title:
                return title, "bold_major_heading"
    return None, "semantic_shift"


def _meaningful_indices(ir: DocumentIR, start: int, stop: int, step: int, limit: int) -> list[int]:
    indices: list[int] = []
    i = start
    while (i >= stop if step < 0 else i <= stop) and len(indices) < limit:
        if semantic_tokens(element_text(ir.elements[i])):
            indices.append(i)
        i += step
    if step < 0:
        indices.reverse()
    return indices


def _context_indices(ir: DocumentIR, boundary_index: int, count: int) -> tuple[list[int], list[int]]:
    before = _meaningful_indices(ir, boundary_index, 0, -1, count)
    after = _meaningful_indices(ir, boundary_index + 1, len(ir.elements) - 1, 1, count)
    return before, after


def _context_tokens(ir: DocumentIR, indices: Iterable[int]) -> set[str]:
    result: set[str] = set()
    for index in indices:
        result.update(semantic_tokens(element_text(ir.elements[index])))
    return result


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _containment(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _term_sample(terms: set[str], limit: int = 8) -> tuple[str, ...]:
    return tuple(sorted(terms, key=lambda value: (-len(value), value))[:limit])


def _score_boundary(
    ir: DocumentIR,
    boundary_index: int,
    config: SplitConfig,
    element_pages: dict[str, int],
) -> SemanticBoundaryScore | None:
    if boundary_index < 0 or boundary_index >= len(ir.elements) - 1:
        return None
    before_indices, after_indices = _context_indices(
        ir, boundary_index, config.semantic_context_elements
    )
    if len(before_indices) < 3 or len(after_indices) < 3:
        # Major headings near document edges remain important even with limited
        # context; ordinary lexical shifts require enough evidence on both sides.
        marker_text, marker_kind = topic_marker_text(ir.elements[boundary_index + 1])
        if marker_kind not in {"major_heading", "bold_major_heading"}:
            return None
    else:
        marker_text, marker_kind = topic_marker_text(ir.elements[boundary_index + 1])

    before_tokens = _context_tokens(ir, before_indices)
    after_tokens = _context_tokens(ir, after_indices)
    if not before_tokens or not after_tokens:
        return None

    jaccard = _jaccard(before_tokens, after_tokens)
    containment = _containment(before_tokens, after_tokens)
    # Containment catches continuity when one side uses a smaller vocabulary.
    continuity = max(jaccard, containment * 0.72)
    discontinuity = max(0.0, min(1.0, 1.0 - continuity))

    before_text = " ".join(element_text(ir.elements[i]) for i in before_indices).casefold()
    after_text = " ".join(element_text(ir.elements[i]) for i in after_indices).casefold()
    signals: list[str] = []

    heading_bonus = 0.0
    if marker_kind in {"major_heading", "bold_major_heading"}:
        heading_bonus = 0.58
        signals.append(marker_kind)
    elif marker_kind == "subheading":
        normalized = (marker_text or "").casefold()
        if normalized in _GENERIC_CONTINUATION_HEADINGS:
            signals.append("generic_continuation_heading")
        else:
            heading_bonus = 0.12
            signals.append("structural_subheading")

    conclusion_bonus = 0.08 if any(marker in before_text for marker in _CONCLUSION_MARKERS) else 0.0
    introduction_bonus = 0.06 if any(marker in after_text for marker in _NEW_TOPIC_MARKERS) else 0.0
    if conclusion_bonus:
        signals.append("preceding_conclusion")
    if introduction_bonus:
        signals.append("new_topic_language")

    if heading_bonus >= 0.5:
        score = heading_bonus + 0.34 * discontinuity + conclusion_bonus
    else:
        score = 0.82 * discontinuity + heading_bonus + conclusion_bonus + introduction_bonus

    if "generic_continuation_heading" in signals:
        score -= 0.38
    shared = before_tokens & after_tokens
    if len(shared) >= 3:
        score -= min(0.16, 0.035 * len(shared))
        signals.append("shared_topic_terms")

    score = max(0.0, min(1.0, score))
    marker = ir.elements[boundary_index + 1]
    boundary = ir.elements[boundary_index]
    return SemanticBoundaryScore(
        boundary_index=boundary_index,
        boundary_element_id=boundary.id,
        marker_index=boundary_index + 1,
        marker_element_id=marker.id,
        marker_text=marker_text or element_text(marker)[:160],
        marker_kind=marker_kind,
        score=round(score, 4),
        lexical_discontinuity=round(discontinuity, 4),
        shared_terms=_term_sample(shared),
        before_terms=_term_sample(before_tokens - shared),
        after_terms=_term_sample(after_tokens - shared),
        before_element_ids=tuple(ir.elements[i].id for i in before_indices),
        after_element_ids=tuple(ir.elements[i].id for i in after_indices),
        boundary_page=element_pages.get(boundary.id),
        marker_page=element_pages.get(marker.id),
        signals=tuple(signals),
    )


def score_semantic_boundaries(ir: DocumentIR, config: SplitConfig) -> list[SemanticBoundaryScore]:
    """Score every transition with enough semantic context."""
    element_pages = analyze_structure(ir, config).element_pages
    return [
        score
        for index in range(len(ir.elements) - 1)
        if (score := _score_boundary(ir, index, config, element_pages)) is not None
    ]


def find_semantic_change_points(ir: DocumentIR, config: SplitConfig) -> list[SemanticBoundaryScore]:
    """Return high-value local maxima for independent review.

    Non-maximum suppression prevents a single topic transition from producing a
    cluster of near-duplicate review tasks.
    """
    scored = score_semantic_boundaries(ir, config)
    by_index = {item.boundary_index: item for item in scored}
    eligible: list[SemanticBoundaryScore] = []
    for item in scored:
        is_major = item.marker_kind in {"major_heading", "bold_major_heading"}
        if item.score < config.topic_change_score_threshold:
            continue
        if not is_major:
            # Heading-free shifts need a strong, locally prominent discontinuity
            # so ordinary paragraph-to-paragraph vocabulary variation does not
            # flood the review queue.
            if item.score < max(config.topic_change_score_threshold, 0.82):
                continue
            neighbors = [
                by_index[index].score
                for index in (item.boundary_index - 1, item.boundary_index + 1)
                if index in by_index
            ]
            if neighbors and item.score < max(neighbors):
                continue
            if neighbors and item.score - (sum(neighbors) / len(neighbors)) < 0.03:
                continue
        eligible.append(item)
    selected: list[SemanticBoundaryScore] = []
    for candidate in sorted(
        eligible,
        key=lambda item: (
            item.marker_kind in {"major_heading", "bold_major_heading"},
            item.score,
        ),
        reverse=True,
    ):
        if any(
            abs(candidate.boundary_index - existing.boundary_index)
            <= config.semantic_nms_radius
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item.boundary_index)


def build_semantic_map(ir: DocumentIR, config: SplitConfig) -> dict:
    """Build a compact document-wide map for reviewer orientation.

    Reviewers still receive full local evidence around each boundary, while this
    map gives them the surrounding outline and all detected change points without
    forcing the raw document into every task prompt.
    """
    outline = []
    structure = analyze_structure(ir, config)
    for index, element in enumerate(ir.elements):
        if element.type != "heading":
            continue
        outline.append(
            {
                "element_id": element.id,
                "index": index,
                "page": structure.element_pages.get(element.id),
                "level": element.level,
                "title": normalize_title_text(element.text),
            }
        )
    change_points = find_semantic_change_points(ir, config)
    return {
        "schema_version": 1,
        "document": {
            "source_file": ir.meta.source_file,
            "element_count": len(ir.elements),
            "word_count": ir.meta.total_word_count,
            "estimated_total_pages": ir.meta.estimated_total_pages,
        },
        "outline": outline,
        "change_candidates": [
            {
                "review_id": f"topic-change:{item.marker_element_id}",
                "boundary_element_id": item.boundary_element_id,
                "boundary_index": item.boundary_index,
                "marker_element_id": item.marker_element_id,
                "marker_text": item.marker_text,
                "candidate_kind": item.marker_kind,
                "score": item.score,
                "signals": list(item.signals),
                "before_terms": list(item.before_terms),
                "after_terms": list(item.after_terms),
                "shared_terms": list(item.shared_terms),
            }
            for item in change_points
        ],
    }
