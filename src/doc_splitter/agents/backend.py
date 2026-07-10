"""Pluggable backends for semantic boundary reviewers."""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from typing import Any, Protocol


class AgentBackend(Protocol):
    async def review(self, task: dict[str, Any]) -> dict[str, Any]:
        """Return one structured review result for a task."""


@dataclass
class HeuristicAgentBackend:
    """Deterministic local reviewer used for tests and offline baselines."""

    backend_id: str = "heuristic"

    async def review(self, task: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0)
        role = str(task.get("review_role", "transition_reviewer"))
        score = float(task.get("semantic_score", 0.0))
        shared = list(task.get("shared_terms", []))
        signals = set(task.get("signals", []))

        if role == "continuity_reviewer":
            decision = (
                "merge"
                if len(shared) >= 3 or "generic_continuation_heading" in signals
                else ("split" if score >= 0.84 else "merge")
            )
        elif role == "adjudicator":
            decision = (
                "split"
                if score >= 0.80 and "generic_continuation_heading" not in signals
                else "merge"
            )
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
            "confidence": round(
                max(0.55, min(0.99, score if decision == "split" else 1.0 - score / 2)), 2
            ),
            "reason": reason,
            "evidence_before": before_ids[-2:] or before_ids,
            "evidence_after": after_ids[:2] or after_ids,
        }


async def _read_limited(stream: asyncio.StreamReader, limit: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise RuntimeError(f"Agent {label} exceeded {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


@dataclass
class CommandAgentBackend:
    """Run an external model bridge as a bounded subprocess for each review."""

    command: str
    timeout_seconds: float = 120.0
    max_output_bytes: int = 2 * 1024 * 1024

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
        assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
        stdin = proc.stdin
        stdout_stream = proc.stdout
        stderr_stream = proc.stderr
        payload = json.dumps(task, ensure_ascii=False).encode("utf-8")
        stdin.write(payload)
        await stdin.drain()
        stdin.close()

        async def collect() -> tuple[bytes, bytes, int]:
            stdout_task = asyncio.create_task(
                _read_limited(stdout_stream, self.max_output_bytes, "stdout")
            )
            stderr_task = asyncio.create_task(
                _read_limited(stderr_stream, self.max_output_bytes, "stderr")
            )
            try:
                stdout_bytes, stderr_bytes, returncode = await asyncio.gather(
                    stdout_task,
                    stderr_task,
                    proc.wait(),
                )
                return stdout_bytes, stderr_bytes, returncode
            except BaseException:
                stdout_task.cancel()
                stderr_task.cancel()
                raise

        try:
            stdout, stderr, returncode = await asyncio.wait_for(
                collect(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Agent command exceeded {self.timeout_seconds:g} seconds") from None
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        if returncode != 0:
            raise RuntimeError(
                stderr.decode("utf-8", errors="replace").strip()
                or f"Agent command exited with {returncode}"
            )
        try:
            result = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Agent command returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("Agent command must return one JSON object")
        return result
