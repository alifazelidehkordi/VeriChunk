from __future__ import annotations

import asyncio
from pathlib import Path

from doc_splitter.agents import HeuristicAgentBackend, run_review_batch
from doc_splitter.boundary.planner import (
    commit_boundary,
    commit_topic_change_reviews,
    get_boundary_context,
    load_session,
)
from doc_splitter.config import SplitConfig
from doc_splitter.ir.serialize import load_ir, save_ir
from doc_splitter.orchestrator import init_session, run_write_and_verify
from doc_splitter.topic_reviews import build_topic_change_review_batch

GOLDEN_IR = Path(__file__).parent / "golden" / "ir"


def test_heading_free_topic_change_completes_end_to_end(tmp_path: Path):
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    config = SplitConfig(output_dir=tmp_path)
    save_ir(ir, tmp_path / "ir.json")
    session = init_session(Path("heading-free.pdf"), config, ir)
    assert session.stage == "topic_review"

    batch = build_topic_change_review_batch(ir, config, workers=3)
    reviews = asyncio.run(
        run_review_batch(batch, HeuristicAgentBackend(), workers=3)
    )
    commit_topic_change_reviews(ir, load_session(tmp_path), config, reviews)

    session = load_session(tmp_path)
    first_context = get_boundary_context(ir, session, config)
    assert first_context["required_topic_boundary"]["boundary_element_id"] == "el-004"
    assert [candidate["element_id"] for candidate in first_context["safe_candidates"]] == ["el-004"]
    commit_boundary(
        ir,
        session,
        config,
        action="cut",
        element_id="el-004",
        reason="The metabolic pathway concludes before the contract-law learning objective begins.",
    )

    session = load_session(tmp_path)
    final_context = get_boundary_context(ir, session, config)
    assert final_context["safe_candidates"][-1]["element_id"] == "el-008"
    commit_boundary(
        ir,
        session,
        config,
        action="cut",
        element_id="el-008",
        reason="The contract-law discussion reaches the end of the source document.",
    )

    report = run_write_and_verify(ir, config)

    assert report["passed"] is True
    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert '"total_chunks": 2' in manifest
    assert '"split_type": "topic_change"' in manifest
