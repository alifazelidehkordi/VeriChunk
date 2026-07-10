from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from doc_splitter.agents.provider_backends import (
    AnthropicAgentBackend,
    OpenAIAgentBackend,
)

TASK = {
    "review_id": "topic-change:el-004",
    "reviewer_slot": 2,
    "review_role": "continuity_reviewer",
    "before_element_ids": ["el-001", "el-004"],
    "after_element_ids": ["el-005", "el-006"],
    "before_context": "[el-004] Insulin signaling concludes.",
    "after_context": "[el-005] Thyroid hormone synthesis begins.",
    "instructions": "Decide whether this is an independent learning objective.",
}


def _review_json() -> str:
    return json.dumps(
        {
            "decision": "split",
            "confidence": 0.93,
            "reason": "The learning objective changes from insulin signaling to thyroid synthesis.",
            "evidence_before": ["el-004"],
            "evidence_after": ["el-005"],
        }
    )


class FakeResponses:
    def __init__(self, captured):
        self.captured = captured

    async def create(self, **kwargs):
        self.captured["request"] = kwargs
        return SimpleNamespace(output_text=_review_json())


class FakeOpenAIClient:
    def __init__(self, captured, **kwargs):
        captured["client"] = kwargs
        captured["closed"] = False
        self.captured = captured
        self.responses = FakeResponses(captured)

    async def close(self):
        self.captured["closed"] = True


class FakeMessages:
    def __init__(self, captured):
        self.captured = captured

    async def create(self, **kwargs):
        self.captured["request"] = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=f"```json\n{_review_json()}\n```")]
        )


class FakeAnthropicClient:
    def __init__(self, captured, **kwargs):
        captured["client"] = kwargs
        captured["closed"] = False
        self.captured = captured
        self.messages = FakeMessages(captured)

    async def close(self):
        self.captured["closed"] = True


def test_openai_backend_uses_responses_api_and_normalizes_identity(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    captured = {}
    backend = OpenAIAgentBackend(
        model="review-model",
        max_output_tokens=777,
        client_factory=lambda **kwargs: FakeOpenAIClient(captured, **kwargs),
    )

    review = asyncio.run(backend.review(TASK))

    assert captured["client"]["api_key"] == "test-openai-key"
    assert captured["request"]["model"] == "review-model"
    assert captured["request"]["max_output_tokens"] == 777
    assert "TASK JSON" in captured["request"]["input"]
    assert captured["closed"] is True
    assert review["review_id"] == TASK["review_id"]
    assert review["reviewer_id"] == "openai:review-model:continuity_reviewer:2"
    assert review["decision"] == "split"


def test_anthropic_backend_uses_messages_api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    captured = {}
    backend = AnthropicAgentBackend(
        model="review-model",
        base_url="https://example.invalid",
        client_factory=lambda **kwargs: FakeAnthropicClient(captured, **kwargs),
    )

    review = asyncio.run(backend.review(TASK))

    assert captured["client"]["base_url"] == "https://example.invalid"
    assert captured["request"]["model"] == "review-model"
    assert captured["request"]["messages"][0]["role"] == "user"
    assert captured["closed"] is True
    assert review["reviewer_id"] == "anthropic:review-model:continuity_reviewer:2"
    assert review["evidence_before"] == ["el-004"]


def test_provider_backend_requires_key_from_environment(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = OpenAIAgentBackend(
        model="review-model",
        client_factory=lambda **kwargs: None,
    )

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        asyncio.run(backend.review(TASK))


def test_provider_backend_rejects_invalid_structured_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    @dataclass
    class InvalidResponses:
        async def create(self, **kwargs):
            return SimpleNamespace(output_text='{"decision":"maybe"}')

    class InvalidClient:
        responses = InvalidResponses()

        async def close(self):
            return None

    backend = OpenAIAgentBackend(
        model="review-model",
        client_factory=lambda **kwargs: InvalidClient(),
    )

    with pytest.raises(ValueError, match="decision"):
        asyncio.run(backend.review(TASK))
