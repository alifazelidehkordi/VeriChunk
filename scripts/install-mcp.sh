#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

register() {
  local cli="$1"
  shift
  if command -v "$cli" >/dev/null 2>&1; then
    echo "→ $cli"
    "$@" || echo "  (skipped: $cli returned non-zero)"
  else
    echo "⊘ $cli not installed"
  fi
}

PYTHON="$REPO/.venv/bin/python3"

register claude claude mcp add doc-splitter -s user -- env DOC_SPLITTER_PYTHON="$PYTHON" node "$REPO/server.js"
register codex codex mcp add doc-splitter -- env DOC_SPLITTER_PYTHON="$PYTHON" node "$REPO/server.js"
register grok grok mcp add doc-splitter -s user -- env DOC_SPLITTER_PYTHON="$PYTHON" node "$REPO/server.js"
register opencode opencode mcp add doc-splitter -- env DOC_SPLITTER_PYTHON="$PYTHON" node "$REPO/server.js"

echo "Done. Available MCP clients were configured with repository-local paths."
echo "For manual setup, copy $REPO/.mcp.json.example to .mcp.json and replace the placeholders."
