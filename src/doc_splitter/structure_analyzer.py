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


def _estimate_page(word_position: int, config: SplitConfig) -> int:
    return max(1, (word_position + config.words_per_page - 1) // config.words_per_page)


def analyze_structure(ir: DocumentIR, config: SplitConfig) -> StructureInfo:
    ir.recompute_word_counts()
    element_pages: dict[str, int] = {}
    roots: list[HeadingNode] = []
    stack: list[HeadingNode] = []

    for el in ir.elements:
        if el.page is not None:
            element_pages[el.id] = el.page
        else:
            prior = el.cumulative_word_count - el.word_count
            element_pages[el.id] = _estimate_page(prior, config)

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