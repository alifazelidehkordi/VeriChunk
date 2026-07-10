import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  parseJsonOutput,
  ProcessCancelledError,
  ProcessOutputLimitError,
  ProcessTimeoutError,
  runProcess,
} from "../mcp/cli-runner.js";

async function script(body) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "doc-splitter-node-test-"));
  const file = path.join(dir, "script.mjs");
  await writeFile(file, body, "utf8");
  return { file, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

test("runProcess returns stdout", async () => {
  const item = await script('process.stdout.write("ok")');
  try {
    assert.equal(await runProcess(process.execPath, [item.file]), "ok");
  } finally { await item.cleanup(); }
});

test("runProcess reports spawn errors", async () => {
  await assert.rejects(runProcess("/definitely/missing/doc-splitter"), /ENOENT/);
});

test("runProcess enforces timeout", async () => {
  const item = await script("setTimeout(() => {}, 5000)");
  try {
    await assert.rejects(
      runProcess(process.execPath, [item.file], { timeoutMs: 30 }),
      ProcessTimeoutError,
    );
  } finally { await item.cleanup(); }
});

test("runProcess enforces combined output limit", async () => {
  const item = await script('process.stdout.write("x".repeat(20000))');
  try {
    await assert.rejects(
      runProcess(process.execPath, [item.file], { maxOutputBytes: 1024 }),
      ProcessOutputLimitError,
    );
  } finally { await item.cleanup(); }
});

test("runProcess supports cancellation", async () => {
  const item = await script("setTimeout(() => {}, 5000)");
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 20);
  try {
    await assert.rejects(
      runProcess(process.execPath, [item.file], { signal: controller.signal }),
      ProcessCancelledError,
    );
  } finally { await item.cleanup(); }
});

test("parseJsonOutput rejects log prefixes instead of guessing", () => {
  assert.deepEqual(parseJsonOutput('{"ok":true}'), { ok: true });
  assert.throws(() => parseJsonOutput('log line\n{"ok":true}'), /non-JSON/);
});

test("runProcess surfaces non-zero stderr", async () => {
  const item = await script('process.stderr.write("boom"); process.exit(3)');
  try {
    await assert.rejects(runProcess(process.execPath, [item.file]), /boom/);
  } finally { await item.cleanup(); }
});
