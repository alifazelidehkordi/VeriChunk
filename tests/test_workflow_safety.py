from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from doc_splitter.boundary.planner import (
    SessionConflictError,
    SplitSession,
    commit_boundary,
    get_boundary_context,
    load_session,
    save_session,
)
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.orchestrator import PipelineError, init_session, run_write_and_verify
from doc_splitter.topic_reviews import build_topic_change_review_batch
from doc_splitter.workflow import WorkflowStateError
from doc_splitter.writer import write_chunks


def _simple_ir() -> DocumentIR:
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="First coherent paragraph."),
            Element(id="el-002", type="paragraph", text="Second coherent paragraph."),
        ],
        meta=DocumentMeta(source_file="simple.docx"),
    )
    ir.recompute_word_counts()
    return ir


def _topic_ir() -> DocumentIR:
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="Foundational subject."),
            Element(id="el-002", type="heading", level=1, text="INDEPENDENT TOPIC"),
            Element(id="el-003", type="paragraph", text="A different learning objective."),
        ],
        meta=DocumentMeta(source_file="topics.docx"),
    )
    ir.recompute_word_counts()
    return ir


def _resolved_topic_review() -> dict:
    return {
        "topic-change:el-002": {
            "heading_element_id": "el-002",
            "heading_text": "INDEPENDENT TOPIC",
            "boundary_element_id": "el-001",
            "boundary_index": 0,
            "consensus": "split",
            "votes": {
                "reviewer-a": {"decision": "split", "reason": "independent subject"},
                "reviewer-b": {"decision": "split", "reason": "new objective"},
            },
        }
    }


def test_init_session_requires_topic_review_before_boundary_planning(tmp_path: Path):
    ir = _topic_ir()
    config = SplitConfig(output_dir=tmp_path, min_pages=1)

    session = init_session(Path("topics.docx"), config, ir)

    assert session.stage == "topic_review"
    with pytest.raises(WorkflowStateError, match="stage=topic_review"):
        get_boundary_context(ir, session, config)


def test_single_worker_still_receives_all_required_reviewer_slots():
    batch = build_topic_change_review_batch(
        _topic_ir(),
        SplitConfig(topic_change_min_votes=2),
        workers=1,
    )

    assert batch["recommended_workers"] == 1
    assert batch["reviewers_per_task"] == 3
    assert len(batch["batches"][0]) == 3
    assert {task["reviewer_slot"] for task in batch["batches"][0]} == {1, 2, 3}


def test_writer_rejects_incomplete_boundary_plan_without_creating_manifest(tmp_path: Path):
    ir = _simple_ir()
    session = SplitSession(
        source_file="simple.docx",
        output_dir=str(tmp_path),
        config={},
        stage="boundary_complete",
        cursor_index=1,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 0,
                "end_element_id": "el-001",
                "reason": "premature cut",
            }
        ],
    )

    with pytest.raises(ValueError, match="Boundary planning is incomplete"):
        write_chunks(ir, session, SplitConfig(output_dir=tmp_path), tmp_path)

    assert not (tmp_path / "manifest.json").exists()


def test_writer_rejects_unresolved_topic_reviews(tmp_path: Path):
    ir = _topic_ir()
    session = SplitSession(
        source_file="topics.docx",
        output_dir=str(tmp_path),
        config={},
        stage="boundary_complete",
        cursor_index=3,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 0,
                "end_element_id": "el-001",
                "reason": "candidate topic boundary",
            },
            {
                "start_index": 1,
                "end_index": 2,
                "end_element_id": "el-003",
                "reason": "document end",
            },
        ],
    )

    with pytest.raises(ValueError, match="Topic-change review is incomplete"):
        write_chunks(ir, session, SplitConfig(output_dir=tmp_path, min_pages=1), tmp_path)


def test_writer_rejects_plan_that_crosses_confirmed_topic_change(tmp_path: Path):
    ir = _topic_ir()
    session = SplitSession(
        source_file="topics.docx",
        output_dir=str(tmp_path),
        config={},
        stage="boundary_complete",
        cursor_index=3,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 2,
                "end_element_id": "el-003",
                "reason": "incorrect merged chunk",
            }
        ],
        topic_change_reviews=_resolved_topic_review(),
    )

    with pytest.raises(ValueError, match="crosses confirmed topic changes"):
        write_chunks(ir, session, SplitConfig(output_dir=tmp_path, min_pages=1), tmp_path)


def test_final_boundary_transitions_session_to_boundary_complete(tmp_path: Path):
    ir = _simple_ir()
    session = SplitSession(
        source_file="simple.docx",
        output_dir=str(tmp_path),
        config={},
        stage="boundary",
    )

    result = commit_boundary(
        ir,
        session,
        SplitConfig(min_pages=1, max_pages=10),
        action="cut",
        element_id="el-002",
        reason="The document ends after a complete coherent explanation.",
    )

    assert result["status"] == "complete"
    assert session.stage == "boundary_complete"
    assert load_session(tmp_path).stage == "boundary_complete"


def test_write_and_verify_advances_to_content_analysis(tmp_path: Path):
    ir = _simple_ir()
    session = SplitSession(
        source_file="simple.docx",
        output_dir=str(tmp_path),
        config={},
        stage="boundary_complete",
        cursor_index=2,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 1,
                "end_element_id": "el-002",
                "reason": "Complete coherent document.",
            }
        ],
    )
    save_session(session, tmp_path)

    report = run_write_and_verify(ir, SplitConfig(output_dir=tmp_path))

    assert report["passed"] is True
    assert load_session(tmp_path).stage == "content_analysis"


def test_stale_session_save_is_rejected_instead_of_losing_updates(tmp_path: Path):
    original = SplitSession(source_file="book.pdf", output_dir=str(tmp_path), config={})
    save_session(original, tmp_path)
    first = load_session(tmp_path)
    stale = load_session(tmp_path)

    first.chunks_read.append(1)
    save_session(first, tmp_path)
    stale.chunks_read.append(2)

    with pytest.raises(SessionConflictError, match="Session changed since it was loaded"):
        save_session(stale, tmp_path)

    assert load_session(tmp_path).chunks_read == [1]


def test_loaded_session_uses_current_output_directory_after_move(tmp_path: Path):
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    session = SplitSession(source_file="book.pdf", output_dir=str(old_dir), config={})
    save_session(session, old_dir)
    new_dir.mkdir()
    shutil.copy2(old_dir / ".split-session.json", new_dir / ".split-session.json")

    moved = load_session(new_dir)
    moved.chunks_read.append(1)
    save_session(moved, new_dir)

    assert moved.output_dir == str(new_dir.resolve())
    assert load_session(new_dir).chunks_read == [1]


def test_verification_failure_is_persisted_as_failed_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ir = _simple_ir()
    session = SplitSession(
        source_file="simple.docx",
        output_dir=str(tmp_path),
        config={},
        stage="boundary_complete",
        cursor_index=2,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 1,
                "end_element_id": "el-002",
                "reason": "Complete coherent document.",
            }
        ],
    )
    save_session(session, tmp_path)
    monkeypatch.setattr(
        "doc_splitter.orchestrator.verify_output",
        lambda *_args, **_kwargs: {"passed": False, "errors": ["forced failure"]},
    )

    with pytest.raises(PipelineError, match="forced failure"):
        run_write_and_verify(ir, SplitConfig(output_dir=tmp_path))

    failed = load_session(tmp_path)
    assert failed.stage == "failed"
    assert failed.failed_from == "verification"
    assert "forced failure" in (failed.last_error or "")
