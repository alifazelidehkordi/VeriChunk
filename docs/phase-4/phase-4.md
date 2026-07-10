# Phase 4 — Boundary Repair and MCP Process Safety

## Scope

Phase 4 turns `needs_review` from a passive report into an enforced repair cycle and makes all Node/Python subprocess boundaries bounded and testable.

## Repair workflow

The state machine now includes:

```text
content_analysis -> boundary_repair -> writing -> verification -> content_analysis
```

When every current chunk has analysis and one or more analyses use `needs_review`:

1. The affected ranges are copied into `repair_queue`.
2. The workflow moves to `boundary_repair`; index generation remains unavailable.
3. `repair-context` returns the complete target range, neighboring chunk metadata, semantic candidates, and only structurally safe internal cuts.
4. `repair-boundary` replaces that single range with two or more ranges. It cannot merge existing chunks or cut outside the queued range.
5. The updated plan is written and verified immediately.
6. Exact unchanged ranges retain their prior analysis and protected Markdown body. New ranges have no inherited analysis and must be reviewed again.
7. Every completed repair is appended to `repair_history` with old/new ranges, reason, verification status, and write-reuse summary.

The generated `manifest.json` includes a `write_summary` showing reused and rewritten chunk IDs.

## MCP and agent process safety

The Node runner now provides:

- spawn-error handling
- request cancellation through `AbortSignal`
- configurable wall-clock timeout
- combined stdout/stderr byte limit
- strict JSON parsing rather than searching output for the first brace
- graceful SIGINT/SIGTERM shutdown
- isolated default output directories for concurrent `split_document` calls
- temporary-file transfer for large review and index bodies

The external Python command reviewer also has independent timeout and stdout/stderr limits, and the scheduler cancels sibling tasks after a fatal task failure.

Environment controls:

```text
DOC_SPLITTER_CLI_TIMEOUT_MS=120000
DOC_SPLITTER_MAX_OUTPUT_BYTES=8388608
DOC_SPLITTER_RUNS_DIR=/optional/run/root
```

## Validation

- Python: 109 tests passed
- Node: 7 tests passed
- Golden corpus: 10/10 matched
- Repair end-to-end test confirms one unchanged chunk body/analysis is reused while two repaired chunks are rewritten and reverified.

## Runtime smoke check

After `npm ci`, the actual MCP server was started over stdio, connected successfully, received `SIGTERM`, closed the MCP server, and exited without writing protocol noise to stdout.

## Deferred work

This phase remains provider-neutral. Direct OpenAI/Anthropic adapters, CI, lint/type-check configuration, a Python lockfile, an explicit license, and wheel-build verification remain separate release-engineering work.
