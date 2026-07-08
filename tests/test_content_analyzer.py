import json
from pathlib import Path

from doc_splitter.boundary.planner import SplitSession, save_session
from doc_splitter.content.analyzer import commit_chunk_analysis


def _setup_session(tmp_path: Path, total_chunks: int = 2) -> None:
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
    result = commit_chunk_analysis(
        tmp_path,
        1,
        topic_fa="عنوان جلسه",
        topic_en="Session title",
        study_focus_fa="تمرکز آموزشی فارسی.",
        study_focus_en="Educational study focus in English.",
        coherence="confident",
        reason="cohesive",
    )
    assert result["status"] == "continue"

    session = json.loads((tmp_path / ".split-session.json").read_text(encoding="utf-8"))
    analysis = session["chunk_analyses"]["1"]
    assert analysis["study_focus_fa"] == "تمرکز آموزشی فارسی."
    assert analysis["study_focus_en"] == "Educational study focus in English."