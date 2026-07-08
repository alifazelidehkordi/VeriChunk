"""Generate rich bilingual study indexes from manifest and content analyses."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from doc_splitter.boundary.planner import SplitSession, load_session
from doc_splitter.config import SplitConfig
from doc_splitter.naming import slugify

BOOK_PAGES_PLACEHOLDER = "—"


@dataclass
class ChapterGroup:
    index: int
    title: str
    anchor: str
    chunks: list[dict]
    topic_summary: str = ""

    @property
    def session_ids(self) -> list[int]:
        return [int(c["id"]) for c in self.chunks]

    @property
    def session_range(self) -> str:
        ids = self.session_ids
        if not ids:
            return "—"
        if len(ids) == 1:
            return str(ids[0])
        return f"{ids[0]}-{ids[-1]}"

    @property
    def total_minutes(self) -> int:
        return sum(int(c.get("estimated_minutes", 1)) for c in self.chunks)

    def page_range_label(self) -> str:
        pages = _all_source_pages(self.chunks)
        if not pages:
            return BOOK_PAGES_PLACEHOLDER
        if pages[0] == pages[-1]:
            return str(pages[0])
        return f"{pages[0]}–{pages[-1]}"


def _format_duration(total_minutes: int, lang: str) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if lang == "fa":
        if hours:
            return f"{hours} ساعت و {minutes} دقیقه"
        return f"{minutes} دقیقه"
    if hours:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    return f"{minutes} min"


def _chunk_page_label(chunk: dict) -> str:
    source_pages = chunk.get("source_pages") or []
    if source_pages:
        if len(source_pages) == 1:
            return str(source_pages[0])
        return f"{source_pages[0]}–{source_pages[-1]}"
    start = chunk.get("start_page")
    end = chunk.get("end_page")
    if start is None or end is None:
        return BOOK_PAGES_PLACEHOLDER
    if start == end:
        return str(start)
    return f"{start}–{end}"


def _all_source_pages(chunks: list[dict]) -> list[int]:
    pages: set[int] = set()
    for chunk in chunks:
        for page in chunk.get("source_pages") or []:
            pages.add(int(page))
        start = chunk.get("start_page")
        end = chunk.get("end_page")
        if start is not None:
            pages.add(int(start))
        if end is not None:
            pages.add(int(end))
    return sorted(pages)


def _anchor_slug(title: str, lang: str, index: int) -> str:
    base = slugify(title, max_length=40) or f"group-{index}"
    suffix = "fa" if lang == "fa" else "en"
    return f"{base}-{suffix}"


def _truncate(text: str, max_len: int = 120) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _chapter_topic_summary(chunks: list[dict], session: SplitSession, lang: str) -> str:
    topics: list[str] = []
    for chunk in chunks[:3]:
        analysis = session.chunk_analyses.get(str(chunk["id"]), {})
        topic = analysis.get(f"topic_{lang}", analysis.get("topic_en", ""))
        if topic and topic not in topics:
            topics.append(topic)
    if not topics:
        return BOOK_PAGES_PLACEHOLDER
    return _truncate("؛ ".join(topics) if lang == "fa" else "; ".join(topics))


def _build_chapter_groups(
    chunks: list[dict],
    session: SplitSession,
    config: SplitConfig,
    lang: str,
) -> list[ChapterGroup]:
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

    groups: list[ChapterGroup] = []
    if use_chapters:
        for i, (title, chapter_chunks) in enumerate(chapters.items(), start=1):
            groups.append(
                ChapterGroup(
                    index=i,
                    title=title,
                    anchor=_anchor_slug(title, lang, i),
                    chunks=chapter_chunks,
                    topic_summary=_chapter_topic_summary(chapter_chunks, session, lang),
                )
            )
        if ungrouped:
            other_title = "سایر" if lang == "fa" else "Other"
            groups.append(
                ChapterGroup(
                    index=len(groups) + 1,
                    title=other_title,
                    anchor=_anchor_slug(other_title, lang, len(groups) + 1),
                    chunks=ungrouped,
                    topic_summary=_chapter_topic_summary(ungrouped, session, lang),
                )
            )
        return groups

    fallback_title = "کل سند" if lang == "fa" else "Full Document"
    return [
        ChapterGroup(
            index=1,
            title=fallback_title,
            anchor=_anchor_slug(fallback_title, lang, 1),
            chunks=chunks,
            topic_summary=_chapter_topic_summary(chunks, session, lang),
        )
    ]


def _source_link(manifest: dict) -> tuple[str, str | None]:
    source_file = manifest.get("source_file", "document")
    source_path = manifest.get("source_path")
    if source_path:
        path = Path(source_path)
        if path.is_file():
            return source_file, path.name
    return source_file, None


def _overview_section(
    source: str,
    source_filename: str | None,
    chunks: list[dict],
    groups: list[ChapterGroup],
    lang: str,
    total_minutes: int,
) -> list[str]:
    all_pages = _all_source_pages(chunks)
    page_coverage = BOOK_PAGES_PLACEHOLDER
    if all_pages:
        page_coverage = (
            str(all_pages[0])
            if all_pages[0] == all_pages[-1]
            else f"{all_pages[0]}–{all_pages[-1]}"
        )

    if lang == "fa":
        lines = ["## نمای کلی", ""]
        if source_filename:
            lines.append(f"- منبع: [{source}]({quote(source_filename)})")
        else:
            lines.append(f"- منبع: {source}")
        lines.append(f"- تعداد جلسات مطالعه: {len(chunks)}")
        lines.append(f"- پوشش صفحات PDF: {page_coverage}")
        lines.append(f"- زمان کل تخمینی: {_format_duration(total_minutes, lang)}")
        lines.append(f"- تعداد فصل‌ها/گروه‌ها: {len(groups)}")
        lines.append("- صفحات کتاب در این خروجی قابل استخراج نبودند؛ ستون «صفحات کتاب» با `—` مشخص شده است.")
        lines.append("- هر عنوان جلسه به فایل همان جلسه لینک شده است.")
    else:
        lines = ["## Overview", ""]
        if source_filename:
            lines.append(f"- Source: [{source}]({quote(source_filename)})")
        else:
            lines.append(f"- Source: {source}")
        lines.append(f"- Total study sessions: {len(chunks)}")
        lines.append(f"- PDF page coverage: {page_coverage}")
        lines.append(f"- Total estimated study time: {_format_duration(total_minutes, lang)}")
        lines.append(f"- Chapter/group count: {len(groups)}")
        lines.append("- Printed book pages were not available; book-page cells use `—`.")
        lines.append("- Every session title links to the corresponding chunk file.")
    return lines


def _chapter_summary_table(groups: list[ChapterGroup], lang: str) -> list[str]:
    if lang == "fa":
        lines = ["## فهرست فصل‌ها و گروه‌ها", ""]
        header = "| فصل/بخش | موضوع | جلسات | صفحات PDF | صفحات کتاب | زمان تقریبی |"
    else:
        lines = ["## Table of Contents", ""]
        header = "| Chapter/Group | Topic | Sessions | PDF pages | Book pages | Estimated time |"
    lines.append(header)
    lines.append("|---|---|---:|---:|---:|---:|")
    for group in groups:
        chapter_link = f"[{group.title}](#{group.anchor})"
        lines.append(
            f"| {chapter_link} | {group.topic_summary} | {group.session_range} | "
            f"{group.page_range_label()} | {BOOK_PAGES_PLACEHOLDER} | "
            f"{_format_duration(group.total_minutes, lang)} |"
        )
    lines.append("")
    return lines


def _study_workflow_section(lang: str) -> list[str]:
    if lang == "fa":
        return [
            "## روش پیشنهادی مطالعه",
            "",
            "1. PDF جلسه را باز کنید و ابتدا تیترها، شکل‌ها و جدول‌های همان بازه را سریع مرور کنید.",
            "2. زنجیره اصلی را مشخص کنید: مسیر متابولیک، الگوریتم تشخیصی، مکانیسم بیماری یا منطق انتخاب تست.",
            "3. برای هر مفهوم کلیدی، تعاریف، مراحل، آستانه‌ها و استثناهای مهم را جدا یادداشت کنید.",
            "4. در جلسات بیماری‌محور، یافته‌ها را به پاتوفیزیولوژی و تصمیم بالینی وصل کنید.",
            "5. در پایان، از خودتان بخواهید الگوریتم یا مقایسه‌های اصلی همان جلسه را بدون نگاه‌کردن بازسازی کنید.",
            "",
        ]
    return [
        "## Suggested Study Workflow",
        "",
        "1. Open the session file and skim headings, figures, and tables for the covered range.",
        "2. Identify the main chain: metabolic pathway, diagnostic algorithm, disease mechanism, or test-selection logic.",
        "3. For each key concept, note definitions, steps, thresholds, and important exceptions.",
        "4. In disease-focused sessions, connect findings to pathophysiology and clinical decisions.",
        "5. Finish by reconstructing the main algorithm or comparison table from memory.",
        "",
    ]


def _session_topic_link(chunk: dict, session: SplitSession, lang: str) -> str:
    analysis = session.chunk_analyses.get(str(chunk["id"]), {})
    topic = analysis.get(f"topic_{lang}") or analysis.get("topic_en")
    if not topic:
        topic = chunk.get("inferred_topic") or chunk.get("title", "—")
    filename = chunk.get("file", "")
    if filename:
        return f"[{topic}]({quote(filename)})"
    return topic or "—"


def _study_focus(chunk: dict, session: SplitSession, lang: str) -> str:
    analysis = session.chunk_analyses.get(str(chunk["id"]), {})
    focus = analysis.get(f"study_focus_{lang}", "")
    if focus:
        return focus
    return analysis.get(f"topic_{lang}", analysis.get("topic_en", "—"))


def _chapter_sections(
    groups: list[ChapterGroup],
    session: SplitSession,
    lang: str,
) -> list[str]:
    lines: list[str] = []
    for group in groups:
        session_count = len(group.chunks)
        if lang == "fa":
            lines.append(f"## {group.title} <a id=\"{group.anchor}\"></a>")
            lines.append("")
            lines.append(
                f"{session_count} جلسه · صفحات PDF {group.page_range_label()} · "
                f"صفحات کتاب {BOOK_PAGES_PLACEHOLDER} · "
                f"زمان تقریبی: {_format_duration(group.total_minutes, lang)}"
            )
            lines.append("")
            lines.append(
                "| جلسه | موضوع | صفحات PDF | صفحات کتاب | زمان | تمرکز مطالعه |"
            )
        else:
            lines.append(f"## {group.title} <a id=\"{group.anchor}\"></a>")
            lines.append("")
            lines.append(
                f"{session_count} sessions · PDF pages {group.page_range_label()} · "
                f"Book pages {BOOK_PAGES_PLACEHOLDER} · "
                f"Estimated time: {_format_duration(group.total_minutes, lang)}"
            )
            lines.append("")
            lines.append(
                "| Session | Topic | PDF pages | Book pages | Time | Study focus |"
            )
        lines.append("|---:|---|---:|---:|---:|---|")
        for chunk in group.chunks:
            cid = chunk["id"]
            mins = chunk.get("estimated_minutes", 1)
            time_label = f"{mins} دقیقه" if lang == "fa" else f"{mins} min"
            lines.append(
                f"| {cid} | {_session_topic_link(chunk, session, lang)} | "
                f"{_chunk_page_label(chunk)} | {BOOK_PAGES_PLACEHOLDER} | {time_label} | "
                f"{_study_focus(chunk, session, lang)} |"
            )
        lines.append("")
    return lines


def _render_index(
    manifest: dict,
    chunks: list[dict],
    session: SplitSession,
    config: SplitConfig,
    lang: str,
    total_minutes: int,
) -> str:
    source, source_filename = _source_link(manifest)
    groups = _build_chapter_groups(chunks, session, config, lang)

    if lang == "fa":
        lines = [f"# ایندکس مطالعاتی — {source}", ""]
    else:
        lines = [f"# Study Index — {source}", ""]

    lines.extend(_overview_section(source, source_filename, chunks, groups, lang, total_minutes))
    lines.append("")
    lines.extend(_chapter_summary_table(groups, lang))
    lines.extend(_study_workflow_section(lang))
    lines.extend(_chapter_sections(groups, session, lang))
    return "\n".join(lines) + "\n"


def generate_study_indexes(output_dir: Path, config: SplitConfig) -> tuple[Path, Path]:
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    session = load_session(output_dir)
    chunks = manifest.get("chunks", [])

    total_minutes = 0
    for chunk in chunks:
        minutes = int(chunk.get("word_count", 0) / config.reading_speed_wpm)
        chunk["estimated_minutes"] = max(1, minutes)
        total_minutes += chunk["estimated_minutes"]

    fa_path = output_dir / "study-index-fa.md"
    en_path = output_dir / "study-index-en.md"
    fa_path.write_text(
        _render_index(manifest, chunks, session, config, "fa", total_minutes),
        encoding="utf-8",
    )
    en_path.write_text(
        _render_index(manifest, chunks, session, config, "en", total_minutes),
        encoding="utf-8",
    )
    return fa_path, en_path