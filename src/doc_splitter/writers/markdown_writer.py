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
        chunk_name = meta["file"]
        prev_name = id_to_name[str(i - 1)]["file"] if i > 1 else None
        next_name = id_to_name[str(i + 1)]["file"] if i < total_chunks else None

        pr = page_ranges[i - 1]
        page_label = "~"
        if pr.source_pages:
            page_label = f"~{pr.start_page}-{pr.end_page}"

        body_parts = [
            render_marked_element(el)
            for el in ir.elements[start_idx : end_idx + 1]
        ]
        body = "\n\n".join(body_parts)
        title = meta.get("title", "")

        header_lines = [
            f"<!-- section: {i:02d}/{total_chunks} | file: {chunk_name} | source: {ir.meta.source_file} | pages: {page_label} -->",
        ]
        if prev_name:
            header_lines.append(f"<!-- continues-from: {prev_name} -->")
        if next_name:
            header_lines.append(f"<!-- continues-to: {next_name} -->")

        content = "\n".join(header_lines) + "\n\n"
        if title:
            content += f"## {title}\n\n"
        content += f"{ELEMENTS_START}\n\n{body}\n\n{ELEMENTS_END}\n"

        atomic_write_text(output_dir / chunk_name, content, encoding="utf-8")