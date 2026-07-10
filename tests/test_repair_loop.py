from __future__ import annotations

import json
from pathlib import Path

import pytest

from doc_splitter.boundary.planner import SplitSession, load_session, save_session
from doc_splitter.cli import main
from doc_splitter.config import SplitConfig
from doc_splitter.content.analyzer import commit_chunk_analysis
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.ir.serialize import save_ir
from doc_splitter.orchestrator import run_boundary_repair, run_index_context, run_write_and_verify
from doc_splitter.repair import get_boundary_repair_context
from doc_splitter.workflow import WorkflowStateError
from doc_splitter.writers.markdown_writer import extract_marked_section


def _ir() -> DocumentIR:
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="heading", level=1, text="FOUNDATIONS"),
            Element(
                id="el-002",
                type="paragraph",
                text="Foundational concepts and definitions remain cohesive.",
            ),
            Element(
                id="el-003",
                type="paragraph",
                text="The second unit introduces a separate diagnostic framework.",
            ),
            Element(
                id="el-004",
                type="paragraph",
                text="Diagnostic criteria and interpretation are explained here.",
            ),
            Element(
                id="el-005",
                type="paragraph",
                text="A third unit begins with treatment planning principles.",
            ),
            Element(
                id="el-006",
                type="paragraph",
                text="Treatment selection and follow-up complete the unit.",
            ),
        ],
        meta=DocumentMeta(source_file="repair.docx"),
    )
    ir.recompute_word_counts()
    return ir


def _setup_written_two_chunks(tmp_path: Path) -> SplitConfig:
    ir = _ir()
    save_ir(ir, tmp_path / "ir.json")
    config = SplitConfig(output_dir=tmp_path, min_pages=1, output_format="markdown")
    session = SplitSession(
        source_file="repair.docx",
        output_dir=str(tmp_path),
        config={
            "source_path": None,
            "output_dir": str(tmp_path),
            "min_pages": 1,
            "max_pages": 12,
            "soft_max_pages": 13,
            "hard_max_pages": 20,
            "output_format": "markdown",
        },
        stage="boundary_complete",
        cursor_index=6,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 1,
                "end_element_id": "el-002",
                "reason": "The introductory unit ends after its complete definition.",
            },
            {
                "start_index": 2,
                "end_index": 5,
                "end_element_id": "el-006",
                "reason": "The original second chunk reached the end of the document.",
            },
        ],
    )
    save_session(session, tmp_path)
    report = run_write_and_verify(ir, config)
    assert report["passed"] is True
    return config


def _commit_analysis(tmp_path: Path, chunk_id: int, coherence: str, topic: str) -> dict:
    return commit_chunk_analysis(
        tmp_path,
        chunk_id,
        topic_fa="عنوان آموزشی معتبر",
        topic_en=topic,
        study_focus_fa="تمرکز آموزشی شامل مفاهیم کلیدی، مثال‌ها و اهداف اصلی این بخش است.",
        study_focus_en="Study the key concepts, examples, decisions, and learning goals in this unit.",
        coherence=coherence,
        reason=(
            "This chunk combines diagnostic and treatment learning objectives that require a new boundary."
            if coherence == "needs_review"
            else "The chunk forms one coherent and independently useful learning unit."
        ),
    )


def test_needs_review_enters_enforced_boundary_repair_stage(tmp_path: Path):
    _setup_written_two_chunks(tmp_path)
    _commit_analysis(tmp_path, 1, "confident", "Foundational Concepts")
    result = _commit_analysis(tmp_path, 2, "needs_review", "Mixed Diagnostic and Treatment Unit")

    assert result["status"] == "needs_boundary_repair"
    assert result["stage"] == "boundary_repair"
    session = load_session(tmp_path)
    assert session.stage == "boundary_repair"
    assert session.repair_queue == [
        {
            "chunk_id": 2,
            "start_index": 2,
            "end_index": 5,
            "reason": "This chunk combines diagnostic and treatment learning objectives that require a new boundary.",
        }
    ]


def test_repair_context_only_offers_internal_safe_boundaries(tmp_path: Path):
    _setup_written_two_chunks(tmp_path)
    _commit_analysis(tmp_path, 1, "confident", "Foundational Concepts")
    _commit_analysis(tmp_path, 2, "needs_review", "Mixed Diagnostic and Treatment Unit")

    context = get_boundary_repair_context(tmp_path, 2)

    ids = {item["element_id"] for item in context["safe_cut_candidates"]}
    assert "el-004" in ids
    assert "el-006" not in ids
    assert "[el-005]" in context["content"]


def test_repair_splits_chunk_reverifies_and_preserves_unchanged_analysis(tmp_path: Path):
    config = _setup_written_two_chunks(tmp_path)
    _commit_analysis(tmp_path, 1, "confident", "Foundational Concepts")
    before_manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    unchanged_before = next(c for c in before_manifest["chunks"] if c["id"] == 1)
    unchanged_body_before = extract_marked_section(
        (tmp_path / unchanged_before["file"]).read_text(encoding="utf-8")
    )
    _commit_analysis(tmp_path, 2, "needs_review", "Mixed Diagnostic and Treatment Unit")

    result = run_boundary_repair(
        config,
        chunk_id=2,
        cut_element_ids=["el-004"],
        reason="Diagnostics conclude before treatment planning starts as a separate learning objective.",
    )

    assert result["status"] == "repair_applied"
    assert result["verification"]["passed"] is True
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [(c["start_index"], c["end_index"]) for c in manifest["chunks"]] == [
        (0, 1),
        (2, 3),
        (4, 5),
    ]
    assert manifest["write_summary"] == {
        "mode": "repair",
        "reused_chunk_bodies": [1],
        "rewritten_chunks": [2, 3],
    }
    unchanged_after = next(c for c in manifest["chunks"] if c["start_index"] == 0)
    assert (
        extract_marked_section((tmp_path / unchanged_after["file"]).read_text(encoding="utf-8"))
        == unchanged_body_before
    )
    session = load_session(tmp_path)
    assert session.stage == "content_analysis"
    assert session.chunk_analyses["1"]["topic_en"] == "Foundational Concepts"
    assert "2" not in session.chunk_analyses
    assert "3" not in session.chunk_analyses
    assert session.active_repair is None
    assert session.repair_queue == []
    assert session.repair_history[-1]["old_range"] == [2, 5]
    assert session.repair_history[-1]["new_ranges"] == [[2, 3], [4, 5]]


def test_repair_rejects_cut_outside_queued_chunk(tmp_path: Path):
    config = _setup_written_two_chunks(tmp_path)
    _commit_analysis(tmp_path, 1, "confident", "Foundational Concepts")
    _commit_analysis(tmp_path, 2, "needs_review", "Mixed Diagnostic and Treatment Unit")

    with pytest.raises(ValueError, match="internal to the queued chunk"):
        run_boundary_repair(
            config,
            chunk_id=2,
            cut_element_ids=["el-002"],
            reason="An invalid repair attempt should not cross the queued chunk boundary.",
        )


def test_repair_context_is_unavailable_before_analysis_flags_a_problem(tmp_path: Path):
    _setup_written_two_chunks(tmp_path)
    with pytest.raises(WorkflowStateError, match="stage=content_analysis"):
        get_boundary_repair_context(tmp_path, 2)


def test_cli_repair_command_runs_full_repair_cycle(tmp_path: Path):
    _setup_written_two_chunks(tmp_path)
    _commit_analysis(tmp_path, 1, "confident", "Foundational Concepts")
    _commit_analysis(tmp_path, 2, "needs_review", "Mixed Diagnostic and Treatment Unit")

    code = main(
        [
            "repair-boundary",
            "--out",
            str(tmp_path),
            "--chunk-id",
            "2",
            "--cut-element-id",
            "el-004",
            "--reason",
            "Diagnostics conclude before treatment planning begins as a new learning objective.",
        ]
    )

    assert code == 0
    assert load_session(tmp_path).stage == "content_analysis"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["total_chunks"] == 3


def test_index_is_locked_while_boundary_repair_is_pending(tmp_path: Path):
    config = _setup_written_two_chunks(tmp_path)
    _commit_analysis(tmp_path, 1, "confident", "Foundational Concepts")
    _commit_analysis(tmp_path, 2, "needs_review", "Mixed Diagnostic and Treatment Unit")

    with pytest.raises(WorkflowStateError, match="stage=boundary_repair"):
        run_index_context(config)
