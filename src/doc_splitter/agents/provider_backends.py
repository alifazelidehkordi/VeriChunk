"""Direct OpenAI and Anthropic reviewer backends.

Provider SDKs are optional dependencies and imported lazily. API keys are read
from environment variables only; they are never accepted as task data or stored
in the split session.
"""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_REVIEW_INSTRUCTIONS = """You are an independent document-boundary reviewer.
Decide whether the material after a proposed safe boundary starts a genuinely
new learning objective or remains part of the same topic. A real topic change
must be split even when the preceding chunk is short. Examples, exercises,
continuations, and conclusions of the same objective must be merged.

Return exactly one JSON object with these fields and no prose:
- decision: \"split\" or \"merge\"
- confidence: number from 0 to 1
- reason: a specific semantic explanation
- evidence_before: one or more element IDs from before_element_ids
- evidence_after: one or more element IDs from after_element_ids
Do not invent element IDs.
"""


def _task_prompt(task: dict[str, Any]) -> str:
    return (
        "Review this proposed boundary. Respect the task's review_role and "
        "instructions.\n\nTASK JSON:\n"
        + json.dumps(task, ensure_ascii=False, separators=(",", ":"))
    )


def _parse_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3:
            value = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("Provider returned invalid review JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Provider must return one JSON object")
    return parsed


def _normalize_review(
    task: dict[str, Any],
    raw: dict[str, Any],
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    decision = str(raw.get("decision", "")).strip().lower()
    if decision not in {"split", "merge"}:
        raise ValueError("Provider review decision must be 'split' or 'merge'")
    confidence_value = raw.get("confidence")
    if confidence_value is None:
        raise ValueError("Provider review confidence must be a number")
    try:
        confidence = float(confidence_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Provider review confidence must be a number") from exc
    if not 0 <= confidence <= 1:
        raise ValueError("Provider review confidence must be between 0 and 1")
    reason = str(raw.get("reason", "")).strip()
    if not reason:
        raise ValueError("Provider review reason cannot be empty")

    def evidence(name: str) -> list[str]:
        values = raw.get(name)
        if not isinstance(values, list) or not values:
            raise ValueError(f"Provider review {name} must be a non-empty array")
        return [str(value) for value in values]

    slot = int(task.get("reviewer_slot", 1))
    role = str(task.get("review_role", "reviewer"))
    return {
        "review_id": str(task["review_id"]),
        "reviewer_id": f"{provider}:{model}:{role}:{slot}",
        "decision": decision,
        "confidence": confidence,
        "reason": reason,
        "evidence_before": evidence("evidence_before"),
        "evidence_after": evidence("evidence_after"),
    }


async def _close_client(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _require_api_key(env_name: str) -> str:
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise ValueError(f"Required API key environment variable is missing: {env_name}")
    return api_key


def _openai_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise ValueError("OpenAI response did not contain text output")
    return "".join(parts)


def _anthropic_text(message: Any) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise ValueError("Anthropic response did not contain a text block")
    return "".join(parts)


@dataclass
class OpenAIAgentBackend:
    """Run independent reviews through OpenAI's Responses API."""

    model: str
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    timeout_seconds: float = 120.0
    max_output_tokens: int = 1200
    client_factory: Callable[..., Any] | None = field(default=None, repr=False, compare=False)

    async def review(self, task: dict[str, Any]) -> dict[str, Any]:
        api_key = _require_api_key(self.api_key_env)
        factory = self.client_factory
        if factory is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "OpenAI backend requires the optional dependency: "
                    "pip install 'doc-splitter[openai]'"
                ) from exc
            factory = AsyncOpenAI
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": self.timeout_seconds,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = factory(**kwargs)
        try:
            response = await client.responses.create(
                model=self.model,
                instructions=_REVIEW_INSTRUCTIONS,
                input=_task_prompt(task),
                max_output_tokens=self.max_output_tokens,
            )
            raw = _parse_json_object(_openai_text(response))
            return _normalize_review(task, raw, provider="openai", model=self.model)
        finally:
            await _close_client(client)


@dataclass
class AnthropicAgentBackend:
    """Run independent reviews through Anthropic's Messages API."""

    model: str
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None
    timeout_seconds: float = 120.0
    max_output_tokens: int = 1200
    client_factory: Callable[..., Any] | None = field(default=None, repr=False, compare=False)

    async def review(self, task: dict[str, Any]) -> dict[str, Any]:
        api_key = _require_api_key(self.api_key_env)
        factory = self.client_factory
        if factory is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise RuntimeError(
                    "Anthropic backend requires the optional dependency: "
                    "pip install 'doc-splitter[anthropic]'"
                ) from exc
            factory = AsyncAnthropic
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": self.timeout_seconds,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = factory(**kwargs)
        try:
            message = await client.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                system=_REVIEW_INSTRUCTIONS,
                messages=[{"role": "user", "content": _task_prompt(task)}],
            )
            raw = _parse_json_object(_anthropic_text(message))
            return _normalize_review(task, raw, provider="anthropic", model=self.model)
        finally:
            await _close_client(client)
