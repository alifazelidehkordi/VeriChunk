#!/usr/bin/env node
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PYTHON = process.env.DOC_SPLITTER_PYTHON || "python3";

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

const outDir = z.string().optional().describe("Output directory (default: output)");
const minPages = z.number().int().optional();
const maxPages = z.number().int().optional();
const outputFormat = z.enum(["markdown", "pdf", "both"]).optional();
const overlapPages = z.number().int().optional();

server.registerTool(
  "split_document",
  {
    title: "Split document",
    description: "Parse a PDF/DOCX and start the boundary planning session.",
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
    description: "Return content window and safe cut candidates for the host agent.",
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
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir, action, element_id, reason }) => {
    const args = ["commit-boundary", "--action", action, "--reason", reason || ""];
    if (element_id) args.push("--element-id", element_id);
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "write_chunks",
  {
    title: "Write chunks",
    description: "Write chunk markdown files and run verification after boundaries are complete.",
    inputSchema: { output_dir: outDir },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ output_dir }) => {
    const args = ["write"];
    if (output_dir) args.push("--out", output_dir);
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
    description: "Store bilingual topic description and coherence flag for a chunk.",
    inputSchema: {
      chunk_id: z.number().int(),
      topic_fa: z.string(),
      topic_en: z.string(),
      coherence: z.enum(["confident", "needs_review"]),
      reason: z.string().optional(),
      output_dir: outDir,
    },
    annotations: { readOnlyHint: false, openWorldHint: false },
  },
  async ({ chunk_id, topic_fa, topic_en, coherence, reason, output_dir }) => {
    const args = [
      "commit-analysis",
      "--chunk-id", String(chunk_id),
      "--topic-fa", topic_fa,
      "--topic-en", topic_en,
      "--coherence", coherence,
      "--reason", reason || "",
    ];
    if (output_dir) args.push("--out", output_dir);
    const out = await runCli(args);
    return { content: [{ type: "text", text: out }] };
  },
);

server.registerTool(
  "generate_study_index",
  {
    title: "Generate study index",
    description: "Render study-index-fa.md and study-index-en.md from manifest and analyses.",
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

await server.connect(new StdioServerTransport());