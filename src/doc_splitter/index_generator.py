"""Agent-authored study index handoff.

Python prepares bounded source data and validates saved artifacts. The actual
Persian and English index prose is authored by the host agent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from doc_splitter.boundary.planner import SplitSession, load_session, save_session
from doc_splitter.config import SplitConfig
from doc_splitter.content.analyzer import read_chunk_content
from doc_splitter.section_titles import validate_analysis


def _page_label(chunk: dict[str, Any]) -> str:
    pages = chunk.get("source_pages") or []
    if pages:
        if len(pages) == 1:
            return str(pages[0])
        return f"{pages[0]}-{pages[-1]}"
    start = chunk.get("start_page")
    end = chunk.get("end_page")
    if start is None or end is None:
        return ""
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _estimated_minutes(chunk: dict[str, Any], config: SplitConfig) -> int:
    return max(1, int(int(chunk.get("word_count", 0)) / config.reading_speed_wpm))


def _load_manifest(output_dir: Path) -> dict[str, Any]:
    return json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))


def _validate_ready_for_index(
    manifest: dict[str, Any],
    session: SplitSession,
) -> None:
    missing: list[int] = []
    needs_review: list[int] = []
    for chunk in manifest.get("chunks", []):
        chunk_id = int(chunk["id"])
        analysis = session.chunk_analyses.get(str(chunk_id))
        if not analysis:
            missing.append(chunk_id)
            continue
        if not analysis.get("study_focus_fa") or not analysis.get("study_focus_en"):
            missing.append(chunk_id)
            continue
        if analysis.get("coherence") == "needs_review":
            needs_review.append(chunk_id)
        validate_analysis(
            topic_fa=analysis["topic_fa"],
            topic_en=analysis["topic_en"],
            study_focus_fa=analysis["study_focus_fa"],
            study_focus_en=analysis["study_focus_en"],
        )
    if missing:
        raise ValueError(
            f"Missing content analyses for chunks: {missing}. "
            "Run analysis-context and commit-analysis first."
        )
    if needs_review:
        raise ValueError(
            f"Chunks need boundary/coherence review before final indexes: {needs_review}. "
            "Fix the boundaries or recommit analysis with coherence=confident."
        )

    total = len(manifest.get("chunks", []))
    unread = [i for i in range(1, total + 1) if i not in session.chunks_read]
    if unread:
        raise ValueError(
            f"Chunk files not yet read by the agent: {unread}. "
            f"Use get_chunk to read each chunk before writing the study index. "
            f"Read {len(session.chunks_read)}/{total} so far."
        )


def get_index_context(output_dir: Path, config: SplitConfig) -> dict[str, Any]:
    manifest = _load_manifest(output_dir)
    session = load_session(output_dir)
    _validate_ready_for_index(manifest, session)

    prompt_path = Path(__file__).parent / "index" / "prompts" / "index.md"
    chunks: list[dict[str, Any]] = []
    total_minutes = 0
    for chunk in manifest.get("chunks", []):
        analysis = session.chunk_analyses[str(chunk["id"])]
        minutes = _estimated_minutes(chunk, config)
        total_minutes += minutes

        content_preview = ""
        try:
            full = read_chunk_content(output_dir, chunk)
            content_preview = full.strip()[:300]
        except Exception:
            content_preview = ""

        chunks.append(
            {
                "id": chunk["id"],
                "file": chunk.get("file"),
                "markdown_file": chunk.get("markdown_file"),
                "pdf_file": chunk.get("pdf_file"),
                "title": chunk.get("title"),
                "topic_fa": analysis["topic_fa"],
                "topic_en": analysis["topic_en"],
                "study_focus_fa": analysis["study_focus_fa"],
                "study_focus_en": analysis["study_focus_en"],
                "coherence": analysis["coherence"],
                "coherence_reason": analysis.get("reason", ""),
                "source_pages": chunk.get("source_pages", []),
                "page_label": _page_label(chunk),
                "word_count": chunk.get("word_count", 0),
                "estimated_minutes": minutes,
                "boundary_reason": chunk.get("boundary_reason", ""),
                "section_headings": chunk.get("section_headings", []),
                "h1_chapter": chunk.get("h1_chapter"),
                "content_preview": content_preview,
            }
        )

    return {
        "status": "needs_agent_decision",
        "source_file": manifest.get("source_file"),
        "source_path": manifest.get("source_path"),
        "total_chunks": manifest.get("total_chunks", len(chunks)),
        "total_estimated_minutes": total_minutes,
        "reading_speed_wpm": config.reading_speed_wpm,
        "total_word_count": sum(c.get("word_count", 0) for c in manifest.get("chunks", [])),
        "output_files": {
            "fa": str(output_dir / "study-index-fa.md"),
            "en": str(output_dir / "study-index-en.md"),
            "map": str(output_dir / "study-map.md"),
        },
        "chunks": chunks,
        "chunks_read": session.chunks_read,
        "chunks_unread": [i for i in range(1, len(manifest.get("chunks", [])) + 1) if i not in session.chunks_read],
        "instructions": prompt_path.read_text(encoding="utf-8"),
    }


_RE_AUTO_STUDY_FOCUS = re.compile(
    r"^\s*(?:Study|Review)\s+.+?:\s*(?:core\s+definitions?|mechanisms?|laboratory\s+methods?)\s*,?\s*(?:core\s+definitions?|mechanisms?|laboratory\s+methods?|and\s+clinical\s+applications?)",
    re.IGNORECASE | re.MULTILINE,
)


def _validate_agent_index(
    text: str,
    *,
    lang: str,
    manifest: dict[str, Any],
) -> None:
    if not text.strip():
        raise ValueError(f"{lang} index must not be empty.")
    if not text.lstrip().startswith("#"):
        raise ValueError(f"{lang} index must start with a Markdown H1 heading.")
    missing_links = [
        chunk["file"]
        for chunk in manifest.get("chunks", [])
        if chunk.get("file") and chunk["file"] not in text
    ]
    if missing_links:
        raise ValueError(
            f"{lang} index does not reference every chunk file. Missing: {missing_links[:10]}"
        )
    _validate_index_quality(text, lang=lang, manifest=manifest)


_STUDY_MAP_SECTIONS = (
    "## Topic Map",
    "## Suggested Study Order",
    "## Session Directory",
)


def _validate_study_map(text: str, manifest: dict[str, Any]) -> None:
    """Require a reusable document-level map, not a domain-specific template."""
    _validate_agent_index(text, lang="Study map", manifest=manifest)
    missing_sections = [section for section in _STUDY_MAP_SECTIONS if section not in text]
    if missing_sections:
        raise ValueError(
            "Study map is missing required sections: " + ", ".join(missing_sections)
        )


def _validate_index_quality(
    text: str,
    *,
    lang: str,
    manifest: dict[str, Any],
) -> None:
    found_template = _RE_AUTO_STUDY_FOCUS.search(text)
    if found_template:
        raise ValueError(
            f"{lang} index contains auto-generated study-focus template: "
            f"'{found_template.group()}'. "
            "Each session's study focus must be unique educational content you write yourself, "
            "not a template like 'Study X: core definitions, mechanisms, clinical applications'."
        )


def commit_study_indexes(
    output_dir: Path,
    *,
    index_fa: str,
    index_en: str,
    study_map: str,
) -> tuple[Path, Path, Path]:
    manifest = _load_manifest(output_dir)
    session = load_session(output_dir)
    _validate_ready_for_index(manifest, session)
    _validate_agent_index(index_fa, lang="Persian", manifest=manifest)
    _validate_agent_index(index_en, lang="English", manifest=manifest)
    _validate_study_map(study_map, manifest)

    fa_path = output_dir / "study-index-fa.md"
    en_path = output_dir / "study-index-en.md"
    map_path = output_dir / "study-map.md"
    fa_path.write_text(index_fa.rstrip() + "\n", encoding="utf-8")
    en_path.write_text(index_en.rstrip() + "\n", encoding="utf-8")
    map_path.write_text(study_map.rstrip() + "\n", encoding="utf-8")

    session.stage = "complete"
    save_session(session, output_dir)
    return fa_path, en_path, map_path
