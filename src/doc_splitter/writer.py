"""Write chunk markdown files and manifest.json."""

from __future__ import annotations

import json
from pathlib import Path

from doc_splitter.boundary.planner import SplitSession
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, Element
from doc_splitter.structure_analyzer import active_h1_for_element, analyze_structure, page_range_for_elements


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


def _chunk_ranges(session: SplitSession, total_elements: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = 0
    for boundary in session.boundaries:
        end = int(boundary["end_index"])
        ranges.append((start, end))
        start = end + 1
    if start < total_elements:
        ranges.append((start, total_elements - 1))
    return ranges


def write_chunks(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
    output_dir: Path,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    structure = analyze_structure(ir, config)
    ranges = _chunk_ranges(session, len(ir.elements))
    total_chunks = len(ranges)
    manifest_chunks: list[dict] = []

    for i, (start_idx, end_idx) in enumerate(ranges, start=1):
        chunk_name = f"chunk-{i:03d}.md"
        prev_name = f"chunk-{i - 1:03d}.md" if i > 1 else None
        next_name = f"chunk-{i + 1:03d}.md" if i < total_chunks else None

        start_page, end_page = page_range_for_elements(
            ir, start_idx, end_idx, structure.element_pages
        )
        page_label = "~"
        if start_page is not None and end_page is not None:
            page_label = f"~{start_page}-{end_page}"

        body_parts = [_render_element(el) for el in ir.elements[start_idx : end_idx + 1]]
        body = "\n\n".join(p for p in body_parts if p)

        title = ""
        for el in ir.elements[start_idx : end_idx + 1]:
            if el.type == "heading":
                title = el.text
                break

        header_lines = [
            f"<!-- chunk: {i:02d}/{total_chunks} | source: {ir.meta.source_file} | pages: {page_label} -->",
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

        word_count = sum(ir.elements[j].word_count for j in range(start_idx, end_idx + 1))
        element_ids = [ir.elements[j].id for j in range(start_idx, end_idx + 1)]
        boundary_reason = ""
        if i - 1 < len(session.boundaries):
            boundary_reason = session.boundaries[i - 1].get("reason", "")

        manifest_chunks.append(
            {
                "id": i,
                "file": chunk_name,
                "title": title,
                "element_ids": element_ids,
                "start_index": start_idx,
                "end_index": end_idx,
                "start_page": start_page,
                "end_page": end_page,
                "word_count": word_count,
                "boundary_reason": boundary_reason,
                "h1_chapter": active_h1_for_element(ir, start_idx),
            }
        )

    manifest = {
        "source_file": ir.meta.source_file,
        "total_chunks": total_chunks,
        "chunks": manifest_chunks,
        "skipped_pages": [p.to_dict() for p in ir.meta.skipped_pages],
        "reconciliation_notes": ir.meta.reconciliation_notes,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest