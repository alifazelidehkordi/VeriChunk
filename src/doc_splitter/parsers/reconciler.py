"""Reconcile pymupdf4llm IR with OpenDataLoader layout data."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from doc_splitter.ir.models import BBox, DocumentIR, Element
from doc_splitter.parsers.pdf_opendataloader import LayoutElement


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _match_score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _best_layout_match(
    element: Element,
    layouts: list[LayoutElement],
    used: set[int],
) -> LayoutElement | None:
    target = ""
    if element.type == "table":
        target = " ".join(" ".join(row) for row in element.rows)
    elif element.type == "list":
        target = " ".join(element.items)
    elif element.type == "image":
        target = element.caption or ""
    else:
        target = element.text

    best_idx = -1
    best_score = 0.0
    for i, layout in enumerate(layouts):
        if i in used:
            continue
        layout_text = layout.text
        if layout.rows and element.type == "table":
            layout_text = " ".join(" ".join(r) for r in layout.rows)
        score = _match_score(target, layout_text)
        if element.page and layout.page == element.page:
            score += 0.1
        if score > best_score:
            best_score = score
            best_idx = i

    if best_idx < 0 or best_score < 0.45:
        return None
    used.add(best_idx)
    return layouts[best_idx]


def reconcile_pdf_ir(ir: DocumentIR, layouts: list[LayoutElement]) -> DocumentIR:
    used: set[int] = set()
    notes = list(ir.meta.reconciliation_notes)

    for element in ir.elements:
        match = _best_layout_match(element, layouts, used)
        if match is None:
            continue

        element.page = match.page
        element.bbox = BBox(
            x0=match.x0,
            y0=match.y0,
            x1=match.x1,
            y1=match.y1,
            page=match.page,
        )

        if element.type == "table" and match.rows:
            if len(match.rows) != len(element.rows) or any(
                len(a) != len(b) for a, b in zip(element.rows, match.rows, strict=False)
            ):
                notes.append(
                    f"Table {element.id}: structure reconciled from OpenDataLoader "
                    f"({len(element.rows)}x{len(element.rows[0]) if element.rows else 0} "
                    f"-> {len(match.rows)}x{len(match.rows[0]) if match.rows else 0})"
                )
                element.rows = match.rows
                element.compute_word_count()

    ir.meta.reconciliation_notes = notes
    ir.recompute_word_counts()
    return ir