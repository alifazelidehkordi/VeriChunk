"""Write semantic-named Markdown chunk files."""

from __future__ import annotations

from pathlib import Path

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, Element
from doc_splitter.naming import resolve_chunk_names
from doc_splitter.structure_analyzer import ChunkPageRange


def _render_element(el: Element) -> str:
    if el.type == "heading":
        return f"{'#' * (el.level or 1)} {el.text}"
    if el.type == "paragraph":
        return el.text
    if el.type == "list":
        return "\n".join(f"- {item}" for item in el.items)
    if el.type == "table":
        if not el.rows:
            return ""
        lines = []
        for i, row in enumerate(el.rows):
            lines.append("| " + " | ".join(row) + " |")
            if i == 0:
                lines.append("| " + " | ".join("---" for _ in row) + " |")
        return "\n".join(lines)
    if el.type == "image":
        caption = el.caption or ""
        return f"![{caption}]({el.ref})"
    return ""


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

        body_parts = [_render_element(el) for el in ir.elements[start_idx : end_idx + 1]]
        body = "\n\n".join(p for p in body_parts if p)
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
        content += body + "\n"

        (output_dir / chunk_name).write_text(content, encoding="utf-8")