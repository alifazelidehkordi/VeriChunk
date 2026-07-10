"""Pluggable backends for semantic boundary reviewers."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import json
import shlex
from typing import Any, Protocol


class AgentBackend(Protocol):
    async def review(self, task: dict[str, Any]) -> dict[str, Any]:
        """Return one structured review result for a task."""


@dataclass
class HeuristicAgentBackend:
    """Deterministic local reviewer used for tests and offline baselines.

    This backend is not presented as an LLM replacement. It exercises the real
    concurrent scheduling/consensus path when no external model backend is
    configured.
    """

    backend_id: str = "heuristic"

    async def review(self, task: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0)
        role = str(task.get("review_role", "transition_reviewer"))
        score = float(task.get("semantic_score", 0.0))
        shared = list(task.get("shared_terms", []))
        signals = set(task.get("signals", []))

        if role == "continuity_reviewer":
            decision = "merge" if len(shared) >= 3 or "generic_continuation_heading" in signals else (
                "split" if score >= 0.84 else "merge"
            )
        elif role == "adjudicator":
            decision = "split" if score >= 0.80 and "generic_continuation_heading" not in signals else "merge"
        else:
            decision = "split" if score >= 0.76 else "merge"

        before_ids = list(task.get("before_element_ids", []))
        after_ids = list(task.get("after_element_ids", []))
        reason = (
            "The semantic signatures and learning vocabulary differ across the proposed boundary."
            if decision == "split"
            else "The material after the boundary continues the same learning objective or application."
        )
        return {
            "review_id": task["review_id"],
            "reviewer_id": f"{self.backend_id}-{task.get('reviewer_slot', 1)}",
            "decision": decision,
            "confidence": round(max(0.55, min(0.99, score if decision == "split" else 1.0 - score / 2)), 2),
            "reason": reason,
            "evidence_before": before_ids[-2:] or before_ids,
            "evidence_after": after_ids[:2] or after_ids,
        }


@dataclass
class CommandAgentBackend:
    """Run an external model bridge as a subprocess for each review.

    The command receives one JSON task on stdin and must emit one JSON object on
    stdout matching the review schema. This keeps provider credentials and SDKs
    outside the core package while allowing true concurrent LLM execution.
    """

    command: str
    timeout_seconds: float = 120.0

    async def review(self, task: dict[str, Any]) -> dict[str, Any]:
        argv = shlex.split(self.command)
        if not argv:
            raise ValueError("Agent command cannot be empty")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = json.dumps(task, ensure_ascii=False).encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(payload), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(
                f"Agent command exceeded {self.timeout_seconds:g} seconds"
            )
        if proc.returncode != 0:
            raise RuntimeError(
                stderr.decode("utf-8", errors="replace").strip()
                or f"Agent command exited with {proc.returncode}"
            )
        try:
            result = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Agent command returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("Agent command must return one JSON object")
        return result
