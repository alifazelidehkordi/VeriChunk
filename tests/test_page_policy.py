from __future__ import annotations

from pathlib import Path

import pytest

from doc_splitter.boundary.planner import (
    SplitSession,
    commit_boundary,
    get_boundary_context,
)
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.ir.serialize import load_ir

GOLDEN_IR = Path(__file__).parent / "golden" / "ir"


def _paged_ir(pages: int) -> DocumentIR:
    ir = DocumentIR(
        elements=[
            Element(
                id=f"el-{page:03d}",
                type="paragraph",
                text=f"Connected explanation on page {page} continues the same topic.",
                page_number=page,
            )
            for page in range(1, pages + 1)
        ],
        meta=DocumentMeta(source_file="continuous.pdf", estimated_total_pages=pages),
    )
    ir.recompute_word_counts()
    return ir


def test_default_page_policy_is_12_13_20():
    config = SplitConfig()

    assert config.max_pages == 12
    assert config.soft_max_pages == 13
    assert config.hard_max_pages == 20
    assert config.boundary_window_extension_pages == 1


def test_absolute_page_cap_cannot_be_configured_above_twenty():
    with pytest.raises(ValueError, match="absolute cap of 20"):
        SplitConfig(hard_max_pages=21, soft_max_pages=13)


def test_extension_to_page_thirteen_does_not_require_continuity_panel(tmp_path: Path):
    ir = _paged_ir(17)
    session = SplitSession(
        source_file="continuous.pdf",
        output_dir=str(tmp_path),
        config={},
        window_pages=12,
    )

    result = commit_boundary(
        ir,
        session,
        SplitConfig(),
        action="extend",
        allow_oversize=True,
        reason="The same immune-response argument continues through its final supporting example.",
    )

    assert result["window_pages"] == 13
    assert result["extension"]["semantic_evidence_required"] is False


def test_extension_beyond_thirteen_requires_two_reviewers_and_evidence(tmp_path: Path):
    ir = _paged_ir(17)
    session = SplitSession(
        source_file="continuous.pdf",
        output_dir=str(tmp_path),
        config={},
        window_pages=13,
    )
    config = SplitConfig()

    with pytest.raises(ValueError, match="independent continuity reviewers"):
        commit_boundary(
            ir,
            session,
            config,
            action="extend",
            allow_oversize=True,
            reason="The derivation is still one inseparable argument on the next page.",
        )

    result = commit_boundary(
        ir,
        session,
        config,
        action="extend",
        allow_oversize=True,
        reason="The derivation is still one inseparable argument on the next page.",
        continuity_evidence=["el-013", "el-014"],
        continuity_reviewers=["reviewer-a", "reviewer-b"],
    )

    assert result["window_pages"] == 14
    assert result["extension"]["semantic_evidence_required"] is True
    assert result["extension"]["reviewer_ids"] == ["reviewer-a", "reviewer-b"]


def test_confirmed_topic_change_blocks_extension(tmp_path: Path):
    ir = _paged_ir(17)
    session = SplitSession(
        source_file="continuous.pdf",
        output_dir=str(tmp_path),
        config={},
        window_pages=12,
        topic_change_reviews={
            "topic-change:el-013": {
                "consensus": "split",
                "boundary_index": 11,
                "boundary_element_id": "el-012",
                "heading_text": "Independent topic",
            }
        },
    )

    with pytest.raises(ValueError, match="confirmed topic change"):
        commit_boundary(
            ir,
            session,
            SplitConfig(),
            action="extend",
            allow_oversize=True,
            reason="The next page should be included despite the detected transition.",
        )


def test_topic_change_before_minimum_is_still_a_required_candidate(tmp_path: Path):
    ir = load_ir(GOLDEN_IR / "early_topic_change_before_minimum.json")
    session = SplitSession(
        source_file="early.pdf",
        output_dir=str(tmp_path),
        config={},
        window_pages=12,
        topic_change_reviews={
            "topic-change:el-004": {
                "consensus": "split",
                "boundary_index": 2,
                "boundary_element_id": "el-003",
                "heading_element_id": "el-004",
                "heading_text": "CARDIAC ELECTROPHYSIOLOGY",
                "votes": {
                    "a": {"decision": "split"},
                    "b": {"decision": "split"},
                },
            }
        },
    )

    context = get_boundary_context(ir, session, SplitConfig(min_pages=5))

    assert context["required_topic_boundary"]["boundary_element_id"] == "el-003"
    assert [item["element_id"] for item in context["safe_candidates"]] == ["el-003"]


def test_hard_cap_produces_forced_continuation_metadata(tmp_path: Path):
    ir = _paged_ir(25)
    session = SplitSession(
        source_file="continuous.pdf",
        output_dir=str(tmp_path),
        config={},
        window_pages=20,
    )
    config = SplitConfig()

    context = get_boundary_context(ir, session, config)
    result = commit_boundary(
        ir,
        session,
        config,
        action="cut",
        element_id="el-020",
        reason="The absolute page cap requires a continuation split at the last safe point.",
    )

    assert context["status"] == "requires_forced_size_split"
    assert context["hard_max_pages"] == 20
    assert result["boundary"]["split_type"] == "forced_size_split"
    assert result["boundary"]["continues_to_next"] is True
    assert session.window_pages == 12


def test_writer_rejects_missing_extension_approval_steps():
    from doc_splitter.writer import validate_boundary_plan

    ir = _paged_ir(14)
    session = SplitSession(
        source_file="continuous.pdf",
        output_dir="output",
        config={},
        stage="boundary_complete",
        cursor_index=14,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 13,
                "end_element_id": "el-014",
                "reason": "One continuous topic.",
                "extension_evidence": [],
            }
        ],
    )

    with pytest.raises(ValueError, match="Missing approvals for page limits: \\[14\\]"):
        validate_boundary_plan(ir, session, SplitConfig())


def test_writer_accepts_complete_extension_approval_steps():
    from doc_splitter.writer import validate_boundary_plan

    ir = _paged_ir(14)
    session = SplitSession(
        source_file="continuous.pdf",
        output_dir="output",
        config={},
        stage="boundary_complete",
        cursor_index=14,
        boundaries=[
            {
                "start_index": 0,
                "end_index": 13,
                "end_element_id": "el-014",
                "reason": "One continuous topic.",
                "extension_evidence": [
                    {
                        "to_pages": 14,
                        "evidence_element_ids": ["el-012", "el-013"],
                        "reviewer_ids": ["reviewer-a", "reviewer-b"],
                    }
                ],
            }
        ],
    )

    assert validate_boundary_plan(ir, session, SplitConfig()) == [(0, 13)]
