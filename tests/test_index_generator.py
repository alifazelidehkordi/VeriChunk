import json
from pathlib import Path

import pytest

from doc_splitter.boundary.planner import SplitSession, save_session
from doc_splitter.config import SplitConfig
from doc_splitter.index_generator import commit_study_indexes, get_index_context


def _write_fixture(tmp_path: Path) -> None:
    chunks = [
        {
            "id": 1,
            "file": "01_intro.pdf",
            "title": "Intro",
            "word_count": 800,
            "source_pages": [1, 2],
            "h1_chapter": "Foundations",
        },
        {
            "id": 2,
            "file": "02_methods.pdf",
            "title": "Methods",
            "word_count": 600,
            "source_pages": [3, 4],
            "h1_chapter": "Foundations",
        },
        {
            "id": 3,
            "file": "03_results.pdf",
            "title": "Results",
            "word_count": 400,
            "source_pages": [5],
            "h1_chapter": "Analysis",
        },
        {
            "id": 4,
            "file": "04_discussion.pdf",
            "title": "Discussion",
            "word_count": 400,
            "source_pages": [6],
            "h1_chapter": "Analysis",
        },
    ]
    manifest = {
        "source_file": "book.pdf",
        "source_path": "/tmp/book.pdf",
        "total_chunks": 4,
        "chunks": chunks,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    session = SplitSession(
        source_file="book.pdf",
        output_dir=str(tmp_path),
        config={},
        stage="index",
        chunk_analyses={
            "1": {
                "topic_fa": "مقدمه",
                "topic_en": "Introduction",
                "study_focus_fa": "تعاریف پایه، اهداف آموزشی، و پیوند مفهومی این جلسه با بخش‌های بعدی.",
                "study_focus_en": "Core definitions, learning goals, and conceptual links to later sections.",
                "coherence": "confident",
            },
            "2": {
                "topic_fa": "روش‌ها",
                "topic_en": "Methods",
                "study_focus_fa": "گام‌های روش‌شناسی، ترتیب اجرا، و نکات مهم برای بازسازی روند.",
                "study_focus_en": "Methodology steps, execution order, and key points for reconstructing the workflow.",
                "coherence": "confident",
            },
            "3": {
                "topic_fa": "نتایج",
                "topic_en": "Results",
                "study_focus_fa": "یافته‌های کلیدی، الگوهای مقایسه، و ارتباط آن‌ها با پرسش اصلی.",
                "study_focus_en": "Key findings, comparison patterns, and how they connect to the main question.",
                "coherence": "confident",
            },
            "4": {
                "topic_fa": "بحث",
                "topic_en": "Discussion",
                "study_focus_fa": "تفسیر نتایج، محدودیت‌های اصلی، و نکاتی که برای مرور نهایی مهم هستند.",
                "study_focus_en": "Interpretation of results, main limitations, and points that matter for final review.",
                "coherence": "confident",
            },
        },
        chunks_read=[1, 2, 3, 4],
    )
    save_session(session, tmp_path)


def test_index_context_requires_agent_authored_commit(tmp_path: Path):
    _write_fixture(tmp_path)
    ctx = get_index_context(tmp_path, SplitConfig(reading_speed_wpm=200))

    assert ctx["status"] == "needs_agent_decision"
    assert ctx["total_chunks"] == 4
    assert ctx["chunks"][0]["topic_en"] == "Introduction"
    assert ctx["chunks"][0]["estimated_minutes"] == 4
    assert "Python has only prepared" in ctx["instructions"]
    assert "author the Markdown content yourself" in ctx["instructions"]

    fa_body = """# ایندکس مطالعاتی

| جلسه | فایل |
|---:|---|
| 1 | [مقدمه](01_intro.pdf) |
| 2 | [روش‌ها](02_methods.pdf) |
| 3 | [نتایج](03_results.pdf) |
| 4 | [بحث](04_discussion.pdf) |
"""
    en_body = """# Study Index

| Session | File |
|---:|---|
| 1 | [Introduction](01_intro.pdf) |
| 2 | [Methods](02_methods.pdf) |
| 3 | [Results](03_results.pdf) |
| 4 | [Discussion](04_discussion.pdf) |
"""
    fa_path, en_path = commit_study_indexes(
        tmp_path,
        index_fa=fa_body,
        index_en=en_body,
    )

    assert fa_path.read_text(encoding="utf-8") == fa_body
    assert en_path.read_text(encoding="utf-8") == en_body


def test_index_context_blocks_chunks_that_need_boundary_review(tmp_path: Path):
    _write_fixture(tmp_path)
    session = json.loads((tmp_path / ".split-session.json").read_text(encoding="utf-8"))
    session["chunk_analyses"]["2"]["coherence"] = "needs_review"
    (tmp_path / ".split-session.json").write_text(
        json.dumps(session),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="boundary/coherence review"):
        get_index_context(tmp_path, SplitConfig(reading_speed_wpm=200))
