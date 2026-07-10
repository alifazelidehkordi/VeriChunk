"""Controlled boundary-repair loop for incoherent generated chunks."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doc_splitter.boundary.planner import SplitSession, load_session, save_session
from doc_splitter.boundary.safe_candidates import find_safe_candidates
from doc_splitter.config import SplitConfig, config_from_dict
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import load_ir
from doc_splitter.section_titles import validate_boundary_reason
from doc_splitter.structure_analyzer import analyze_structure, page_range_for_elements
from doc_splitter.topic_reviews import find_topic_change_candidates
from doc_splitter.workflow import BOUNDARY_REPAIR, WRITING, require_stage, transition_stage


def _manifest(output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))


def _render_elements(ir: DocumentIR, start: int, end: int) -> str:
    parts: list[str] = []
    for element in ir.elements[start : end + 1]:
        prefix = f"[{element.id}] "
        if element.type == "heading":
            parts.append(prefix + "#" * (element.level or 1) + " " + element.text)
        elif element.type == "paragraph":
            parts.append(prefix + element.text)
        elif element.type == "list":
            parts.append(prefix + "\n".join(f"- {item}" for item in element.items))
        elif element.type == "table":
            rows = [" | ".join(row) for row in element.rows]
            parts.append(prefix + "\n".join(rows))
        elif element.type == "image":
            parts.append(prefix + f"[image: {element.ref}] {element.caption or ''}")
    return "\n\n".join(parts)


def _queued_target(
    session: SplitSession, manifest: dict[str, Any], chunk_id: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    chunk = next(
        (item for item in manifest.get("chunks", []) if int(item.get("id", 0)) == chunk_id), None
    )
    if chunk is None:
        raise ValueError(f"Chunk {chunk_id} not found in manifest")
    start = int(chunk.get("start_index", -1))
    end = int(chunk.get("end_index", -1))
    queued = next(
        (
            item
            for item in session.repair_queue
            if int(item.get("start_index", -2)) == start and int(item.get("end_index", -2)) == end
        ),
        None,
    )
    if queued is None:
        raise ValueError(f"Chunk {chunk_id} is not queued for boundary repair")
    return chunk, queued


def get_boundary_repair_context(output_dir: Path, chunk_id: int) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    session = load_session(output_dir)
    require_stage(session, BOUNDARY_REPAIR, "request boundary-repair context")
    manifest = _manifest(output_dir)
    chunk, queued = _queued_target(session, manifest, chunk_id)
    ir = load_ir(output_dir / "ir.json")
    config = config_from_dict(session.config)
    config.output_dir = output_dir
    start = int(chunk["start_index"])
    end = int(chunk["end_index"])

    safe = find_safe_candidates(ir, start, max(start, end - 1)) if end > start else []
    semantic = [
        candidate
        for candidate in find_topic_change_candidates(ir, config)
        if start <= candidate.boundary_index < end
    ]
    semantic_ids = {candidate.boundary_element_id for candidate in semantic}
    previous = next(
        (c for c in manifest.get("chunks", []) if int(c.get("id", 0)) == chunk_id - 1), None
    )
    following = next(
        (c for c in manifest.get("chunks", []) if int(c.get("id", 0)) == chunk_id + 1), None
    )

    return {
        "status": "needs_agent_repair_decision",
        "stage": session.stage,
        "chunk_id": chunk_id,
        "queued_reason": queued.get("reason", ""),
        "target_range": {"start_index": start, "end_index": end},
        "source_pages": chunk.get("source_pages", []),
        "previous_chunk": (
            {
                "id": previous["id"],
                "title": previous.get("title", ""),
                "range": [previous.get("start_index"), previous.get("end_index")],
                "content": _render_elements(
                    ir, int(previous.get("start_index", 0)), int(previous.get("end_index", 0))
                ),
            }
            if previous
            else None
        ),
        "next_chunk": (
            {
                "id": following["id"],
                "title": following.get("title", ""),
                "range": [following.get("start_index"), following.get("end_index")],
                "content": _render_elements(
                    ir, int(following.get("start_index", 0)), int(following.get("end_index", 0))
                ),
            }
            if following
            else None
        ),
        "content": _render_elements(ir, start, end),
        "safe_cut_candidates": [
            {
                "element_id": candidate.element_id,
                "index": candidate.index,
                "after_type": candidate.after_type,
                "snippet": candidate.snippet,
                "semantic_candidate": candidate.element_id in semantic_ids,
            }
            for candidate in safe
            if candidate.index < end
        ],
        "semantic_candidates": [asdict(candidate) for candidate in semantic],
        "instructions": (
            "Choose one or more internal safe cut element IDs that separate independent "
            "learning objectives. The original final boundary is preserved automatically. "
            "Do not cut merely to satisfy a page target."
        ),
    }


def commit_boundary_repair_plan(
    output_dir: Path,
    chunk_id: int,
    *,
    cut_element_ids: list[str],
    reason: str,
) -> tuple[DocumentIR, SplitSession, SplitConfig, dict[str, Any]]:
    output_dir = output_dir.expanduser().resolve()
    validate_boundary_reason(reason)
    session = load_session(output_dir)
    require_stage(session, BOUNDARY_REPAIR, "commit a boundary repair")
    manifest = _manifest(output_dir)
    chunk, queued = _queued_target(session, manifest, chunk_id)
    ir = load_ir(output_dir / "ir.json")
    config = config_from_dict(session.config)
    config.output_dir = output_dir

    start = int(chunk["start_index"])
    end = int(chunk["end_index"])
    if not cut_element_ids:
        raise ValueError("At least one --cut-element-id is required for boundary repair")
    indices = sorted({ir.index_of(element_id) for element_id in cut_element_ids})
    if any(index < start or index >= end for index in indices):
        raise ValueError("Repair cuts must be internal to the queued chunk")

    allowed = {
        candidate.element_id
        for candidate in find_safe_candidates(ir, start, max(start, end - 1))
        if candidate.index < end
    }
    invalid = [element_id for element_id in cut_element_ids if element_id not in allowed]
    if invalid:
        raise ValueError(f"Repair cuts are not structurally safe: {invalid}")

    boundary_position = next(
        (
            index
            for index, boundary in enumerate(session.boundaries)
            if int(boundary.get("start_index", -1)) == start
            and int(boundary.get("end_index", -1)) == end
        ),
        None,
    )
    if boundary_position is None:
        raise ValueError("Queued chunk no longer matches the committed boundary plan")

    structure = analyze_structure(ir, config)
    original = session.boundaries[boundary_position]
    new_ends = indices + [end]
    replacement: list[dict[str, Any]] = []
    next_start = start
    confirmed = {
        int(review.get("boundary_index", -1))
        for review in session.topic_change_reviews.values()
        if review.get("consensus") == "split"
    }
    for position, new_end in enumerate(new_ends):
        start_page, end_page = page_range_for_elements(
            ir, next_start, new_end, structure.element_pages
        )
        page_count = (
            end_page - start_page + 1 if start_page is not None and end_page is not None else None
        )
        if page_count is not None and page_count > config.hard_max_pages:
            raise ValueError(
                f"Repair would create {page_count} pages, exceeding hard_max_pages={config.hard_max_pages}"
            )
        is_last = position == len(new_ends) - 1
        replacement.append(
            {
                "start_index": next_start,
                "end_index": new_end,
                "end_element_id": ir.elements[new_end].id,
                "reason": reason if not is_last else original.get("reason", reason),
                "est_pages": page_count,
                "start_page": start_page,
                "end_page": end_page,
                "split_type": (
                    "repair_topic_change"
                    if not is_last or new_end in confirmed
                    else original.get("split_type", "conceptual")
                ),
                "continues_from_previous": (
                    bool(original.get("continues_from_previous", False)) if position == 0 else False
                ),
                "continues_to_next": (
                    bool(original.get("continues_to_next", False)) if is_last else False
                ),
                "extension_evidence": original.get("extension_evidence", []) if is_last else [],
                "repair_of_chunk": chunk_id,
            }
        )
        next_start = new_end + 1

    old_range = [start, end]
    session.boundaries[boundary_position : boundary_position + 1] = replacement
    session.active_repair = {
        "chunk_id": chunk_id,
        "old_range": old_range,
        "new_ranges": [[item["start_index"], item["end_index"]] for item in replacement],
        "reason": reason,
        "queued_reason": queued.get("reason", ""),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    session.cursor_index = len(ir.elements)
    transition_stage(session, WRITING)
    save_session(session, output_dir)
    return ir, session, config, session.active_repair
