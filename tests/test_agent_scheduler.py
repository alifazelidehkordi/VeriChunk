from __future__ import annotations

import asyncio
from pathlib import Path

from doc_splitter.agents.scheduler import run_review_batch
from doc_splitter.boundary.planner import load_session
from doc_splitter.cli import main
from doc_splitter.config import SplitConfig
from doc_splitter.ir.serialize import load_ir, save_ir
from doc_splitter.orchestrator import init_session
from doc_splitter.topic_reviews import build_topic_change_review_batch

GOLDEN_IR = Path(__file__).parent / "golden" / "ir"


class TrackingBackend:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def review(self, task):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.03)
        self.active -= 1
        return {
            "review_id": task["review_id"],
            "reviewer_id": f"tracking-{task['reviewer_slot']}",
            "decision": "split",
            "confidence": 0.9,
            "reason": "The contexts express separate learning objectives and domain vocabulary.",
            "evidence_before": [task["before_element_ids"][-1]],
            "evidence_after": [task["after_element_ids"][0]],
        }


def test_scheduler_executes_reviews_concurrently():
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    batch = build_topic_change_review_batch(ir, SplitConfig(), workers=3)
    backend = TrackingBackend()

    reviews = asyncio.run(run_review_batch(batch, backend, workers=3))

    assert len(reviews) == 3
    assert backend.max_active >= 2


def test_cli_can_run_and_commit_parallel_heuristic_reviews(tmp_path: Path):
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    config = SplitConfig(output_dir=tmp_path)
    save_ir(ir, tmp_path / "ir.json")
    init_session(Path("shift.pdf"), config, ir)
    assert (tmp_path / "semantic-map.json").is_file()

    code = main(
        [
            "run-topic-reviews",
            "--out",
            str(tmp_path),
            "--workers",
            "3",
            "--backend",
            "heuristic",
        ]
    )

    assert code == 0
    session = load_session(tmp_path)
    assert session.stage == "boundary"
    assert next(iter(session.topic_change_reviews.values()))["consensus"] == "split"


def test_command_backend_runs_json_reviewer_process(tmp_path: Path):
    from doc_splitter.agents.backend import CommandAgentBackend

    reviewer = tmp_path / "reviewer.py"
    reviewer.write_text(
        """#!/usr/bin/env python3
import json, sys
task = json.load(sys.stdin)
json.dump({
    'review_id': task['review_id'],
    'reviewer_id': 'external-' + str(task['reviewer_slot']),
    'decision': 'split',
    'confidence': 0.9,
    'reason': 'The external reviewer found distinct learning objectives.',
    'evidence_before': [task['before_element_ids'][-1]],
    'evidence_after': [task['after_element_ids'][0]],
}, sys.stdout)
""",
        encoding="utf-8",
    )
    reviewer.chmod(0o755)
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    batch = build_topic_change_review_batch(ir, SplitConfig(), workers=3)

    reviews = asyncio.run(
        run_review_batch(
            batch,
            CommandAgentBackend(str(reviewer), timeout_seconds=5),
            workers=3,
        )
    )

    assert len(reviews) == 3
    assert {review["reviewer_id"] for review in reviews} == {
        "external-1",
        "external-2",
        "external-3",
    }


def test_command_backend_rejects_unbounded_output(tmp_path: Path):
    from doc_splitter.agents.backend import CommandAgentBackend

    reviewer = tmp_path / "noisy.py"
    reviewer.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.stdout.write('x' * 10000)\n",
        encoding="utf-8",
    )
    reviewer.chmod(0o755)
    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    batch = build_topic_change_review_batch(ir, SplitConfig(), workers=1)

    import pytest

    with pytest.raises(RuntimeError, match="exceeded 1024 bytes"):
        asyncio.run(
            run_review_batch(
                batch,
                CommandAgentBackend(str(reviewer), timeout_seconds=5, max_output_bytes=1024),
                workers=1,
                retries=0,
            )
        )


def test_cli_accepts_topic_reviews_from_file(tmp_path: Path):
    import json

    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    config = SplitConfig(output_dir=tmp_path)
    save_ir(ir, tmp_path / "ir.json")
    init_session(Path("shift.pdf"), config, ir)
    batch = build_topic_change_review_batch(ir, config, workers=1)
    tasks = [task for worker in batch["batches"] for task in worker]
    reviews = [
        {
            "review_id": task["review_id"],
            "reviewer_id": f"file-{task['reviewer_slot']}",
            "decision": "split",
            "confidence": 0.9,
            "reason": "The learning objective and terminology change across this boundary.",
            "evidence_before": [task["before_element_ids"][-1]],
            "evidence_after": [task["after_element_ids"][0]],
        }
        for task in tasks
    ]
    review_file = tmp_path / "reviews.json"
    review_file.write_text(json.dumps(reviews), encoding="utf-8")

    code = main(
        [
            "commit-topic-reviews",
            "--out",
            str(tmp_path),
            "--reviews-file",
            str(review_file),
        ]
    )

    assert code == 0
    assert load_session(tmp_path).stage == "boundary"


def test_scheduler_cancels_sibling_reviews_after_fatal_failure():
    class FailingBackend:
        def __init__(self) -> None:
            self.cancelled = 0

        async def review(self, task):
            if task["reviewer_slot"] == 1:
                raise RuntimeError("fatal reviewer failure")
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise

    ir = load_ir(GOLDEN_IR / "topic_change_without_heading.json")
    batch = build_topic_change_review_batch(ir, SplitConfig(), workers=3)
    backend = FailingBackend()

    import pytest

    with pytest.raises(RuntimeError, match="fatal reviewer failure"):
        asyncio.run(run_review_batch(batch, backend, workers=3, retries=0))
    assert backend.cancelled >= 1
