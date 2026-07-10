#!/usr/bin/env node
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { parseJsonOutput, runProcess } from "./mcp/cli-runner.js";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const VENV_PYTHON = path.join(ROOT, ".venv", "bin", "python3");
const PYTHON = process.env.DOC_SPLITTER_PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : "python3");
const DEBUG = process.env.DOC_SPLITTER_MCP_DEBUG === "1";
const AGENT_COMMAND = process.env.DOC_SPLITTER_AGENT_COMMAND || "";

function debug(message) {
  if (DEBUG) process.stderr.write(`[doc-splitter] ${message}\n`);
}


function positiveEnvInt(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback;
}

function runCli(args, { signal } = {}) {
  return runProcess(PYTHON, ["-m", "doc_splitter.cli", ...args], {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: path.join(ROOT, "src") },
    timeoutMs: positiveEnvInt("DOC_SPLITTER_CLI_TIMEOUT_MS", 120000),
    maxOutputBytes: positiveEnvInt("DOC_SPLITTER_MAX_OUTPUT_BYTES", 8 * 1024 * 1024),
    signal,
  });
}

async function createRunOutputDir() {
  const base = process.env.DOC_SPLITTER_RUNS_DIR || path.join(ROOT, "output-runs");
  await mkdir(base, { recursive: true });
  return mkdtemp(path.join(base, "run-"));
}

async function withTempTextFiles(files, callback) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "doc-splitter-mcp-"));
  try {
    const paths = {};
    for (const [name, content] of Object.entries(files)) {
      const file = path.join(dir, name);
      await writeFile(file, content, "utf8");
      paths[name] = file;
    }
    return await callback(paths);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const server = new McpServer({ name: "doc-splitter", version: "0.4.0" });
server.server.onerror = (error) => debug(`server error: ${error?.stack || error}`);
server.server.onclose = () => debug("server closed");

const outDir = z.string().optional().describe("Output directory (default: output)");
const minPages = z.number().int().optional();
const maxPages = z.number().int().optional();
const outputFormat = z.enum(["markdown", "pdf", "both"]).optional();
const overlapPages = z.number().int().optional();

server.registerTool(
  "split_document",
  {
    title: "Split document",
    description: "Parse a PDF/DOCX and start the enforced topic-review/boundary workflow.",
    inputSchema: {
      file_path: z.string(),
      min_pages: minPages,
      max_pages: maxPages,
      output_dir: outDir,
      output_format: outputFormat,
      overlap_pages: overlapPages,
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ file_path, min_pages, max_pages, output_dir, output_format, overlap_pages }, extra) => {
    const resolvedOutputDir = output_dir || await createRunOutputDir();
    const args = ["run", "--input", file_path, "--out", resolvedOutputDir];
    if (min_pages) args.push("--min-pages", String(min_pages));
    if (max_pages) args.push("--max-pages", String(max_pages));
    if (output_format) args.push("--output-format", output_format);
    if (overlap_pages !== undefined) args.push("--overlap-pages", String(overlap_pages));
    const out = await runCli(args, { signal: extra?.signal });
    const data = parseJsonOutput(out);
    data.output_dir = resolvedOutputDir;
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  },
);

server.registerTool(
  "get_boundary_context",
  {
    title: "Get boundary context",
    description: "Return content window and safe cut candidates after all required topic reviews are resolved.",
    inputSchema: { output_dir: outDir },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ output_dir }, extra) => {
    const args = ["boundary-context"];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "commit_boundary",
  {
    title: "Commit boundary",
    description: "Commit a conceptual boundary cut or window extension.",
    inputSchema: {
      output_dir: outDir,
      action: z.enum(["cut", "extend"]),
      element_id: z.string().optional(),
      reason: z.string().optional(),
      allow_oversize: z.boolean().optional(),
      continuity_evidence: z.array(z.string()).optional(),
      continuity_reviewers: z.array(z.string()).optional(),
      allow_topic_merge: z.boolean().optional().describe("Deprecated; confirmed topic changes cannot be overridden."),
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, action, element_id, reason, allow_oversize, continuity_evidence, continuity_reviewers, allow_topic_merge }, extra) => {
    const args = ["commit-boundary", "--action", action, "--reason", reason || ""];
    if (element_id) args.push("--element-id", element_id);
    if (allow_oversize) args.push("--allow-oversize");
    for (const elementId of continuity_evidence || []) args.push("--continuity-evidence", elementId);
    for (const reviewerId of continuity_reviewers || []) args.push("--continuity-reviewer", reviewerId);
    if (allow_topic_merge) args.push("--allow-topic-merge");
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "get_topic_change_review_batch",
  {
    title: "Get parallel topic-change review tasks",
    description: "Return three-role semantic transition tasks, including heading-free candidates, for concurrent subagents. Collect evidence-backed votes and submit them together.",
    inputSchema: {
      output_dir: outDir,
      workers: z.number().int().min(1).max(16).optional(),
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ output_dir, workers }, extra) => {
    const args = ["topic-review-context"];
    if (output_dir) args.push("--out", output_dir);
    if (workers) args.push("--workers", String(workers));
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "run_parallel_topic_reviews",
  {
    title: "Run parallel topic-change reviewers",
    description: "Execute the operator-configured JSON reviewer command concurrently. Requires DOC_SPLITTER_AGENT_COMMAND in the MCP server environment.",
    inputSchema: {
      output_dir: outDir,
      workers: z.number().int().min(1).max(16).optional(),
      timeout_seconds: z.number().positive().max(600).optional(),
      retries: z.number().int().min(0).max(5).optional(),
      max_output_bytes: z.number().int().min(1024).max(16 * 1024 * 1024).optional(),
    },
    annotations: { readOnlyHint: false, openWorldHint: true },
  },
  async ({ output_dir, workers, timeout_seconds, retries, max_output_bytes }, extra) => {
    if (!AGENT_COMMAND) {
      throw new Error("DOC_SPLITTER_AGENT_COMMAND is not configured for this MCP server");
    }
    const args = [
      "run-topic-reviews",
      "--backend",
      "command",
      "--agent-command",
      AGENT_COMMAND,
    ];
    if (output_dir) args.push("--out", output_dir);
    if (workers) args.push("--workers", String(workers));
    if (timeout_seconds) args.push("--timeout-seconds", String(timeout_seconds));
    if (retries !== undefined) args.push("--retries", String(retries));
    if (max_output_bytes !== undefined) args.push("--agent-max-output-bytes", String(max_output_bytes));
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "commit_topic_change_reviews",
  {
    title: "Commit parallel topic-change review votes",
    description: "Persist evidence-backed independent votes. Two split votes create a hard boundary; unresolved disagreement blocks planning.",
    inputSchema: {
      output_dir: outDir,
      reviews: z.array(z.object({
        review_id: z.string(),
        reviewer_id: z.string(),
        decision: z.enum(["split", "merge"]),
        confidence: z.number().min(0).max(1),
        reason: z.string(),
        evidence_before: z.array(z.string()).min(1),
        evidence_after: z.array(z.string()).min(1),
      })).min(1),
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, reviews }, extra) => {
    const out = await withTempTextFiles(
      { "reviews.json": JSON.stringify(reviews) },
      async (files) => {
        const args = ["commit-topic-reviews", "--reviews-file", files["reviews.json"]];
        if (output_dir) args.push("--out", output_dir);
        return runCli(args, { signal: extra?.signal });
      },
    );
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "write_chunks",
  {
    title: "Write chunks",
    description: "Write and verify only after topic reviews and exact boundary coverage are complete. Ask the user which format they want, then provide output_format explicitly.",
    inputSchema: {
      output_dir: outDir,
      output_format: z.enum(["markdown", "pdf", "both"]),
      overlap_pages: overlapPages,
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, output_format, overlap_pages }, extra) => {
    const args = ["write"];
    if (output_dir) args.push("--out", output_dir);
    args.push("--output-format", output_format);
    if (overlap_pages !== undefined) args.push("--overlap-pages", String(overlap_pages));
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "get_chunk",
  {
    title: "Get chunk",
    description: "Read chunk content by numeric id (Markdown or extracted PDF text).",
    inputSchema: {
      chunk_id: z.number().int(),
      output_dir: outDir,
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ chunk_id, output_dir }, extra) => {
    const args = ["get-chunk", "--chunk-id", String(chunk_id)];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "verify_integrity",
  {
    title: "Verify integrity",
    description: "Run coverage, word-count, and table/image integrity checks.",
    inputSchema: { output_dir: outDir },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ output_dir }, extra) => {
    const args = ["verify"];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "get_chunk_analysis_context",
  {
    title: "Get chunk analysis context",
    description: "Return full chunk content for host-agent conceptual analysis.",
    inputSchema: {
      chunk_id: z.number().int(),
      output_dir: outDir,
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ chunk_id, output_dir }, extra) => {
    const args = ["analysis-context", "--chunk-id", String(chunk_id)];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "commit_chunk_analysis",
  {
    title: "Commit chunk analysis",
    description: "Store bilingual topic, study focus, and coherence flag for a chunk.",
    inputSchema: {
      chunk_id: z.number().int(),
      topic_fa: z.string(),
      topic_en: z.string(),
      study_focus_fa: z.string(),
      study_focus_en: z.string(),
      coherence: z.enum(["confident", "needs_review"]),
      reason: z.string().optional(),
      output_dir: outDir,
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ chunk_id, topic_fa, topic_en, study_focus_fa, study_focus_en, coherence, reason, output_dir }, extra) => {
    const args = [
      "commit-analysis",
      "--chunk-id", String(chunk_id),
      "--topic-fa", topic_fa,
      "--topic-en", topic_en,
      "--study-focus-fa", study_focus_fa,
      "--study-focus-en", study_focus_en,
      "--coherence", coherence,
      "--reason", reason || "",
    ];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);


server.registerTool(
  "get_boundary_repair_context",
  {
    title: "Get boundary repair context",
    description: "Inspect one incoherent chunk and return only internal structurally safe repair cuts.",
    inputSchema: {
      chunk_id: z.number().int(),
      output_dir: outDir,
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ chunk_id, output_dir }, extra) => {
    const args = ["repair-context", "--chunk-id", String(chunk_id)];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "repair_chunk_boundaries",
  {
    title: "Repair incoherent chunk boundaries",
    description: "Split one queued incoherent chunk at safe element IDs, rewrite changed chunks, and rerun verification.",
    inputSchema: {
      chunk_id: z.number().int(),
      cut_element_ids: z.array(z.string()).min(1),
      reason: z.string().min(1),
      output_dir: outDir,
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ chunk_id, cut_element_ids, reason, output_dir }, extra) => {
    const args = ["repair-boundary", "--chunk-id", String(chunk_id), "--reason", reason];
    for (const elementId of cut_element_ids) args.push("--cut-element-id", elementId);
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "get_study_index_context",
  {
    title: "Get study index context",
    description: "Return verified chunk metadata and analyses so the host agent can author the study indexes.",
    inputSchema: {
      output_dir: outDir,
      reading_speed_wpm: z.number().int().optional(),
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, reading_speed_wpm }, extra) => {
    const args = ["index"];
    if (output_dir) args.push("--out", output_dir);
    if (reading_speed_wpm) args.push("--reading-speed-wpm", String(reading_speed_wpm));
    const out = await runCli(args, { signal: extra?.signal });
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "commit_study_index",
  {
    title: "Commit study index",
    description: "Store Persian and English study indexes authored by the host agent.",
    inputSchema: {
      output_dir: outDir,
      index_fa: z.string(),
      index_en: z.string(),
      study_map: z.string(),
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, index_fa, index_en, study_map }, extra) => {
    const out = await withTempTextFiles(
      { "index-fa.md": index_fa, "index-en.md": index_en, "study-map.md": study_map },
      async (files) => {
        const args = [
          "commit-index",
          "--fa-file", files["index-fa.md"],
          "--en-file", files["index-en.md"],
          "--map-file", files["study-map.md"],
        ];
        if (output_dir) args.push("--out", output_dir);
        return runCli(args, { signal: extra?.signal });
      },
    );
    return { content: [{ type: "text", text: out }] };
  },
);

debug(`starting MCP server with python ${PYTHON}`);
await server.connect(new StdioServerTransport());
debug("MCP server connected to stdio");
process.stdin.resume();
const keepAlive = setInterval(() => {}, 1 << 30);
let shuttingDown = false;
const shutdown = async (signal) => {
  if (shuttingDown) return;
  shuttingDown = true;
  debug(`received ${signal}; shutting down`);
  clearInterval(keepAlive);
  try {
    await server.close();
  } finally {
    process.exitCode = 0;
  }
};
process.once("SIGINT", () => { void shutdown("SIGINT"); });
process.once("SIGTERM", () => { void shutdown("SIGTERM"); });
