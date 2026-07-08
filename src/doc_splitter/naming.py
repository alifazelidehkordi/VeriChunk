"""Semantic chunk filenames: {index:02d}_{slug}.{ext}"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from doc_splitter.boundary.planner import SplitSession
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR

MARKUP_RE = re.compile(r"</?mark>|</?u>|\*\*|__|#{1,6}\s*")
NON_SLUG_RE = re.compile(r"[^\w\s-]", re.UNICODE)
WHITESPACE_RE = re.compile(r"[\s_]+")


def _ascii_fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def slugify(title: str, max_length: int = 60) -> str:
    cleaned = MARKUP_RE.sub("", title).strip()
    cleaned = _ascii_fold(cleaned)
    cleaned = NON_SLUG_RE.sub("", cleaned)
    cleaned = WHITESPACE_RE.sub("-", cleaned).strip("-").lower()
    if not cleaned:
        return ""
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("-")
    return cleaned


def _chunk_title(ir: DocumentIR, start_idx: int, end_idx: int) -> str:
    for el in ir.elements[start_idx : end_idx + 1]:
        if el.type == "heading" and el.text.strip():
            return el.text.strip()
    for el in ir.elements[start_idx : end_idx + 1]:
        if el.type == "paragraph" and el.text.strip():
            text = el.text.strip()
            if len(text) > 10:
                return text[:120]
    return ""


def resolve_chunk_names(
    ir: DocumentIR,
    session: SplitSession,
    ranges: list[tuple[int, int]],
    config: SplitConfig,
    *,
    ext: str,
) -> list[dict[str, str]]:
    used: set[str] = set()
    names: list[dict[str, str]] = []

    for i, (start_idx, end_idx) in enumerate(ranges, start=1):
        analysis = session.chunk_analyses.get(str(i), {})
        title = _chunk_title(ir, start_idx, end_idx)
        slug_source = analysis.get("topic_en") or title or f"section-{i}"
        slug = slugify(slug_source, config.slug_max_length) or f"section-{i}"

        base = f"{i:02d}_{slug}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used.add(candidate)

        filename = f"{candidate}.{ext}"
        names.append({"id": str(i), "slug": slug, "file": filename, "title": title})

    return names


def chunk_file_from_manifest(manifest: dict, chunk_id: int) -> str | None:
    for chunk in manifest.get("chunks", []):
        if chunk.get("id") == chunk_id:
            return chunk.get("file")
    return None


def resolve_chunk_path(output_dir: Path, manifest: dict, chunk_id: int) -> Path | None:
    name = chunk_file_from_manifest(manifest, chunk_id)
    if not name:
        return None
    return output_dir / name