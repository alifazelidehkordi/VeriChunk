"""Layer 1: structurally safe boundary cut points."""

from __future__ import annotations

from dataclasses import dataclass

from doc_splitter.ir.models import DocumentIR, Element


@dataclass
class SafeCandidate:
    element_id: str
    index: int
    after_type: str
    snippet: str
    cumulative_word_count: int


def _snippet(el: Element, max_len: int = 120) -> str:
    if el.type == "heading":
        text = el.text
    elif el.type == "table":
        text = " | ".join(" ".join(row) for row in el.rows[:2])
    elif el.type == "list":
        text = "; ".join(el.items[:3])
    elif el.type == "image":
        text = el.caption or el.ref or ""
    else:
        text = el.text
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def find_safe_candidates(
    ir: DocumentIR,
    start_index: int,
    end_index: int,
) -> list[SafeCandidate]:
    """Return indices where a cut AFTER this element is structurally safe."""
    candidates: list[SafeCandidate] = []
    end_index = min(end_index, len(ir.elements) - 1)

    for i in range(start_index, end_index + 1):
        el = ir.elements[i]
        if el.type not in {"paragraph", "table", "list", "heading", "image"}:
            continue
        candidates.append(
            SafeCandidate(
                element_id=el.id,
                index=i,
                after_type=el.type,
                snippet=_snippet(el),
                cumulative_word_count=el.cumulative_word_count,
            )
        )
    return candidates


def candidates_in_word_window(
    ir: DocumentIR,
    cursor_index: int,
    window_words: int,
    min_words: int,
) -> tuple[int, list[SafeCandidate]]:
    """Return window end index and safe candidates within the word window."""
    if cursor_index >= len(ir.elements):
        return cursor_index, []

    start_words = ir.elements[cursor_index - 1].cumulative_word_count if cursor_index > 0 else 0
    target_words = start_words + window_words
    end_index = cursor_index

    for i in range(cursor_index, len(ir.elements)):
        end_index = i
        if ir.elements[i].cumulative_word_count >= target_words:
            break

    candidates = find_safe_candidates(ir, cursor_index, end_index)
    if min_words > 0:
        min_target = start_words + min_words
        candidates = [c for c in candidates if c.cumulative_word_count >= min_target]

    return end_index, candidates
