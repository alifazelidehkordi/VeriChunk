# Phase three: parser resilience and content-derived verification

Date: 2026-07-10  
Branch: `phase-3-parser-verifier`

## Scope completed

Phase three closes the two remaining parser gaps in the frozen corpus and
replaces metadata-only verification with direct comparison of generated files.

## PDF parser

- Fixed blank-page construction to use `SkippedPage(page=...)`.
- Missing or blank page chunks are recorded exactly once and parsing continues.
- Invalid/missing page chunks are reconciled against the real PDF page count.
- A `pymupdf4llm` exception or invalid return shape falls back to native
  PyMuPDF text extraction and adds a reconciliation note.
- OpenDataLoader now runs in an isolated Python subprocess with a conversion
  timeout; Java checks also have a timeout.
- Malformed JSON, converter errors, missing output, and unexpected integration
  errors no longer stop the primary parse result.
- PyMuPDF is now an explicit direct dependency because the parser and PDF
  verifier import it directly.

## DOCX parser

- Standard Word list styles and numbering XML are recognized as lists.
- Consecutive list paragraphs are preserved as one ordered IR list element.
- Images in empty paragraphs are no longer discarded.
- Embedded media retains its real extension rather than being forced to PNG.
- Extracted image bytes receive a SHA-256 hash in IR.
- Paragraphs, lists, images, and tables retain document block order.

## Markdown integrity format

Every source-derived element written to Markdown is enclosed in a protected
region and preceded by a stable element/type marker. Navigation comments and the
human-facing inferred title stay outside that region.

The verifier parses the actual generated file and checks:

- exactly one protected region
- exact element IDs and source order
- exact element type
- canonical rendered content for headings, paragraphs, lists, tables, and images
- word count calculated from the rendered file, not `manifest.json`
- existence, non-empty size, and SHA-256 integrity of extracted images

Replacing the file with unrelated text, deleting markers, editing one paragraph,
reordering chunks, changing a table, or replacing an image now fails
verification even when the manifest remains untouched.

## PDF verification

For PDF or `both` output, the verifier opens the real source and output PDFs. It
checks page count, page dimensions, order, and a grayscale rendered-page digest
for every page listed in each chunk. Duplicating the wrong source page or
replacing a page with visually different content fails verification.

PDF verification requires a readable source path from `SplitConfig.source_path`
or `manifest.json`.

## Compatibility note

Markdown chunks generated before version `0.3.0` do not contain protected
element markers. They must be regenerated before using the new verifier.

## Verification commands

```bash
python -m pytest -q
python -m compileall -q src tests
PYTHONPATH=src python scripts/audit-golden-corpus.py \
  --strict --output docs/phase-3/golden-results.json
node --check server.js
npm test
```

Current results:

- Python: 99 tests passing.
- Golden audit: all 10 frozen scenarios and the 5/12/13/20 page policy match.
- Direct tamper tests cover Markdown text, integrity markers, image bytes, and
  PDF page substitution.
- Node still discovers 0 tests; MCP process hardening and Node coverage remain
  deferred.

## Deferred work

- coherence repair loop after `needs_review`
- direct OpenAI and Anthropic agent adapters
- MCP timeout/cancellation/output-size hardening
- real Node integration tests
- CI, typing/linting, lockfile, license, and release packaging policy
