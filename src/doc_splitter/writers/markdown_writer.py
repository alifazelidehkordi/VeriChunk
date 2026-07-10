"""Write semantic-named Markdown chunk files."""

from __future__ import annotations

from pathlib import Path

from doc_splitter.ir.models import DocumentIR
from doc_splitter.markdown_codec import (
    ELEMENTS_END,
    ELEMENTS_START,
    render_marked_element,
)
from doc_splitter.storage import atomic_write_text
from doc_splitter.structure_analyzer import ChunkPageRange


def extract_marked_section(content: str) -> str | None:
    """Return the protected element section, preserving its exact body bytes."""
    start = content.find(ELEMENTS_START)
    end = content.find(ELEMENTS_END, start + len(ELEMENTS_START))
    if start < 0 or end < 0:
        return None
    return content[start : end + len(ELEMENTS_END)]


def render_markdown_chunk(
    ir: DocumentIR,
    *,
    start_idx: int,
    end_idx: int,
    page_range: ChunkPageRange,
    meta: dict[str, str],
    chunk_number: int,
    total_chunks: int,
    prev_name: str | None,
    next_name: str | None,
    marked_section: str | None = None,
) -> str:
    chunk_name = meta["file"]
    page_label = "~"
    if page_range.source_pages:
        page_label = f"~{page_range.start_page}-{page_range.end_page}"

    if marked_section is None:
        body_parts = [render_marked_element(el) for el in ir.elements[start_idx : end_idx + 1]]
        body = "\n\n".join(body_parts)
        marked_section = f"{ELEMENTS_START}\n\n{body}\n\n{ELEMENTS_END}"

    title = meta.get("title", "")
    header_lines = [
        f"<!-- section: {chunk_number:02d}/{total_chunks} | file: {chunk_name} | source: {ir.meta.source_file} | pages: {page_label} -->",
    ]
    if prev_name:
        header_lines.append(f"<!-- continues-from: {prev_name} -->")
    if next_name:
        header_lines.append(f"<!-- continues-to: {next_name} -->")

    content = "\n".join(header_lines) + "\n\n"
    if title:
        content += f"## {title}\n\n"
    return content + marked_section.rstrip() + "\n"


def write_markdown_chunks(
    ir: DocumentIR,
    ranges: list[tuple[int, int]],
    page_ranges: list[ChunkPageRange],
    names: list[dict[str, str]],
    output_dir: Path,
    total_chunks: int,
) -> None:
    id_to_name = {n["id"]: n for n in names}
    for i, (start_idx, end_idx) in enumerate(ranges, start=1):
        meta = id_to_name[str(i)]
        prev_name = id_to_name[str(i - 1)]["file"] if i > 1 else None
        next_name = id_to_name[str(i + 1)]["file"] if i < total_chunks else None
        content = render_markdown_chunk(
            ir,
            start_idx=start_idx,
            end_idx=end_idx,
            page_range=page_ranges[i - 1],
            meta=meta,
            chunk_number=i,
            total_chunks=total_chunks,
            prev_name=prev_name,
            next_name=next_name,
        )
        atomic_write_text(output_dir / meta["file"], content, encoding="utf-8")
