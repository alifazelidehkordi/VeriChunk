"""Orchestrate chunk writing (Markdown and/or PDF) and manifest.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

from doc_splitter.boundary.planner import SplitSession
from doc_splitter.config import SplitConfig
from doc_splitter.format_detector import InputFormat, detect_format
from doc_splitter.ir.models import DocumentIR
from doc_splitter.naming import resolve_chunk_names
from doc_splitter.section_titles import infer_chunk_topic, list_section_headings
from doc_splitter.structure_analyzer import (
    active_h1_for_element,
    compute_chunk_page_ranges,
)

_CHUNK_FILE_RE = re.compile(r"^\d{2}_.+\.(md|pdf)$")
from doc_splitter.writers.markdown_writer import write_markdown_chunks
from doc_splitter.writers.pdf_writer import write_pdf_chunks


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


def _cleanup_orphan_chunk_files(output_dir: Path, keep_files: set[str]) -> None:
    for path in output_dir.iterdir():
        if (
            path.is_file()
            and _CHUNK_FILE_RE.match(path.name)
            and path.name not in keep_files
        ):
            path.unlink()


def _validate_output_format(config: SplitConfig, input_format: InputFormat | None) -> None:
    if config.output_format in ("pdf", "both") and input_format == InputFormat.DOCX:
        raise ValueError(
            "PDF output is only supported for PDF inputs. Use --output-format markdown for DOCX."
        )
    if config.output_format in ("pdf", "both") and not config.source_path:
        raise ValueError("source_path is required for PDF output format.")


def write_chunks(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
    output_dir: Path,
    *,
    input_format: InputFormat | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    _validate_output_format(config, input_format)

    ranges = _chunk_ranges(session, len(ir.elements))
    total_chunks = len(ranges)
    page_ranges = compute_chunk_page_ranges(ir, ranges, config)

    write_md = config.output_format in ("markdown", "both")
    write_pdf = config.output_format in ("pdf", "both")

    md_names = (
        resolve_chunk_names(ir, session, ranges, config, ext="md") if write_md else []
    )
    pdf_names = (
        resolve_chunk_names(ir, session, ranges, config, ext="pdf") if write_pdf else []
    )

    if write_md:
        write_markdown_chunks(
            ir, ranges, page_ranges, md_names, output_dir, total_chunks
        )
    if write_pdf:
        write_pdf_chunks(config.source_path, page_ranges, pdf_names, output_dir)

    manifest_chunks: list[dict] = []
    for i, (start_idx, end_idx) in enumerate(ranges, start=1):
        pr = page_ranges[i - 1]
        md_meta = md_names[i - 1] if md_names else None
        pdf_meta = pdf_names[i - 1] if pdf_names else None
        primary = md_meta or pdf_meta or {"file": f"{i:02d}_section-{i}", "slug": f"section-{i}", "title": ""}

        word_count = sum(ir.elements[j].word_count for j in range(start_idx, end_idx + 1))
        element_ids = [ir.elements[j].id for j in range(start_idx, end_idx + 1)]
        boundary_reason = ""
        if i - 1 < len(session.boundaries):
            boundary_reason = session.boundaries[i - 1].get("reason", "")

        chunk_entry: dict = {
            "id": i,
            "file": primary["file"],
            "slug": primary["slug"],
            "title": primary.get("title", ""),
            "inferred_topic": infer_chunk_topic(ir, start_idx, end_idx),
            "section_headings": list_section_headings(ir, start_idx, end_idx),
            "format": config.output_format,
            "element_ids": element_ids,
            "start_index": start_idx,
            "end_index": end_idx,
            "start_page": pr.start_page if pr.source_pages else None,
            "end_page": pr.end_page if pr.source_pages else None,
            "source_pages": pr.source_pages,
            "pdf_pages": pr.pdf_pages,
            "overlap_pages": {"prev": pr.overlap_prev, "next": pr.overlap_next},
            "word_count": word_count,
            "boundary_reason": boundary_reason,
            "h1_chapter": active_h1_for_element(ir, start_idx),
        }
        if md_meta:
            chunk_entry["markdown_file"] = md_meta["file"]
        if pdf_meta:
            chunk_entry["pdf_file"] = pdf_meta["file"]
            if config.output_format == "pdf":
                chunk_entry["file"] = pdf_meta["file"]
        manifest_chunks.append(chunk_entry)

    manifest = {
        "source_file": ir.meta.source_file,
        "source_path": str(config.source_path) if config.source_path else None,
        "output_format": config.output_format,
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
    keep_files = {c["file"] for c in manifest_chunks}
    for c in manifest_chunks:
        if c.get("markdown_file"):
            keep_files.add(c["markdown_file"])
        if c.get("pdf_file"):
            keep_files.add(c["pdf_file"])
    _cleanup_orphan_chunk_files(output_dir, keep_files)
    return manifest