#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const VENV_PYTHON = path.join(ROOT, ".venv", "bin", "python3");
const PYTHON = process.env.DOC_SPLITTER_PYTHON || (existsSync(VENV_PYTHON) ? VENV_PYTHON : "python3");
const DEBUG = process.env.DOC_SPLITTER_MCP_DEBUG === "1";

function debug(message) {
  if (DEBUG) process.stderr.write(`[doc-splitter] ${message}\n`);
}

function runCli(args) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON, ["-m", "doc_splitter.cli", ...args], {
      cwd: ROOT,
      env: { ...process.env, PYTHONPATH: path.join(ROOT, "src") },
    });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => { stdout += d; });
    proc.stderr.on("data", (d) => { stderr += d; });
    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || stdout.trim() || `exit ${code}`));
        return;
      }
      resolve(stdout.trim());
    });
  });
}

function parseJsonOutput(output) {
  const start = output.indexOf("{");
  const arrStart = output.indexOf("[");
  let idx = -1;
  if (start >= 0 && arrStart >= 0) idx = Math.min(start, arrStart);
  else idx = Math.max(start, arrStart);
  if (idx < 0) return { raw: output };
  return JSON.parse(output.slice(idx));
}

const server = new McpServer({ name: "doc-splitter", version: "0.1.0" });
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
  async ({ file_path, min_pages, max_pages, output_dir, output_format, overlap_pages }) => {
    const args = ["run", "--input", file_path];
    if (min_pages) args.push("--min-pages", String(min_pages));
    if (max_pages) args.push("--max-pages", String(max_pages));
    if (output_dir) args.push("--out", output_dir);
    if (output_format) args.push("--output-format", output_format);
    if (overlap_pages !== undefined) args.push("--overlap-pages", String(overlap_pages));
    const out = await runCli(args);
    const data = parseJsonOutput(out);
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
  async ({ output_dir }) => {
    const args = ["boundary-context"];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
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
      allow_topic_merge: z.boolean().optional().describe("Deprecated; confirmed topic changes cannot be overridden."),
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, action, element_id, reason, allow_oversize, allow_topic_merge }) => {
    const args = ["commit-boundary", "--action", action, "--reason", reason || ""];
    if (element_id) args.push("--element-id", element_id);
    if (allow_oversize) args.push("--allow-oversize");
    if (allow_topic_merge) args.push("--allow-topic-merge");
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "get_topic_change_review_batch",
  {
    title: "Get parallel topic-change review tasks",
    description: "Return independent topic-transition tasks for concurrent subagents. Collect all votes, then submit them together.",
    inputSchema: {
      output_dir: outDir,
      workers: z.number().int().min(1).max(16).optional(),
    },
    annotations: { readOnlyHint: true, openWorldHint: false },
  },
  async ({ output_dir, workers }) => {
    const args = ["topic-review-context"];
    if (output_dir) args.push("--out", output_dir);
    if (workers) args.push("--workers", String(workers));
    const out = await runCli(args);
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "commit_topic_change_reviews",
  {
    title: "Commit parallel topic-change review votes",
    description: "Persist collected independent votes. Two matching votes turn a confirmed topic change into a hard boundary.",
    inputSchema: {
      output_dir: outDir,
      reviews: z.array(z.object({
        review_id: z.string(),
        reviewer_id: z.string(),
        decision: z.enum(["split", "merge"]),
        reason: z.string(),
      })).min(1),
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, reviews }) => {
    const args = ["commit-topic-reviews", "--reviews", JSON.stringify(reviews)];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
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
  async ({ output_dir, output_format, overlap_pages }) => {
    const args = ["write"];
    if (output_dir) args.push("--out", output_dir);
    args.push("--output-format", output_format);
    if (overlap_pages !== undefined) args.push("--overlap-pages", String(overlap_pages));
    const out = await runCli(args);
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
  async ({ chunk_id, output_dir }) => {
    const args = ["get-chunk", "--chunk-id", String(chunk_id)];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
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
  async ({ output_dir }) => {
    const args = ["verify"];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
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
  async ({ chunk_id, output_dir }) => {
    const args = ["analysis-context", "--chunk-id", String(chunk_id)];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
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
  async ({ chunk_id, topic_fa, topic_en, study_focus_fa, study_focus_en, coherence, reason, output_dir }) => {
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
    const out = await runCli(args);
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
  async ({ output_dir, reading_speed_wpm }) => {
    const args = ["index"];
    if (output_dir) args.push("--out", output_dir);
    if (reading_speed_wpm) args.push("--reading-speed-wpm", String(reading_speed_wpm));
    const out = await runCli(args);
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
  async ({ output_dir, index_fa, index_en, study_map }) => {
    const args = ["commit-index", "--fa", index_fa, "--en", index_en, "--map", study_map];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
    return { content: [{ type: "text", text: out }] };
  },
);

debug(`starting MCP server with python ${PYTHON}`);
await server.connect(new StdioServerTransport());
debug("MCP server connected to stdio");
process.stdin.resume();
const keepAlive = setInterval(() => {}, 1 << 30);
const shutdown = async () => {
  clearInterval(keepAlive);
  await server.close();
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
