"""Boundary planning session for host-agent LLM decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from doc_splitter.boundary.safe_candidates import SafeCandidate, candidates_in_word_window
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import load_json, save_json
from doc_splitter.structure_analyzer import analyze_structure, page_range_for_elements

SESSION_FILE = ".split-session.json"


@dataclass
class BoundaryDecision:
    end_element_id: str
    end_index: int
    reason: str
    est_pages: float | None = None


@dataclass
class SplitSession:
    source_file: str
    output_dir: str
    config: dict[str, Any]
    stage: str = "boundary"
    cursor_index: int = 0
    window_pages: int = 15
    boundaries: list[dict[str, Any]] = field(default_factory=list)
    chunk_analyses: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "output_dir": self.output_dir,
            "config": self.config,
            "stage": self.stage,
            "cursor_index": self.cursor_index,
            "window_pages": self.window_pages,
            "boundaries": self.boundaries,
            "chunk_analyses": self.chunk_analyses,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SplitSession:
        return cls(
            source_file=data["source_file"],
            output_dir=data["output_dir"],
            config=data.get("config", {}),
            stage=data.get("stage", "boundary"),
            cursor_index=int(data.get("cursor_index", 0)),
            window_pages=int(data.get("window_pages", 15)),
            boundaries=list(data.get("boundaries", [])),
            chunk_analyses=dict(data.get("chunk_analyses", {})),
        )


def session_path(output_dir: Path) -> Path:
    return output_dir / SESSION_FILE


def save_session(session: SplitSession, output_dir: Path) -> None:
    save_json(session.to_dict(), session_path(output_dir))


def load_session(output_dir: Path) -> SplitSession:
    return SplitSession.from_dict(load_json(session_path(output_dir)))


def _element_text_window(ir: DocumentIR, start: int, end: int) -> str:
    parts: list[str] = []
    for el in ir.elements[start : end + 1]:
        if el.type == "heading":
            parts.append(f"{'#' * (el.level or 1)} {el.text}")
        elif el.type == "paragraph":
            parts.append(el.text)
        elif el.type == "list":
            parts.extend(f"- {item}" for item in el.items)
        elif el.type == "table":
            for row in el.rows:
                parts.append("| " + " | ".join(row) + " |")
        elif el.type == "image":
            parts.append(f"[image: {el.ref}] {el.caption or ''}")
    return "\n\n".join(parts)


def get_boundary_context(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
) -> dict[str, Any]:
    if session.cursor_index >= len(ir.elements):
        return {"status": "complete", "boundaries": session.boundaries}

    structure = analyze_structure(ir, config)
    window_words = session.window_pages * config.words_per_page
    end_index, candidates = candidates_in_word_window(
        ir,
        session.cursor_index,
        window_words,
        config.min_chunk_words(),
    )

    if not candidates and end_index < len(ir.elements) - 1:
        session.window_pages += config.boundary_window_extension_pages
        window_words = session.window_pages * config.words_per_page
        end_index, candidates = candidates_in_word_window(
            ir, session.cursor_index, window_words, 0
        )

    start_page, _ = page_range_for_elements(
        ir, session.cursor_index, end_index, structure.element_pages
    )

    prompt_path = Path(__file__).parent / "prompts" / "boundary.md"
    return {
        "status": "needs_agent_decision",
        "chunk_number": len(session.boundaries) + 1,
        "cursor_index": session.cursor_index,
        "window_pages": session.window_pages,
        "estimated_start_page": start_page,
        "content_window": _element_text_window(ir, session.cursor_index, end_index),
        "safe_candidates": [
            {
                "element_id": c.element_id,
                "index": c.index,
                "after_type": c.after_type,
                "snippet": c.snippet,
                "cumulative_word_count": c.cumulative_word_count,
            }
            for c in candidates
        ],
        "instructions": prompt_path.read_text(encoding="utf-8"),
        "min_pages": config.min_pages,
        "max_pages": config.max_pages,
    }


def commit_boundary(
    ir: DocumentIR,
    session: SplitSession,
    config: SplitConfig,
    *,
    action: Literal["cut", "extend"],
    element_id: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    if action == "extend":
        session.window_pages += config.boundary_window_extension_pages
        save_session(session, Path(session.output_dir))
        return {
            "status": "extended",
            "window_pages": session.window_pages,
            "message": reason or "Window extended for concept completion.",
        }

    if not element_id:
        raise ValueError("element_id is required for action=cut")

    end_index = ir.index_of(element_id)
    _, candidates = candidates_in_word_window(
        ir,
        session.cursor_index,
        session.window_pages * config.words_per_page,
        0,
    )
    allowed = {c.element_id for c in candidates}
    if element_id not in allowed and end_index < len(ir.elements) - 1:
        raise ValueError(
            f"element_id {element_id} is not among safe candidates for the current window"
        )

    structure = analyze_structure(ir, config)
    start_page, end_page = page_range_for_elements(
        ir, session.cursor_index, end_index, structure.element_pages
    )
    est_pages = None
    if start_page is not None and end_page is not None:
        est_pages = end_page - start_page + 1

    session.boundaries.append(
        {
            "end_element_id": element_id,
            "end_index": end_index,
            "reason": reason,
            "start_index": session.cursor_index,
            "est_pages": est_pages,
            "start_page": start_page,
            "end_page": end_page,
        }
    )
    session.cursor_index = end_index + 1
    session.window_pages = config.boundary_window_pages
    save_session(session, Path(session.output_dir))

    if session.cursor_index >= len(ir.elements):
        return {"status": "complete", "boundaries": session.boundaries}
    return {"status": "continue", "cursor_index": session.cursor_index}