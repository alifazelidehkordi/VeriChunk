"""Bounded-concurrency execution for independent semantic review tasks."""

from __future__ import annotations

import asyncio
from typing import Any

from doc_splitter.agents.backend import AgentBackend


async def run_review_batch(
    batch: dict[str, Any],
    backend: AgentBackend,
    *,
    workers: int,
    retries: int = 1,
) -> list[dict[str, Any]]:
    tasks = [task for worker_batch in batch.get("batches", []) for task in worker_batch]
    semaphore = asyncio.Semaphore(max(1, workers))

    async def execute(task: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(max(1, retries + 1)):
            try:
                async with semaphore:
                    result = await backend.review(task)
                returned_review_id = result.get("review_id")
                if returned_review_id not in {None, task["review_id"]}:
                    raise ValueError(
                        "Reviewer returned a result for a different review_id: "
                        f"{returned_review_id!r}"
                    )
                result["review_id"] = task["review_id"]
                if not str(result.get("reviewer_id", "")).strip():
                    raise ValueError("Reviewer result is missing reviewer_id")
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(min(0.25 * (attempt + 1), 1.0))
        assert last_error is not None
        raise RuntimeError(
            f"Review task {task.get('review_id')} slot={task.get('reviewer_slot')} failed: {last_error}"
        ) from last_error

    pending = [asyncio.create_task(execute(task)) for task in tasks]
    try:
        results = list(await asyncio.gather(*pending))
    except BaseException:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        raise

    seen: set[tuple[str, str]] = set()
    for result in results:
        key = (str(result["review_id"]), str(result["reviewer_id"]))
        if key in seen:
            raise ValueError(
                "Independent reviewer IDs must be unique per boundary; "
                f"duplicate result: {key}"
            )
        seen.add(key)
    return results
