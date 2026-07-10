import json
from pathlib import Path

import pytest

from doc_splitter.boundary.planner import SplitSession, save_session
from doc_splitter.content.analyzer import commit_chunk_analysis, get_chunk_analysis_context
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.ir.serialize import save_ir


def _setup_session(tmp_path: Path, total_chunks: int = 2) -> None:
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="RECURSIVE TREE TRAVERSAL"),
            Element(id="el-002", type="paragraph", text="Body text about visiting nodes in order."),
        ],
        meta=DocumentMeta(source_file="sample.pdf"),
    )
    save_ir(ir, tmp_path / "ir.json")
    session = SplitSession(
        source_file="sample.pdf",
        output_dir=str(tmp_path),
        config={},
        stage="content_analysis",
    )
    save_session(session, tmp_path)
    manifest = {
        "source_file": "sample.pdf",
        "total_chunks": total_chunks,
        "chunks": [{"id": i, "file": f"{i:02d}_chunk.pdf"} for i in range(1, total_chunks + 1)],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_commit_chunk_analysis_stores_study_focus(tmp_path: Path):
    _setup_session(tmp_path)
    (tmp_path / "01_chunk.pdf").write_text("chunk one", encoding="utf-8")
    result = commit_chunk_analysis(
        tmp_path,
        1,
        topic_fa="عنوان جلسه",
        topic_en="Session title",
        study_focus_fa="تمرکز آموزشی: مفاهیم کلیدی، مثال‌های اصلی و اهداف یادگیری این جلسه.",
        study_focus_en="Educational study focus in English with key concepts.",
        coherence="confident",
        reason="cohesive",
    )
    assert result["status"] == "continue"

    session = json.loads((tmp_path / ".split-session.json").read_text(encoding="utf-8"))
    analysis = session["chunk_analyses"]["1"]
    assert analysis["study_focus_fa"] == "تمرکز آموزشی: مفاهیم کلیدی، مثال‌های اصلی و اهداف یادگیری این جلسه."
    assert analysis["study_focus_en"] == "Educational study focus in English with key concepts."

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["chunks"][0]["file"] == "01_session-title.pdf"
    assert manifest["chunks"][0]["title"] == "Session title"
    assert (tmp_path / "01_session-title.pdf").exists()
    assert not (tmp_path / "01_chunk.pdf").exists()


def test_get_chunk_analysis_context_includes_section_headings(tmp_path: Path):
    _setup_session(tmp_path, total_chunks=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["chunks"][0].update(
        {
            "start_index": 0,
            "end_index": 1,
            "file": "01_intro.md",
            "markdown_file": "01_intro.md",
        }
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "01_intro.md").write_text("# INTRODUCTION\n\nBody text.", encoding="utf-8")

    ctx = get_chunk_analysis_context(tmp_path, 1)
    assert ctx["section_headings"] == ["RECURSIVE TREE TRAVERSAL"]
    assert ctx["provisional_topic"] == "RECURSIVE TREE TRAVERSAL"
    session = json.loads((tmp_path / ".split-session.json").read_text(encoding="utf-8"))
    assert session["chunks_read"] == [1]


def test_commit_chunk_analysis_rejects_sentence_topic(tmp_path: Path):
    _setup_session(tmp_path)
    with pytest.raises(ValueError, match="body sentence"):
        commit_chunk_analysis(
            tmp_path,
            1,
            topic_fa="جمله بلند",
            topic_en="Recursive calls are useful because they simplify repeated work.",
            study_focus_fa="تمرکز آموزشی کافی برای این جلسه با مفاهیم کلیدی و کاربردها.",
            study_focus_en="Key concepts and applications to study in this session with enough detail.",
            coherence="confident",
            reason="Chunk covers traversal concepts cohesively with examples.",
        )


def test_commit_chunk_analysis_rejects_auto_from_section_headings_reason(tmp_path: Path):
    _setup_session(tmp_path)
    (tmp_path / "01_chunk.pdf").write_text("chunk one", encoding="utf-8")
    with pytest.raises(ValueError, match="not acceptable"):
        commit_chunk_analysis(
            tmp_path,
            1,
            topic_fa="عنوان جلسه",
            topic_en="Session title",
            study_focus_fa="تمرکز آموزشی: مفاهیم کلیدی، مثال‌های اصلی و اهداف یادگیری این جلسه.",
            study_focus_en="Educational study focus in English with key concepts.",
            coherence="confident",
            reason="auto from section_headings",
        )


def test_commit_chunk_analysis_rejects_empty_reason(tmp_path: Path):
    _setup_session(tmp_path)
    (tmp_path / "01_chunk.pdf").write_text("chunk one", encoding="utf-8")
    with pytest.raises(ValueError, match="must not be empty"):
        commit_chunk_analysis(
            tmp_path,
            1,
            topic_fa="عنوان جلسه",
            topic_en="Session title",
            study_focus_fa="تمرکز آموزشی: مفاهیم کلیدی، مثال‌های اصلی و اهداف یادگیری این جلسه.",
            study_focus_en="Educational study focus in English with key concepts.",
            coherence="confident",
        )
