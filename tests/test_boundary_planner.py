import pytest

from doc_splitter.boundary.planner import (
    SplitSession,
    commit_boundary,
    commit_topic_change_reviews,
    get_boundary_context,
)
from doc_splitter.topic_reviews import build_topic_change_review_batch
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element


def _paragraphs(n: int) -> list[Element]:
    return [
        Element(id=f"el-{i:03d}", type="paragraph", text=f"word{i} " * 50)
        for i in range(1, n + 1)
    ]


def test_get_boundary_context_offers_tail_candidates_when_remainder_is_short():
    ir = DocumentIR(elements=_paragraphs(12), meta=DocumentMeta(source_file="t.pdf"))
    ir.recompute_word_counts()
    session = SplitSession(
        source_file="t.pdf",
        output_dir="output",
        config={},
        cursor_index=10,
        window_pages=15,
    )
    config = SplitConfig(min_pages=5, max_pages=10, words_per_page=400)

    ctx = get_boundary_context(ir, session, config)

    assert ctx["status"] == "needs_agent_decision"
    assert ctx["safe_candidates"]
    assert ctx["safe_candidates"][-1]["element_id"] == "el-012"


def test_extend_requires_explicit_oversize_permission(tmp_path):
    ir = DocumentIR(elements=_paragraphs(3), meta=DocumentMeta(source_file="t.pdf"))
    session = SplitSession(source_file="t.pdf", output_dir=str(tmp_path), config={})
    config = SplitConfig()

    with pytest.raises(ValueError, match="allow_oversize=True"):
        commit_boundary(
            ir,
            session,
            config,
            action="extend",
            reason="The only coherent topic continues beyond the target range.",
        )


def test_trailing_page_number_is_merged_into_previous_chunk(tmp_path):
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="Meaningful content."),
            Element(id="el-002", type="paragraph", text="2", page_number=2),
        ],
        meta=DocumentMeta(source_file="t.pdf"),
    )
    session = SplitSession(
        source_file="t.pdf",
        output_dir=str(tmp_path),
        config={},
        boundaries=[{"start_index": 0, "end_index": 0, "end_element_id": "el-001"}],
        cursor_index=1,
    )
    config = SplitConfig()

    result = commit_boundary(
        ir,
        session,
        config,
        action="cut",
        element_id="el-002",
        reason="The terminal page footer belongs to the preceding completed section.",
    )

    assert result["status"] == "complete"
    assert len(session.boundaries) == 1
    assert session.boundaries[0]["end_element_id"] == "el-002"


def test_confirmed_topic_change_becomes_a_hard_boundary(tmp_path):
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="Foundations are established here."),
            Element(id="el-002", type="heading", level=1, text="INDEPENDENT TOPIC"),
            Element(id="el-003", type="paragraph", text="A new unrelated subject begins here."),
            Element(id="el-004", type="paragraph", text="The new subject continues."),
        ],
        meta=DocumentMeta(source_file="t.pdf"),
    )
    session = SplitSession(
        source_file="t.pdf",
        output_dir=str(tmp_path),
        config={},
        stage="topic_review",
    )
    config = SplitConfig(min_pages=1, max_pages=10)
    batch = build_topic_change_review_batch(ir, config, workers=2)
    task = batch["batches"][0][0]
    assert batch["reviewers_per_task"] == 2
    assert sum(
        1
        for worker_batch in batch["batches"]
        for candidate in worker_batch
        if candidate["review_id"] == task["review_id"]
    ) == 2

    result = commit_topic_change_reviews(
        ir,
        session,
        config,
        [
            {
                "review_id": task["review_id"],
                "reviewer_id": "reviewer-a",
                "decision": "split",
                "reason": "The heading begins a separate subject with no shared learning objective.",
            },
            {
                "review_id": task["review_id"],
                "reviewer_id": "reviewer-b",
                "decision": "split",
                "reason": "The following material introduces an independent topic rather than a subtopic.",
            },
        ],
    )

    assert result["confirmed_topic_boundaries"] == 1
    with pytest.raises(ValueError, match="confirmed topic change"):
        commit_boundary(
            ir,
            session,
            config,
            action="cut",
            element_id="el-003",
            reason="This would incorrectly combine two different learning units.",
            allow_topic_merge=True,
        )


def test_hard_page_cap_blocks_a_second_extension(tmp_path):
    ir = DocumentIR(elements=_paragraphs(3), meta=DocumentMeta(source_file="t.pdf"))
    session = SplitSession(
        source_file="t.pdf",
        output_dir=str(tmp_path),
        config={},
        window_pages=13,
    )
    config = SplitConfig(hard_max_pages=13)

    with pytest.raises(ValueError, match="hard_max_pages=13"):
        commit_boundary(
            ir,
            session,
            config,
            action="extend",
            allow_oversize=True,
            reason="No safe cut exists before the end of this continuous explanation.",
        )


def test_final_element_cannot_bypass_hard_page_cap(tmp_path):
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="Start", page_number=1),
            Element(id="el-002", type="paragraph", text="End", page_number=14),
        ],
        meta=DocumentMeta(source_file="t.pdf"),
    )
    session = SplitSession(source_file="t.pdf", output_dir=str(tmp_path), config={})

    with pytest.raises(ValueError, match="hard_max_pages=13"):
        commit_boundary(
            ir,
            session,
            SplitConfig(hard_max_pages=13),
            action="cut",
            element_id="el-002",
            reason="This would incorrectly keep a very long document as one study unit.",
        )
