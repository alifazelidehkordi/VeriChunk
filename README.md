# Document Splitter Agent

Conceptual PDF/DOCX splitter with verification, bilingual study indexes, MCP server, and CLI.

## Requirements

- Python 3.10+
- Java 11+ (for OpenDataLoader PDF reconciliation)
- Node.js 18+ (for MCP server)

## Install

```bash
cd /home/ali/Desktop/ducsplit
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
npm install
java -version   # must succeed
```

## CLI workflow

The host agent (Cursor/Grok) drives LLM steps — boundary detection and content analysis.

```bash
# 1. Parse and start boundary session
doc-splitter run --input book.pdf --out ./output --min-pages 5 --max-pages 10

# 2. Loop until status=complete
doc-splitter boundary-context --out ./output
doc-splitter commit-boundary --out ./output --action cut --element-id el-042 --reason "..."

# 3. Write chunks + verify
doc-splitter write --out ./output

# 4. Per-chunk content analysis (host agent reads context, commits analysis)
doc-splitter analysis-context --out ./output --chunk-id 1
doc-splitter commit-analysis --out ./output --chunk-id 1 \
  --topic-fa "..." --topic-en "..." --coherence confident

# 5. Generate indexes
doc-splitter index --out ./output
```

## MCP setup (Cursor / Claude Code)

Add to project `.mcp.json` or run:

```bash
claude mcp add doc-splitter -- node /home/ali/Desktop/ducsplit/server.js
```

Tools: `split_document`, `get_boundary_context`, `commit_boundary`, `write_chunks`, `get_chunk`, `verify_integrity`, `get_chunk_analysis_context`, `commit_chunk_analysis`, `generate_study_index`.

## Output layout

```
output/
├── chunk-001.md
├── images/
├── manifest.json
├── verification-report.json
├── semantic-review-report.json
├── study-index-fa.md
├── study-index-en.md
└── .split-session.json
```