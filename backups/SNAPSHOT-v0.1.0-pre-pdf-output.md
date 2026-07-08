# Snapshot: v0.1.0-pre-pdf-output

**Date:** 2026-07-08  
**Purpose:** Baseline backup before implementing PDF-native output, semantic naming, and IR page_number/bbox improvements.

## What this version includes

- Python pipeline: parse (pymupdf4llm + OpenDataLoader) → IR → boundary session → Markdown chunks
- Node MCP server (`server.js`) with 9 tools
- CLI: `doc-splitter run|write|verify|index|...`
- Output format: **Markdown only** (`chunk-001.md`, `chunk-002.md`, ...)
- IR fields: `page` (optional), `bbox` (optional, PDF only after reconciliation)
- Host-agent driven boundary detection and content analysis

## Test runs preserved (in `output/`)

| Run | Source | Chunks |
|-----|--------|--------|
| `output/4pdf/` | 4.pdf (82 pp) | 7 |
| `output/nvc/` | Nonviolent Communication (317 pp) | 21 |
| `output/methodology2/` | Methodology 2.pdf (170 pp) | 13 |

## Backup artifacts

| Artifact | Path | Size |
|----------|------|------|
| Git tag | `v0.1.0-pre-pdf-output` (commit `b9a193b`) | source only |
| Tarball (full, incl. `output/`) | `backups/ducsplit-v0.1.0-pre-pdf-output.tar.gz` | ~363 MB |
| Tarball copy | `/home/ali/Desktop/ducsplit-backup-v0.1.0-pre-pdf-output.tar.gz` | same |

## Restore

```bash
# From git tag (source code only, no output/)
cd /home/ali/Desktop/ducsplit
git checkout v0.1.0-pre-pdf-output

# From tarball (includes output/ test runs)
tar -xzf backups/ducsplit-v0.1.0-pre-pdf-output.tar.gz -C /home/ali/Desktop
```

## Next planned changes (not in this snapshot)

- `output_format: pdf | markdown | both`
- Semantic filenames: `03_musculoskeletal-exam.pdf`
- `page_number` + `bbox` on all IR elements
- Boundary page overlap policy