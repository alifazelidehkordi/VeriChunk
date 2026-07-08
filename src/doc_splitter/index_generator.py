"""Generate bilingual study indexes from manifest and content analyses."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from doc_splitter.boundary.planner import load_session
from doc_splitter.config import SplitConfig


def _format_duration(total_minutes: int, lang: str) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if lang == "fa":
        if hours:
            return f"{hours} ساعت و {minutes} دقیقه"
        return f"{minutes} دقیقه"
    if hours:
        return f"{hours} hours and {minutes} minutes"
    return f"{minutes} minutes"


def _page_label(start: int | None, end: int | None) -> str:
    if start is None or end is None:
        return "—"
    if start == end:
        return str(start)
    return f"{start}–{end}"


def _chunk_page_label(chunk: dict) -> str:
    source_pages = chunk.get("source_pages") or []
    if source_pages:
        if len(source_pages) == 1:
            return str(source_pages[0])
        return f"{source_pages[0]}–{source_pages[-1]}"
    return _page_label(chunk.get("start_page"), chunk.get("end_page"))


def generate_study_indexes(output_dir: Path, config: SplitConfig) -> tuple[Path, Path]:
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    session = load_session(output_dir)
    chunks = manifest.get("chunks", [])
    source = manifest.get("source_file", "document")

    total_minutes = 0
    for chunk in chunks:
        minutes = int(chunk.get("word_count", 0) / config.reading_speed_wpm)
        chunk["estimated_minutes"] = max(1, minutes)
        total_minutes += chunk["estimated_minutes"]

    chapters: dict[str, list[dict]] = defaultdict(list)
    ungrouped: list[dict] = []
    for chunk in chunks:
        h1 = chunk.get("h1_chapter")
        if h1:
            chapters[h1].append(chunk)
        else:
            ungrouped.append(chunk)

    use_chapters = bool(chapters) and all(
        len(v) >= config.min_chunks_per_chapter for v in chapters.values()
    )

    fa_path = output_dir / "study-index-fa.md"
    en_path = output_dir / "study-index-en.md"
    fa_path.write_text(
        _render_index(source, chunks, chapters, ungrouped, use_chapters, session, config, "fa", total_minutes),
        encoding="utf-8",
    )
    en_path.write_text(
        _render_index(source, chunks, chapters, ungrouped, use_chapters, session, config, "en", total_minutes),
        encoding="utf-8",
    )
    return fa_path, en_path


def _render_index(
    source: str,
    chunks: list[dict],
    chapters: dict[str, list[dict]],
    ungrouped: list[dict],
    use_chapters: bool,
    session,
    config: SplitConfig,
    lang: str,
    total_minutes: int,
) -> str:
    if lang == "fa":
        lines = [f"# ایندکس مطالعاتی — {source}", "", "## نمای کلی", ""]
        lines.append(f"- تعداد کل بخش‌ها (جلسات مطالعه): {len(chunks)}")
        if use_chapters:
            lines.append(f"- تعداد فصل‌های مفهومی: {len(chapters)}")
        lines.append(f"- زمان تقریبی کل مطالعه: {_format_duration(total_minutes, lang)}")
        lines.extend(["", "## فهرست فصل‌ها و بخش‌ها", ""])
        header = "| # | فایل | عنوان بخش | موضوع | صفحات منبع | زمان تقریبی |"
    else:
        lines = [f"# Study Index — {source}", "", "## Overview", ""]
        lines.append(f"- Total study sessions: {len(chunks)}")
        if use_chapters:
            lines.append(f"- Conceptual chapters: {len(chapters)}")
        lines.append(f"- Estimated total study time: {_format_duration(total_minutes, lang)}")
        lines.extend(["", "## Chapters and Sections", ""])
        header = "| # | File | Section Title | Topic | Source Pages | Est. Study Time |"

    lines.append(header)
    lines.append("|---|---|---|---|---|---|")

    def row(chunk: dict) -> str:
        cid = chunk["id"]
        analysis = session.chunk_analyses.get(str(cid), {})
        topic = analysis.get(f"topic_{lang}", analysis.get("topic_en", "—"))
        pages = _chunk_page_label(chunk)
        mins = chunk.get("estimated_minutes", 1)
        time_label = f"~{mins} دقیقه" if lang == "fa" else f"~{mins} min"
        title = chunk.get("title", "—")
        filename = chunk.get("file", "—")
        return f"| {cid} | {filename} | {title} | {topic} | {pages} | {time_label} |"

    if use_chapters:
        chapter_num = 0
        for chapter_title, chapter_chunks in chapters.items():
            chapter_num += 1
            if lang == "fa":
                lines.append(f"### فصل {chapter_num}: {chapter_title}")
            else:
                lines.append(f"### Chapter {chapter_num}: {chapter_title}")
            lines.append("")
            for chunk in chapter_chunks:
                lines.append(row(chunk))
            lines.append("")
        for chunk in ungrouped:
            lines.append(row(chunk))
    else:
        for chunk in chunks:
            lines.append(row(chunk))

    return "\n".join(lines) + "\n"