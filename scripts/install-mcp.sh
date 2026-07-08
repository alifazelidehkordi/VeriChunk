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

register claude claude mcp add doc-splitter -s user -- node "$REPO/server.js"
register codex codex mcp add doc-splitter -- node "$REPO/server.js"
register grok grok mcp add doc-splitter -s user -- node "$REPO/server.js"
register opencode opencode mcp add doc-splitter -- node "$REPO/server.js"

echo "Done. Project .mcp.json is at $REPO/.mcp.json"