"""Orchestrate chunk writing (Markdown and/or PDF) and manifest.json."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from doc_splitter.boundary.planner import (
    SplitSession,
    get_topic_review_progress,
)
from doc_splitter.config import SplitConfig
from doc_splitter.format_detector import InputFormat
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import save_json
from doc_splitter.naming import resolve_chunk_names
from doc_splitter.section_titles import infer_chunk_topic, list_section_headings
from doc_splitter.storage import atomic_write_text
from doc_splitter.structure_analyzer import (
    active_h1_for_element,
    analyze_structure,
    compute_chunk_page_ranges,
    page_range_for_elements,
)
from doc_splitter.workflow import BOUNDARY_COMPLETE, WRITING, require_stage
from doc_splitter.writers.markdown_writer import (
    extract_marked_section,
    render_markdown_chunk,
)
from doc_splitter.writers.pdf_writer import write_pdf_chunks

_CHUNK_FILE_RE = re.compile(r"^\d{2}_.+\.(md|pdf)$")


def validate_boundary_plan(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
) -> list[tuple[int, int]]:
    """Validate that an agent-reviewed plan covers the document exactly once."""
    require_stage(
        session,
        {BOUNDARY_COMPLETE, WRITING},
        "write chunk files",
    )
    total_elements = len(ir.elements)
    if session.cursor_index != total_elements:
        raise ValueError(
            "Boundary planning is incomplete: "
            f"cursor_index={session.cursor_index}, total_elements={total_elements}."
        )

    review_progress = get_topic_review_progress(ir, session, config)
    if not review_progress["complete"]:
        unresolved = [item["review_id"] for item in review_progress["unresolved"]]
        raise ValueError(
            "Topic-change review is incomplete. Resolve all required reviews before "
            f"writing: {unresolved}."
        )

    committed_end_indices = {int(boundary["end_index"]) for boundary in session.boundaries}
    missing_hard_boundaries = [
        review.get("boundary_element_id")
        for review in session.topic_change_reviews.values()
        if review.get("consensus") == "split"
        and int(review.get("boundary_index", -1)) not in committed_end_indices
    ]
    if missing_hard_boundaries:
        raise ValueError(
            "The boundary plan crosses confirmed topic changes. Missing cuts at: "
            f"{missing_hard_boundaries}."
        )

    if total_elements == 0:
        if session.boundaries:
            raise ValueError("Empty documents cannot contain boundary records.")
        return []

    if not session.boundaries:
        raise ValueError("Boundary planning is incomplete: no boundaries were committed.")

    ranges: list[tuple[int, int]] = []
    expected_start = 0
    structure = analyze_structure(ir, config)
    for position, boundary in enumerate(session.boundaries, start=1):
        start = int(boundary.get("start_index", -1))
        end = int(boundary.get("end_index", -1))
        if start != expected_start:
            raise ValueError(
                f"Boundary {position} starts at {start}; expected {expected_start}. "
                "The plan has a gap or overlap."
            )
        if end < start or end >= total_elements:
            raise ValueError(
                f"Boundary {position} has invalid range {start}-{end} for "
                f"{total_elements} elements."
            )
        expected_id = ir.elements[end].id
        if boundary.get("end_element_id") != expected_id:
            raise ValueError(
                f"Boundary {position} end_element_id does not match IR index {end}: "
                f"expected {expected_id}."
            )
        start_page, end_page = page_range_for_elements(ir, start, end, structure.element_pages)
        page_count = (
            end_page - start_page + 1 if start_page is not None and end_page is not None else None
        )
        if page_count is not None and page_count > config.hard_max_pages:
            raise ValueError(
                f"Boundary {position} creates {page_count} pages, exceeding "
                f"hard_max_pages={config.hard_max_pages}."
            )
        if page_count is not None and page_count > config.soft_max_pages:
            evidence = boundary.get("extension_evidence", [])
            valid_steps = {
                int(item.get("to_pages", 0))
                for item in evidence
                if len(item.get("evidence_element_ids", [])) >= 2
                and len(item.get("reviewer_ids", [])) >= config.continuity_min_reviewers
                and int(item.get("to_pages", 0)) > config.soft_max_pages
            }
            required_steps = set(range(config.soft_max_pages + 1, page_count + 1))
            if not required_steps.issubset(valid_steps):
                missing = sorted(required_steps - valid_steps)
                raise ValueError(
                    f"Boundary {position} exceeds soft_max_pages={config.soft_max_pages} "
                    "without continuity evidence for every extension step. "
                    f"Missing approvals for page limits: {missing}."
                )
        ranges.append((start, end))
        expected_start = end + 1

    if expected_start != total_elements:
        raise ValueError(
            "Boundary planning is incomplete: the committed plan ends at element "
            f"{expected_start - 1}, but the document ends at {total_elements - 1}."
        )
    return ranges


def _chunk_ranges(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
) -> list[tuple[int, int]]:
    return validate_boundary_plan(ir, session, config)


def _cleanup_orphan_chunk_files(output_dir: Path, keep_files: set[str]) -> None:
    for path in output_dir.iterdir():
        if path.is_file() and _CHUNK_FILE_RE.match(path.name) and path.name not in keep_files:
            path.unlink()


def _validate_output_format(config: SplitConfig, input_format: InputFormat | None) -> None:
    if config.output_format in ("pdf", "both") and input_format == InputFormat.DOCX:
        raise ValueError(
            "PDF output is only supported for PDF inputs. Use --output-format markdown for DOCX."
        )
    if config.output_format in ("pdf", "both") and not config.source_path:
        raise ValueError("source_path is required for PDF output format.")


def _load_previous_manifest(output_dir: Path) -> dict | None:
    path = output_dir / "manifest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _range_key(chunk: dict) -> tuple[int, int]:
    return int(chunk.get("start_index", -1)), int(chunk.get("end_index", -1))


def _remap_session_metadata(
    session: SplitSession,
    previous_manifest: dict | None,
    ranges: list[tuple[int, int]],
) -> dict[tuple[int, int], dict]:
    if not previous_manifest:
        return {}
    old_by_range = {
        _range_key(chunk): chunk
        for chunk in previous_manifest.get("chunks", [])
        if _range_key(chunk)[0] >= 0
    }
    previous_analyses = dict(session.chunk_analyses)
    previous_reads = set(session.chunks_read)
    remapped_analyses: dict[str, dict] = {}
    remapped_reads: list[int] = []
    for new_id, range_key in enumerate(ranges, start=1):
        old = old_by_range.get(range_key)
        if not old:
            continue
        old_id = int(old.get("id", 0))
        analysis = previous_analyses.get(str(old_id))
        if analysis:
            remapped_analyses[str(new_id)] = analysis
        if old_id in previous_reads:
            remapped_reads.append(new_id)
    session.chunk_analyses = remapped_analyses
    session.chunks_read = remapped_reads
    return old_by_range


def write_chunks(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
    output_dir: Path,
    *,
    input_format: InputFormat | None = None,
    reuse_existing: bool = False,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    _validate_output_format(config, input_format)

    ranges = _chunk_ranges(ir, session, config)
    total_chunks = len(ranges)
    page_ranges = compute_chunk_page_ranges(ir, ranges, config)
    previous_manifest = _load_previous_manifest(output_dir) if reuse_existing else None
    old_by_range = _remap_session_metadata(session, previous_manifest, ranges)

    write_md = config.output_format in ("markdown", "both")
    write_pdf = config.output_format in ("pdf", "both")
    source_path = config.source_path
    if write_pdf and source_path is None:
        raise ValueError("PDF output requires a source_path")
    md_names = resolve_chunk_names(ir, session, ranges, config, ext="md") if write_md else []
    pdf_names = resolve_chunk_names(ir, session, ranges, config, ext="pdf") if write_pdf else []

    reused_chunk_ids: list[int] = []
    rewritten_chunk_ids: list[int] = []
    with tempfile.TemporaryDirectory(prefix="doc-splitter-reuse-") as temp_name:
        temp_dir = Path(temp_name)
        preserved: dict[tuple[int, str], Path] = {}
        for i, range_key in enumerate(ranges, start=1):
            old = old_by_range.get(range_key)
            if not old:
                continue
            if write_md:
                old_name = old.get("markdown_file") or (
                    old.get("file") if str(old.get("file", "")).endswith(".md") else None
                )
                if old_name and (output_dir / old_name).is_file():
                    target = temp_dir / f"{i:04d}.md"
                    shutil.copy2(output_dir / old_name, target)
                    preserved[(i, "md")] = target
            if write_pdf:
                old_name = old.get("pdf_file") or (
                    old.get("file") if str(old.get("file", "")).endswith(".pdf") else None
                )
                if old_name and (output_dir / old_name).is_file():
                    target = temp_dir / f"{i:04d}.pdf"
                    shutil.copy2(output_dir / old_name, target)
                    preserved[(i, "pdf")] = target

        for i, (start_idx, end_idx) in enumerate(ranges, start=1):
            reused_body = False
            if write_md:
                meta = md_names[i - 1]
                prev_name = md_names[i - 2]["file"] if i > 1 else None
                next_name = md_names[i]["file"] if i < total_chunks else None
                marked_section = None
                preserved_md = preserved.get((i, "md"))
                if preserved_md:
                    marked_section = extract_marked_section(
                        preserved_md.read_text(encoding="utf-8")
                    )
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
                    marked_section=marked_section,
                )
                atomic_write_text(output_dir / meta["file"], content, encoding="utf-8")
                reused_body = marked_section is not None
            if write_pdf:
                meta = pdf_names[i - 1]
                preserved_pdf = preserved.get((i, "pdf"))
                if preserved_pdf:
                    shutil.copy2(preserved_pdf, output_dir / meta["file"])
                    reused_body = True if not write_md else reused_body
                else:
                    assert source_path is not None
                    write_pdf_chunks(
                        source_path,
                        [page_ranges[i - 1]],
                        [meta],
                        output_dir,
                    )
            if reused_body and old_by_range.get((start_idx, end_idx)):
                reused_chunk_ids.append(i)
            else:
                rewritten_chunk_ids.append(i)

    manifest_chunks: list[dict] = []
    for i, (start_idx, end_idx) in enumerate(ranges, start=1):
        pr = page_ranges[i - 1]
        md_meta = md_names[i - 1] if md_names else None
        pdf_meta = pdf_names[i - 1] if pdf_names else None
        primary = (
            md_meta
            or pdf_meta
            or {"file": f"{i:02d}_section-{i}", "slug": f"section-{i}", "title": ""}
        )

        word_count = sum(ir.elements[j].word_count for j in range(start_idx, end_idx + 1))
        element_ids = [ir.elements[j].id for j in range(start_idx, end_idx + 1)]
        boundary_meta = session.boundaries[i - 1] if i - 1 < len(session.boundaries) else {}
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
            "boundary_reason": boundary_meta.get("reason", ""),
            "split_type": boundary_meta.get("split_type", "conceptual"),
            "continues_to_next": bool(boundary_meta.get("continues_to_next", False)),
            "continues_from_previous": bool(boundary_meta.get("continues_from_previous", False)),
            "extension_evidence": boundary_meta.get("extension_evidence", []),
            "repair_of_chunk": boundary_meta.get("repair_of_chunk"),
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
        "page_policy": {
            "target_min_pages": config.min_pages,
            "preferred_max_pages": config.max_pages,
            "soft_max_pages": config.soft_max_pages,
            "hard_max_pages": config.hard_max_pages,
        },
        "total_chunks": total_chunks,
        "chunks": manifest_chunks,
        "skipped_pages": [p.to_dict() for p in ir.meta.skipped_pages],
        "reconciliation_notes": ir.meta.reconciliation_notes,
        "write_summary": {
            "mode": "repair" if reuse_existing else "initial",
            "reused_chunk_bodies": reused_chunk_ids,
            "rewritten_chunks": rewritten_chunk_ids,
        },
    }
    manifest_path = output_dir / "manifest.json"
    save_json(manifest, manifest_path)
    keep_files = {c["file"] for c in manifest_chunks}
    for c in manifest_chunks:
        if c.get("markdown_file"):
            keep_files.add(c["markdown_file"])
        if c.get("pdf_file"):
            keep_files.add(c["pdf_file"])
    _cleanup_orphan_chunk_files(output_dir, keep_files)
    return manifest
