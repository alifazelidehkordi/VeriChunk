from __future__ import annotations

from pathlib import Path

import pytest

from doc_splitter.boundary.planner import (
    SplitSession,
    commit_topic_change_reviews,
)
from doc_splitter.config import SplitConfig
from doc_splitter.ir.serialize import load_ir
from doc_splitter.topic_reviews import (
    build_topic_change_review_batch,
    find_topic_change_candidates,
)

GOLDEN_IR = Path(__file__).parent / "golden" / "ir"


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("topic_change_with_heading.json", ["el-005"]),
        ("topic_change_without_heading.json", ["el-004"]),
        ("subheading_same_topic.json", []),
        ("early_topic_change_before_minimum.json", ["el-003"]),
        ("continuous_topic_17_pages.json", []),
        ("continuous_topic_25_pages.json", []),
        ("table_on_topic_boundary.json", ["el-003"]),
        ("image_on_topic_boundary.json", ["el-003"]),
    ],
)
def test_semantic_candidates_match_golden_boundaries(fixture: str, expected: list[str]):
    ir = load_ir(GOLDEN_IR / fixture)

    candidates = find_topic_change_candidates(ir, SplitConfig())

    assert [candidate.boundary_element_id for candidate in candidates] == expected


def test_heading_free_shift_contains_bidirectional_evidence_context():
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")

    candidate = find_topic_change_candidates(ir, SplitConfig())[0]

    assert candidate.candidate_kind == "semantic_shift"
    assert candidate.semantic_score >= 0.8
    assert "el-004" in candidate.before_element_ids
    assert "el-005" in candidate.after_element_ids
    assert candidate.before_terms
    assert candidate.after_terms


def test_review_batch_assigns_three_independent_roles():
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")

    batch = build_topic_change_review_batch(ir, SplitConfig(), workers=2)
    tasks = [task for worker in batch["batches"] for task in worker]

    assert batch["total_boundaries"] == 1
    assert batch["total_tasks"] == 3
    assert {task["review_role"] for task in tasks} == {
        "transition_reviewer",
        "continuity_reviewer",
        "adjudicator",
    }
    assert all("[el-004]" in task["before_context"] for task in tasks)
    assert all("[el-005]" in task["after_context"] for task in tasks)
    assert all(task["document_summary"]["element_count"] == 8 for task in tasks)


def test_split_minority_prevents_automatic_merge(tmp_path: Path):
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    config = SplitConfig()
    session = SplitSession(
        source_file="shift.pdf",
        output_dir=str(tmp_path),
        config={},
        stage="topic_review",
    )
    task = build_topic_change_review_batch(ir, config, workers=1)["batches"][0][0]
    before = [task["before_element_ids"][-1]]
    after = [task["after_element_ids"][0]]

    result = commit_topic_change_reviews(
        ir,
        session,
        config,
        [
            {
                "review_id": task["review_id"],
                "reviewer_id": "split-reviewer",
                "decision": "split",
                "confidence": 0.8,
                "reason": "The learning objective changes from metabolism to contract law.",
                "evidence_before": before,
                "evidence_after": after,
            },
            {
                "review_id": task["review_id"],
                "reviewer_id": "merge-reviewer-a",
                "decision": "merge",
                "confidence": 0.7,
                "reason": "The transition might be an application within the same lesson.",
                "evidence_before": before,
                "evidence_after": after,
            },
            {
                "review_id": task["review_id"],
                "reviewer_id": "merge-reviewer-b",
                "decision": "merge",
                "confidence": 0.7,
                "reason": "The paragraphs could be intended as one composite exercise.",
                "evidence_before": before,
                "evidence_after": after,
            },
        ],
    )

    assert result["review_progress"]["complete"] is False
    assert session.topic_change_reviews[task["review_id"]]["consensus"] == "pending"
    assert session.stage == "topic_review"


def test_review_rejects_evidence_outside_supplied_context(tmp_path: Path):
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    config = SplitConfig()
    session = SplitSession(
        source_file="shift.pdf",
        output_dir=str(tmp_path),
        config={},
        stage="topic_review",
    )
    task = build_topic_change_review_batch(ir, config, workers=1)["batches"][0][0]

    with pytest.raises(ValueError, match="outside its context"):
        commit_topic_change_reviews(
            ir,
            session,
            config,
            [
                {
                    "review_id": task["review_id"],
                    "reviewer_id": "reviewer-a",
                    "decision": "split",
                    "confidence": 0.9,
                    "reason": "The two sides use unrelated learning objectives and vocabulary.",
                    "evidence_before": ["el-008"],
                    "evidence_after": [task["after_element_ids"][0]],
                }
            ],
        )
