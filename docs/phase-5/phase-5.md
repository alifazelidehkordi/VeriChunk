# Phase 5: provider adapters and release hardening

Date: 2026-07-10

## Scope

- Added direct asynchronous OpenAI Responses API and Anthropic Messages API reviewer backends.
- Kept provider SDKs optional through `openai`, `anthropic`, and `agents` extras.
- Restricted API keys to environment variables; keys are not accepted in MCP inputs or persisted state.
- Added a reproducible `uv.lock` covering runtime, provider, and development dependencies.
- Added Ruff formatting/linting and Mypy checks for the Python package.
- Added GitHub Actions jobs for Python compatibility, quality/build checks, Node tests, and package smoke installation.
- Added an MIT license and complete package metadata.
- Added real wheel and source-distribution build/install validation.

## Supported review backends

| Backend | Configuration |
|---|---|
| MCP host | Host reads tasks and submits votes through `commit_topic_change_reviews`. |
| `command` | `DOC_SPLITTER_AGENT_COMMAND` or CLI `--agent-command`. |
| `openai` | `OPENAI_API_KEY` and an explicit model or `DOC_SPLITTER_OPENAI_MODEL`. |
| `anthropic` | `ANTHROPIC_API_KEY` and an explicit model or `DOC_SPLITTER_ANTHROPIC_MODEL`. |
| `heuristic` | Offline tests and deterministic baselines only. |

Provider responses are normalized into the same evidence-backed review schema before consensus is committed.

## Release verification

```bash
uv sync --frozen --extra dev --extra agents
uv run ruff check .
uv run ruff format --check .
uv run mypy src/doc_splitter
uv run pytest -q
npm ci
npm test
uv build
```

## Verified results

- Python tests: **113 passed**.
- Node/MCP tests: **10 passed**.
- Golden corpus: **10/10 matched**, including the 5/12/13/20 page policy.
- Ruff lint and formatting checks pass.
- Mypy reports no issues across 38 source files.
- Wheel and source distribution build successfully.
- The wheel installs in an isolated environment and exposes a working `doc-splitter` CLI.
- Provider adapter tests use simulated SDK clients; no live OpenAI or Anthropic API request was made during this phase.
