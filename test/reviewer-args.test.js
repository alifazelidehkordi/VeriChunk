import assert from "node:assert/strict";
import test from "node:test";

import { buildReviewerArgs } from "../mcp/reviewer-args.js";

test("command backend reads its bridge only from environment", () => {
  const args = buildReviewerArgs(
    { backend: "command", workers: 3, max_output_bytes: 4096 },
    { DOC_SPLITTER_AGENT_COMMAND: "./reviewer" },
  );
  assert.deepEqual(args, [
    "run-topic-reviews", "--backend", "command",
    "--agent-command", "./reviewer",
    "--workers", "3",
    "--agent-max-output-bytes", "4096",
  ]);
});

test("OpenAI backend uses configured model without exposing a key", () => {
  const args = buildReviewerArgs(
    { backend: "openai", max_output_tokens: 900 },
    { DOC_SPLITTER_OPENAI_MODEL: "review-model", OPENAI_API_KEY: "secret" },
  );
  assert.deepEqual(args, [
    "run-topic-reviews", "--backend", "openai",
    "--model", "review-model",
    "--max-output-tokens", "900",
  ]);
  assert.equal(args.includes("secret"), false);
});

test("Anthropic backend requires an explicit or environment model", () => {
  assert.throws(
    () => buildReviewerArgs({ backend: "anthropic" }, {}),
    /DOC_SPLITTER_ANTHROPIC_MODEL/,
  );
});
