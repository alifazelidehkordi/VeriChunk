# Document Splitter Agent

Conceptual PDF/DOCX splitter with verification, bilingual study indexes, MCP server, and CLI.

**Repository:** https://github.com/alifazelidehkordi/ducsplit

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

# PDF-native chunks (page extract with boundary overlap)
doc-splitter run --input book.pdf --out ./output --output-format pdf --overlap-pages 1

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

## MCP setup (all AI CLIs)

After `npm install`, register the MCP server once (replace the path if you cloned elsewhere):

```bash
REPO=/home/ali/Desktop/ducsplit

# Claude Code (user + project .mcp.json)
claude mcp add doc-splitter -s user -- node "$REPO/server.js"

# Codex
codex mcp add doc-splitter -- node "$REPO/server.js"

# Grok CLI
grok mcp add doc-splitter -s user -- node "$REPO/server.js"

# OpenCode
opencode mcp add doc-splitter -- node "$REPO/server.js"
```

Or use the project `.mcp.json` (Claude Code / Grok project scope pick it up automatically).

**Tools:** `split_document`, `get_boundary_context`, `commit_boundary`, `write_chunks`, `get_chunk`, `verify_integrity`, `get_chunk_analysis_context`, `commit_chunk_analysis`, `generate_study_index`.

## Output layout

```
output/
├── 01_topic-slug.md          # or .pdf when --output-format pdf|both
├── 02_another-topic.pdf
├── images/
├── manifest.json             # semantic filenames, source_pages, pdf_pages
├── verification-report.json
├── semantic-review-report.json
├── study-index-fa.md
├── study-index-en.md
└── .split-session.json
```

### Output format options

| `--output-format` | Behavior |
|---|---|
| `markdown` (default) | Semantic `{NN}_{slug}.md` chunks |
| `pdf` | PyMuPDF page extract per chunk (PDF inputs only) |
| `both` | Writes both `.md` and `.pdf` per chunk |

`--overlap-pages N` adds N extra pages at shared boundaries so mid-page topics are not lost.