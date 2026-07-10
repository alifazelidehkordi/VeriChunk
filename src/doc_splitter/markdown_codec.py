"""Canonical Markdown rendering and integrity markers for chunk files."""

from __future__ import annotations

import re
from dataclasses import dataclass

from doc_splitter.ir.models import Element

ELEMENTS_START = "<!-- doc-splitter-elements-start -->"
ELEMENTS_END = "<!-- doc-splitter-elements-end -->"
_MARKER_RE = re.compile(
    r"^<!-- doc-splitter-element: (?P<id>[A-Za-z0-9_.:-]+) \| type: (?P<type>[a-z]+) -->$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ParsedMarkdownElement:
    element_id: str
    element_type: str
    body: str


def normalize_markdown_block(value: str) -> str:
    """Normalize line endings and surrounding blank lines, not user content."""
    return value.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def render_element(element: Element) -> str:
    if element.type == "heading":
        return f"{'#' * (element.level or 1)} {element.text}"
    if element.type == "paragraph":
        return element.text
    if element.type == "list":
        return "\n".join(f"- {item}" for item in element.items)
    if element.type == "table":
        if not element.rows:
            return ""
        lines: list[str] = []
        for index, row in enumerate(element.rows):
            lines.append("| " + " | ".join(row) + " |")
            if index == 0:
                lines.append("| " + " | ".join("---" for _ in row) + " |")
        return "\n".join(lines)
    if element.type == "image":
        return f"![{element.caption or ''}]({element.ref})"
    return ""


def render_marked_element(element: Element) -> str:
    marker = f"<!-- doc-splitter-element: {element.id} | type: {element.type} -->"
    body = render_element(element)
    return marker if not body else f"{marker}\n{body}"


def parse_marked_elements(content: str) -> tuple[list[ParsedMarkdownElement], list[str]]:
    """Read actual element blocks from a generated Markdown chunk.

    The title/navigation preamble is intentionally outside the protected region.
    All source-derived document content must be inside exactly one marked region.
    """
    errors: list[str] = []
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    start_count = normalized.count(ELEMENTS_START)
    end_count = normalized.count(ELEMENTS_END)
    if start_count != 1:
        errors.append(f"Expected one element-region start marker, found {start_count}")
    if end_count != 1:
        errors.append(f"Expected one element-region end marker, found {end_count}")
    if errors:
        return [], errors

    start = normalized.index(ELEMENTS_START) + len(ELEMENTS_START)
    end = normalized.index(ELEMENTS_END)
    if end < start:
        return [], ["Element-region end marker appears before start marker"]

    region = normalized[start:end]
    trailer = normalized[end + len(ELEMENTS_END) :]
    if trailer.strip():
        errors.append("Unexpected content appears after the protected element region")

    matches = list(_MARKER_RE.finditer(region))
    if not matches:
        if region.strip():
            errors.append("Protected element region contains content without element markers")
        return [], errors

    prefix = region[: matches[0].start()]
    if prefix.strip():
        errors.append("Unexpected content appears before the first element marker")

    parsed: list[ParsedMarkdownElement] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(region)
        body = normalize_markdown_block(region[body_start:body_end])
        parsed.append(
            ParsedMarkdownElement(
                element_id=match.group("id"),
                element_type=match.group("type"),
                body=body,
            )
        )
    return parsed, errors


def rendered_word_count(body: str, element_type: str) -> int:
    """Count words from the actual rendered block using IR-compatible rules."""
    if element_type == "heading":
        text = re.sub(r"^#{1,6}\s+", "", body.strip())
    elif element_type == "list":
        text = " ".join(
            re.sub(r"^\s*[-*+]\s+", "", line) for line in body.splitlines() if line.strip()
        )
    elif element_type == "table":
        cells: list[str] = []
        for line in body.splitlines():
            if not line.strip().startswith("|"):
                continue
            row = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if row and all(cell and set(cell) <= {"-", ":"} for cell in row):
                continue
            cells.extend(row)
        text = " ".join(cells)
    elif element_type == "image":
        match = re.match(r"^!\[([^\]]*)\]\([^)]+\)$", body.strip(), re.DOTALL)
        text = match.group(1) if match else body
    else:
        text = body
    return len(text.split()) if text else 0
