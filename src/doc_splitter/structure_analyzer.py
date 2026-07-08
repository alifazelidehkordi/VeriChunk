"""Build heading hierarchy and page estimates from IR."""

from __future__ import annotations

from dataclasses import dataclass, field

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, Element


@dataclass
class HeadingNode:
    element_id: str
    level: int
    title: str
    children: list[HeadingNode] = field(default_factory=list)


@dataclass
class StructureInfo:
    heading_tree: list[HeadingNode]
    element_pages: dict[str, int]


@dataclass
class ChunkPageRange:
    start_page: int
    end_page: int
    overlap_prev: list[int]
    overlap_next: list[int]
    source_pages: list[int]
    pdf_pages: list[int]


def _estimate_page(word_position: int, config: SplitConfig) -> int:
    return max(1, (word_position + config.words_per_page - 1) // config.words_per_page)


def element_page_number(el: Element, config: SplitConfig) -> int | None:
    page = el.resolved_page_number()
    if page is not None:
        return page
    prior = el.cumulative_word_count - el.word_count
    return _estimate_page(prior, config)


def analyze_structure(ir: DocumentIR, config: SplitConfig) -> StructureInfo:
    ir.recompute_word_counts()
    element_pages: dict[str, int] = {}
    roots: list[HeadingNode] = []
    stack: list[HeadingNode] = []

    for el in ir.elements:
        page = element_page_number(el, config)
        if page is not None:
            element_pages[el.id] = page

        if el.type != "heading" or el.level is None:
            continue

        node = HeadingNode(element_id=el.id, level=el.level, title=el.text)
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    return StructureInfo(heading_tree=roots, element_pages=element_pages)


def active_h1_for_element(ir: DocumentIR, element_index: int) -> str | None:
    current: str | None = None
    for i, el in enumerate(ir.elements):
        if i > element_index:
            break
        if el.type == "heading" and el.level == 1:
            current = el.text
    return current


def page_range_for_elements(
    ir: DocumentIR,
    start_idx: int,
    end_idx: int,
    element_pages: dict[str, int],
) -> tuple[int | None, int | None]:
    pages = []
    for el in ir.elements[start_idx : end_idx + 1]:
        page = element_pages.get(el.id)
        if page is not None:
            pages.append(page)
    if not pages:
        return None, None
    return min(pages), max(pages)


def _pages_for_indices(
    ir: DocumentIR,
    start_idx: int,
    end_idx: int,
    element_pages: dict[str, int],
) -> list[int]:
    pages: set[int] = set()
    for el in ir.elements[start_idx : end_idx + 1]:
        page = element_pages.get(el.id)
        if page is not None:
            pages.add(page)
    return sorted(pages)


def _boundary_page_shared(
    ir: DocumentIR,
    end_idx: int,
    element_pages: dict[str, int],
) -> int | None:
    if end_idx >= len(ir.elements) - 1:
        return None
    end_page = element_pages.get(ir.elements[end_idx].id)
    next_page = element_pages.get(ir.elements[end_idx + 1].id)
    if end_page is not None and next_page == end_page:
        return end_page
    return None


def compute_chunk_page_ranges(
    ir: DocumentIR,
    ranges: list[tuple[int, int]],
    config: SplitConfig,
) -> list[ChunkPageRange]:
    structure = analyze_structure(ir, config)
    element_pages = structure.element_pages
    overlap_n = max(0, config.overlap_boundary_pages)
    result: list[ChunkPageRange] = []

    for i, (start_idx, end_idx) in enumerate(ranges):
        source_pages = _pages_for_indices(ir, start_idx, end_idx, element_pages)
        if not source_pages:
            result.append(
                ChunkPageRange(0, 0, [], [], [], [])
            )
            continue

        start_page = source_pages[0]
        end_page = source_pages[-1]
        overlap_prev: list[int] = []
        overlap_next: list[int] = []

        shared = _boundary_page_shared(ir, end_idx, element_pages)
        if shared is not None:
            overlap_next.append(shared)

        if i > 0:
            prev_end = ranges[i - 1][1]
            prev_shared = _boundary_page_shared(ir, prev_end, element_pages)
            if prev_shared is not None and prev_shared not in overlap_prev:
                overlap_prev.append(prev_shared)

        pdf_pages = set(range(start_page, end_page + 1))
        for p in overlap_prev:
            pdf_pages.add(p)
            for offset in range(1, overlap_n + 1):
                if p - offset >= 1:
                    pdf_pages.add(p - offset)
        for p in overlap_next:
            pdf_pages.add(p)
            for offset in range(1, overlap_n + 1):
                pdf_pages.add(p + offset)

        if i + 1 < len(ranges):
            next_start_pages = _pages_for_indices(
                ir, ranges[i + 1][0], ranges[i + 1][0], element_pages
            )
            if next_start_pages:
                pdf_pages.add(next_start_pages[0])

        result.append(
            ChunkPageRange(
                start_page=start_page,
                end_page=end_page,
                overlap_prev=sorted(overlap_prev),
                overlap_next=sorted(overlap_next),
                source_pages=source_pages,
                pdf_pages=sorted(pdf_pages),
            )
        )

    return result