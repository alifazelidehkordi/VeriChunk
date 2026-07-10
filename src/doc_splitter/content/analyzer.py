"""Content analysis session for host-agent chunk descriptions."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Literal

from doc_splitter.boundary.planner import (
    SplitSession,
    load_session,
    record_chunk_read,
    save_session,
)
from doc_splitter.ir.serialize import load_ir, save_json
from doc_splitter.storage import atomic_write_text
from doc_splitter.workflow import CONTENT_ANALYSIS, INDEX, require_stage, transition_stage
from doc_splitter.naming import slugify
from doc_splitter.section_titles import (
    infer_chunk_topic,
    list_section_headings,
    validate_analysis,
    validate_analysis_reason,
)


def _chunk_read_path(output_dir: Path, chunk: dict) -> Path:
    name = chunk.get("markdown_file") or chunk.get("file")
    if not name:
        raise ValueError(f"Chunk {chunk.get('id')} has no readable file in manifest")
    return output_dir / name


def read_chunk_content(output_dir: Path, chunk: dict) -> str:
    path = _chunk_read_path(output_dir, chunk)
    if path.suffix.lower() == ".pdf":
        import pymupdf

        doc = pymupdf.open(str(path))
        try:
            parts = [page.get_text() for page in doc]
            text = "\n\n".join(p.strip() for p in parts if p.strip())
            if text:
                return text
            pages = chunk.get("pdf_pages") or chunk.get("source_pages") or []
            return f"[PDF chunk: {path.name}, pages: {pages}]"
        finally:
            doc.close()
    return path.read_text(encoding="utf-8")


def _unique_topic_slug(
    topic: str,
    chunk_id: int,
    used: set[str],
    *,
    max_length: int = 60,
) -> str:
    base = slugify(topic, max_length) or f"section-{chunk_id}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _rename_file(output_dir: Path, old_name: str, new_name: str) -> None:
    if old_name == new_name:
        return
    old_path = output_dir / old_name
    new_path = output_dir / new_name
    if not old_path.exists():
        return
    if new_path.exists():
        raise ValueError(f"Cannot rename {old_name} to {new_name}: destination exists")
    tmp_path = output_dir / f".rename-{uuid.uuid4().hex}-{old_path.name}"
    old_path.rename(tmp_path)
    tmp_path.rename(new_path)


def _page_label(chunk: dict) -> str:
    pages = chunk.get("source_pages") or []
    if pages:
        if len(pages) == 1:
            return f"~{pages[0]}"
        return f"~{pages[0]}-{pages[-1]}"
    return "~"


def _replace_markdown_header(
    content: str,
    *,
    section_line: str,
    prev_line: str | None,
    next_line: str | None,
    title: str,
) -> str:
    lines = content.splitlines()
    body_start = 0
    while body_start < len(lines) and lines[body_start].startswith("<!--"):
        body_start += 1
    if body_start < len(lines) and lines[body_start] == "":
        body_start += 1

    body = lines[body_start:]
    if body and body[0].startswith("## "):
        body[0] = f"## {title}"

    header = [section_line]
    if prev_line:
        header.append(prev_line)
    if next_line:
        header.append(next_line)
    return "\n".join(header + [""] + body).rstrip() + "\n"


def _refresh_markdown_headers(output_dir: Path, manifest: dict) -> None:
    chunks = manifest.get("chunks", [])
    total = int(manifest.get("total_chunks", len(chunks)))
    source = manifest.get("source_file", "")
    for i, chunk in enumerate(chunks):
        name = chunk.get("markdown_file") or (
            chunk.get("file") if str(chunk.get("file", "")).endswith(".md") else None
        )
        if not name:
            continue
        path = output_dir / name
        if not path.exists():
            continue
        prev_name = None
        next_name = None
        if i > 0:
            prev = chunks[i - 1]
            prev_name = prev.get("markdown_file") or prev.get("file")
        if i < total - 1:
            nxt = chunks[i + 1]
            next_name = nxt.get("markdown_file") or nxt.get("file")

        section_line = (
            f"<!-- section: {int(chunk['id']):02d}/{total} | file: {name} | "
            f"source: {source} | pages: {_page_label(chunk)} -->"
        )
        prev_line = f"<!-- continues-from: {prev_name} -->" if prev_name else None
        next_line = f"<!-- continues-to: {next_name} -->" if next_name else None
        title = chunk.get("title") or chunk.get("agent_topic_en") or f"Section {chunk['id']}"
        atomic_write_text(
            path,
            _replace_markdown_header(
                path.read_text(encoding="utf-8"),
                section_line=section_line,
                prev_line=prev_line,
                next_line=next_line,
                title=title,
            ),
            encoding="utf-8",
        )


def _apply_agent_topic_filename(
    output_dir: Path,
    session: SplitSession,
    chunk_id: int,
) -> None:
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = manifest.get("chunks", [])
    chunk = next((c for c in chunks if int(c.get("id", 0)) == chunk_id), None)
    if chunk is None:
        raise ValueError(f"Chunk {chunk_id} not found in manifest")

    analysis = session.chunk_analyses.get(str(chunk_id), {})
    topic_en = analysis.get("topic_en", "").strip()
    if not topic_en:
        return

    used_slugs = {
        c.get("slug", "")
        for c in chunks
        if int(c.get("id", 0)) != chunk_id and c.get("slug")
    }
    slug = _unique_topic_slug(topic_en, chunk_id, used_slugs)
    base = f"{chunk_id:02d}_{slug}"

    old_primary = chunk.get("file", "")
    old_markdown = chunk.get("markdown_file")
    old_pdf = chunk.get("pdf_file")
    primary_ext = Path(old_primary).suffix.lower()

    if old_markdown or primary_ext == ".md":
        new_markdown = f"{base}.md"
        if old_markdown:
            _rename_file(output_dir, old_markdown, new_markdown)
            chunk["markdown_file"] = new_markdown
        if primary_ext == ".md":
            _rename_file(output_dir, old_primary, new_markdown)
            chunk["file"] = new_markdown

    if old_pdf or primary_ext == ".pdf":
        new_pdf = f"{base}.pdf"
        if old_pdf:
            _rename_file(output_dir, old_pdf, new_pdf)
            chunk["pdf_file"] = new_pdf
        if primary_ext == ".pdf":
            _rename_file(output_dir, old_primary, new_pdf)
            chunk["file"] = new_pdf

    chunk["slug"] = slug
    chunk["title"] = topic_en
    chunk["agent_topic_en"] = topic_en
    chunk["agent_topic_fa"] = analysis.get("topic_fa", "")

    save_json(manifest, manifest_path)
    _refresh_markdown_headers(output_dir, manifest)


def get_chunk_analysis_context(
    output_dir: Path,
    chunk_id: int,
) -> dict[str, Any]:
    session = load_session(output_dir)
    require_stage(session, CONTENT_ANALYSIS, "request chunk analysis context")
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    chunks = manifest.get("chunks", [])
    chunk = next((c for c in chunks if c["id"] == chunk_id), None)
    if chunk is None:
        raise ValueError(f"Chunk {chunk_id} not found in manifest")

    # Analysis reads the complete chunk, so it satisfies the index read gate too.
    record_chunk_read(output_dir, chunk_id)
    content = read_chunk_content(output_dir, chunk)

    ir = load_ir(output_dir / "ir.json")
    start_idx = int(chunk.get("start_index", 0))
    end_idx = int(chunk.get("end_index", start_idx))
    section_headings = list_section_headings(ir, start_idx, end_idx)
    provisional_topic = infer_chunk_topic(ir, start_idx, end_idx)

    prev_title = ""
    next_title = ""
    for c in chunks:
        if c["id"] == chunk_id - 1:
            prev_title = c.get("title", "")
        if c["id"] == chunk_id + 1:
            next_title = c.get("title", "")

    prompt_path = Path(__file__).parent / "prompts" / "content.md"
    return {
        "status": "needs_agent_decision",
        "chunk_id": chunk_id,
        "chunk_file": chunk["file"],
        "markdown_file": chunk.get("markdown_file"),
        "pdf_file": chunk.get("pdf_file"),
        "source_pages": chunk.get("source_pages", []),
        "pdf_pages": chunk.get("pdf_pages", []),
        "title": chunk.get("title", ""),
        "section_headings": section_headings,
        "provisional_topic": provisional_topic,
        "prev_chunk_title": prev_title,
        "next_chunk_title": next_title,
        "content": content,
        "instructions": prompt_path.read_text(encoding="utf-8"),
    }


def commit_chunk_analysis(
    output_dir: Path,
    chunk_id: int,
    *,
    topic_fa: str,
    topic_en: str,
    study_focus_fa: str,
    study_focus_en: str,
    coherence: Literal["confident", "needs_review"],
    reason: str = "",
) -> dict[str, Any]:
    validate_analysis(
        topic_fa=topic_fa,
        topic_en=topic_en,
        study_focus_fa=study_focus_fa,
        study_focus_en=study_focus_en,
    )
    validate_analysis_reason(reason)
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    chunks = manifest.get("chunks", [])
    valid_chunk_ids = {int(chunk["id"]) for chunk in chunks}
    if chunk_id not in valid_chunk_ids:
        raise ValueError(f"Chunk {chunk_id} not found in manifest")

    session = load_session(output_dir)
    require_stage(session, CONTENT_ANALYSIS, "commit chunk analysis")
    session.chunk_analyses[str(chunk_id)] = {
        "topic_fa": topic_fa,
        "topic_en": topic_en,
        "study_focus_fa": study_focus_fa,
        "study_focus_en": study_focus_en,
        "coherence": coherence,
        "reason": reason,
    }
    save_session(session, output_dir)
    _apply_agent_topic_filename(output_dir, session, chunk_id)

    valid_analysis_keys = {str(chunk_id) for chunk_id in valid_chunk_ids}
    done = sum(1 for key in valid_analysis_keys if key in session.chunk_analyses)
    total = len(valid_chunk_ids)
    needs_review = [
        int(key)
        for key in valid_analysis_keys
        if session.chunk_analyses.get(key, {}).get("coherence") == "needs_review"
    ]
    if done >= total:
        _write_semantic_report(output_dir, session, valid_chunk_ids=valid_chunk_ids)
        if needs_review:
            return {
                "status": "needs_boundary_review",
                "analyzed": done,
                "total": total,
                "chunks": sorted(needs_review),
            }
        transition_stage(session, INDEX)
        save_session(session, output_dir)
        return {
            "status": "complete",
            "stage": session.stage,
            "analyzed": done,
            "total": total,
        }
    return {
        "status": "continue",
        "stage": session.stage,
        "analyzed": done,
        "total": total,
    }


def _write_semantic_report(
    output_dir: Path,
    session: SplitSession,
    *,
    valid_chunk_ids: set[int],
) -> None:
    valid_keys = {str(chunk_id) for chunk_id in valid_chunk_ids}
    analyses = {
        key: value
        for key, value in session.chunk_analyses.items()
        if key in valid_keys
    }
    needs_review = [
        {"chunk_id": int(k), **v}
        for k, v in analyses.items()
        if v.get("coherence") == "needs_review"
    ]
    report = {
        "total_chunks": len(valid_chunk_ids),
        "needs_review": needs_review,
        "analyses": analyses,
    }
    save_json(report, output_dir / "semantic-review-report.json")
