"""Content analysis session for host-agent chunk descriptions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from doc_splitter.boundary.planner import SplitSession, load_session, save_session
from doc_splitter.ir.serialize import save_json


def get_chunk_analysis_context(
    output_dir: Path,
    chunk_id: int,
) -> dict[str, Any]:
    session = load_session(output_dir)
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    chunks = manifest.get("chunks", [])
    chunk = next((c for c in chunks if c["id"] == chunk_id), None)
    if chunk is None:
        raise ValueError(f"Chunk {chunk_id} not found in manifest")

    chunk_path = output_dir / chunk["file"]
    content = chunk_path.read_text(encoding="utf-8")

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
        "title": chunk.get("title", ""),
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
    coherence: Literal["confident", "needs_review"],
    reason: str = "",
) -> dict[str, Any]:
    session = load_session(output_dir)
    session.chunk_analyses[str(chunk_id)] = {
        "topic_fa": topic_fa,
        "topic_en": topic_en,
        "coherence": coherence,
        "reason": reason,
    }
    save_session(session, output_dir)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    total = int(manifest.get("total_chunks", 0))
    done = len(session.chunk_analyses)
    if done >= total:
        session.stage = "index"
        save_session(session, output_dir)
        _write_semantic_report(output_dir, session)
        return {"status": "complete", "analyzed": done, "total": total}
    return {"status": "continue", "analyzed": done, "total": total}


def _write_semantic_report(output_dir: Path, session: SplitSession) -> None:
    needs_review = [
        {"chunk_id": int(k), **v}
        for k, v in session.chunk_analyses.items()
        if v.get("coherence") == "needs_review"
    ]
    report = {
        "total_chunks": len(session.chunk_analyses),
        "needs_review": needs_review,
        "analyses": session.chunk_analyses,
    }
    save_json(report, output_dir / "semantic-review-report.json")