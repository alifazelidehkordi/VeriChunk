import json
from pathlib import Path

from doc_splitter.boundary.planner import SplitSession, save_session
from doc_splitter.config import SplitConfig
from doc_splitter.index_generator import generate_study_indexes


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
                "study_focus_fa": "تعاریف پایه و اهداف.",
                "study_focus_en": "Core definitions and goals.",
                "coherence": "confident",
            },
            "2": {
                "topic_fa": "روش‌ها",
                "topic_en": "Methods",
                "study_focus_fa": "گام‌های روش‌شناسی.",
                "study_focus_en": "Methodology steps.",
                "coherence": "confident",
            },
            "3": {
                "topic_fa": "نتایج",
                "topic_en": "Results",
                "study_focus_fa": "یافته‌های کلیدی.",
                "study_focus_en": "Key findings.",
                "coherence": "confident",
            },
            "4": {
                "topic_fa": "بحث",
                "topic_en": "Discussion",
                "study_focus_fa": "تفسیر و محدودیت‌ها.",
                "study_focus_en": "Interpretation and limits.",
                "coherence": "confident",
            },
        },
    )
    save_session(session, tmp_path)


def test_generate_study_indexes_rich_structure(tmp_path: Path):
    _write_fixture(tmp_path)
    fa_path, en_path = generate_study_indexes(tmp_path, SplitConfig(reading_speed_wpm=200))

    fa = fa_path.read_text(encoding="utf-8")
    en = en_path.read_text(encoding="utf-8")

    assert "## نمای کلی" in fa
    assert "## Overview" in en
    assert "## فهرست فصل‌ها و گروه‌ها" in fa
    assert "## Table of Contents" in en
    assert "## روش پیشنهادی مطالعه" in fa
    assert "## Suggested Study Workflow" in en
    assert "تمرکز مطالعه" in fa
    assert "Study focus" in en
    assert "Core definitions and goals." in en
    assert "[Introduction](01_intro.pdf)" in en
    assert "1-2" in fa or "1–2" in fa