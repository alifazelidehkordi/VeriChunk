# Phase one: workflow state and persistence safety

Date: 2026-07-10  
Branch: `phase-1-state-safety`

## Scope completed

Phase one closes the workflow and persistence bypasses identified during the
initial audit. It does not yet replace the heading-based semantic detector or
implement the 5/12/13/20 page policy; those remain phase-two work.

Implemented safeguards:

- Added an explicit workflow state machine.
- Topic-change review is now mandatory whenever candidates exist.
- Boundary commands are rejected until topic review reaches consensus.
- The final boundary transitions the session to `boundary_complete`.
- `write` is rejected unless the cursor reached the end of the document.
- The writer now requires exact, gap-free, overlap-free element coverage.
- The writer no longer appends the unplanned document tail as an implicit chunk.
- Every required topic review must contain enough matching independent votes.
- Every confirmed topic-change cut must appear in the final boundary plan.
- Confirmed topic changes can no longer be bypassed with
  `allow_topic_merge=True`.
- Successful write and verification advance the run to `content_analysis`.
- Failed writing or verification is recorded as a recoverable `failed` stage.
- Content analysis is rejected for unknown chunk identifiers before session
  mutation.
- Invalid or stale analysis records no longer inflate completion counts.
- Session configuration is restored without replacing persisted values with CLI
  defaults. Only explicitly supplied CLI options override saved settings.
- The current `--out` directory is authoritative after a project directory is
  moved.
- Session writes use an advisory file lock, atomic file replacement, revision
  numbers, and optimistic conflict detection.
- IR, manifest, reports, indexes, and Markdown chunk writes use atomic file
  replacement.
- The circular import between `topic_reviews` and `boundary.__init__` was
  removed with lazy planner exports.
- A single worker now still receives all reviewer slots required for consensus;
  worker count controls concurrency rather than vote count.
- Images are now structurally safe cut candidates, so a figure remains attached
  to the preceding topic and the final image can be explicitly covered.

## State machine

```text
topic_review
    ↓
boundary
    ↓
boundary_complete
    ↓
writing
    ↓
verification
    ↓
content_analysis
    ↓
index
    ↓
complete
```

Any active processing stage may enter `failed`. A failed write or verification
can be retried through the `write` command after the underlying cause is fixed.

## Write invariants

Before any output chunk can be written, all of these conditions must hold:

1. Session stage is `boundary_complete` or the internal `writing` stage.
2. `cursor_index` equals the number of IR elements.
3. Every required topic-change review has enough matching votes.
4. Every confirmed topic change has a committed cut at its exact safe boundary.
5. The first chunk starts at element zero.
6. Every subsequent chunk starts exactly after the previous chunk.
7. Every `end_element_id` matches its IR index.
8. The final boundary ends at the final IR element.

The old fallback that silently converted the unplanned tail into a final chunk
has been removed.

## Session concurrency model

`.split-session.json` now contains:

- `revision`
- `updated_at`
- `last_error`
- `failed_from`

A save succeeds only when the in-memory revision still matches the on-disk
revision. Concurrent stale writers receive `SessionConflictError` instead of
silently overwriting another agent's update.

The lock file `.split-session.json.lock` is a runtime coordination file. The
session JSON itself is replaced atomically after an `fsync`.

## Verification commands

```bash
python -m pytest -q
python -m compileall -q src tests
python scripts/audit-golden-corpus.py \
  --output docs/phase-1/golden-results.json
npm test
```

Current Python result:

- `65 passed`

The golden semantic/parser audit intentionally remains non-strict. Phase one
fixes orchestration safety, not the semantic detector or parsers. Its remaining
results are still:

- 6 matching cases
- 3 behavioral gaps
- 1 parser error
- page-policy mismatch

## Remaining planned work

The next implementation phase should address:

1. Semantic units and topic-change detection without relying on headings.
2. The preferred 12-page, soft 13-page, and absolute 20-page policy.
3. Evidence-based extension beyond page 13.
4. Multi-agent execution backend and scheduler rather than host-only batches.
5. Content-based verification instead of trusting manifest metadata.
6. PDF blank-page and DOCX list/image parser defects.
7. Real MCP tests, process timeout, cancellation, and output isolation.
