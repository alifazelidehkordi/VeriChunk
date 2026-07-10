# Phase two: semantic boundaries, page policy, and concurrent reviews

Date: 2026-07-10  
Branch: `phase-2-semantic-engine`

## Scope completed

Phase two replaces the heading-only candidate pass and implements the agreed
page policy:

- target minimum: 5 pages
- preferred maximum: 12 pages
- soft maximum: 13 pages
- absolute maximum: 20 pages

A confirmed topic change overrides the minimum size. Page 13 may be used to
finish the same concept. Every one-page extension after page 13 requires two
independent reviewer IDs and at least two cited IR element IDs. No extension can
cross a confirmed topic boundary. At the absolute cap, the chosen safe boundary
is stored as a `forced_size_split` and linked to the next chunk with continuation
metadata.

## Semantic candidate engine

`src/doc_splitter/semantic.py` scores every transition that has enough context
on both sides. Signals include:

- major heading strength
- heading-free lexical discontinuity
- shared topic terms
- concluding language before the boundary
- new-topic language after the boundary
- generic continuation headings such as worked examples and summaries

The detector uses local non-maximum suppression so one transition does not
produce a cluster of duplicate review tasks. It proposes candidates only; final
boundaries still require review consensus. Every initialized run also writes a
compact `semantic-map.json` containing the document outline and all candidate
change points so reviewers have document-wide orientation alongside local text.

The frozen IR corpus now passes all eight semantic cases:

1. major heading topic change
2. topic change without a heading
3. same-topic worked-example subheading
4. topic change before the five-page target
5. continuous 17-page topic
6. continuous 25-page topic
7. table attached to the preceding topic
8. image attached to the preceding topic

## Review model

Each candidate receives three independent roles:

1. `transition_reviewer`
2. `continuity_reviewer`
3. `adjudicator`

Review results must include:

- `decision`: `split` or `merge`
- confidence from 0 to 1
- a specific reason
- evidence element IDs before the boundary
- evidence element IDs after the boundary

Two split votes confirm a hard boundary. Merge is intentionally asymmetric: a
split minority prevents automatic merge and leaves the review pending until the
disagreement is explicitly resolved.

## Concurrent execution

`src/doc_splitter/agents/` adds a bounded-concurrency scheduler with retries and
provider-neutral backends.

### Host-managed mode

`topic-review-context` returns worker batches for MCP-host subagents. The host
collects their evidence-backed votes and commits them together.

### Command backend mode

`run-topic-reviews` can execute real reviewer processes concurrently:

```bash
doc-splitter run-topic-reviews \
  --out ./output/book \
  --workers 6 \
  --backend command \
  --agent-command './scripts/my-llm-reviewer'
```

The command receives one JSON task on stdin and must write one review JSON
object on stdout. Provider credentials and SDK choices remain outside the core
package.

A deterministic `heuristic` backend exists for tests and offline baseline runs.
It exercises concurrency and consensus but is not an independent LLM review and
must not be treated as equivalent to model agents. The MCP server also exposes
`run_parallel_topic_reviews` when the operator sets
`DOC_SPLITTER_AGENT_COMMAND`; the command itself is not accepted from arbitrary
tool input.

## Page-policy invariants

- The initial boundary window is 12 pages.
- Extensions advance exactly one page.
- Extension to page 13 needs a semantic reason.
- Extensions to page 14–20 need evidence and two independent confirmations at
  every step.
- Confirmed topic boundaries block extension.
- The hard cap cannot be configured above 20.
- A cut outside the currently approved window is rejected.
- A topic boundary before `min_pages` is presented as the exact required cut.
- Boundary and manifest records preserve `split_type`,
  `continues_to_next`, `continues_from_previous`, and extension evidence.
- Writer validation independently rejects chunks above 20 pages or chunks above
  13 pages whose extension approvals are incomplete.

## Verification commands

```bash
python -m pytest -q
python -m compileall -q src tests
PYTHONPATH=src python scripts/audit-golden-corpus.py \
  --output docs/phase-2/golden-results.json
node --check server.js
npm test
```

Current results:

- Python: 90 tests passing.
- Golden audit: all 8 semantic cases and page policy match.
- Remaining golden gaps: PDF blank-page parser error and DOCX list/image loss.
- Node command still discovers 0 tests; MCP process hardening remains a later
  phase.

## Deferred work

Phase two does not claim to solve the following items:

- content-based verifier reconstruction
- PDF blank-page parser defect
- DOCX numbering/list and standalone-image extraction
- repair loop after chunk coherence analysis
- provider-specific OpenAI/Anthropic adapters
- MCP timeout, cancellation, output limits, and actual Node test coverage
