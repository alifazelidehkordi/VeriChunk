# Phase-zero baseline

Date: 2026-07-10  
Branch: `phase-0-baseline`  
Pre-cleanup snapshot: `fc25f6d`

## Scope completed

- Captured all pre-existing tracked and untracked source changes in a dedicated
  Git snapshot. This includes `src/doc_splitter/topic_reviews.py`.
- Removed generated and machine-local content from the working package:
  `node_modules`, Python bytecode, pytest cache, output artifacts, and Claude
  local cache/settings.
- Removed the tracked personal `.mcp.json` and replaced it with a portable
  `.mcp.json.example`. The real `.mcp.json` is now ignored.
- Added a deterministic ten-case golden corpus covering semantic boundaries,
  page policy, blank PDF pages, DOCX lists, images, and tables.
- Added a non-strict audit command that records current behavior without
  changing desired expectations to match current bugs.
- Added tests that protect the corpus schema, required scenarios, source files,
  element references, and the agreed page policy.

## Frozen desired page policy

| Rule | Value |
|---|---:|
| Target minimum | 5 pages |
| Preferred maximum | 12 pages |
| Soft maximum | 13 pages |
| Absolute maximum | 20 pages |
| Topic change overrides minimum | Yes |
| Extension after page 13 requires semantic evidence | Yes |

## Golden baseline result

The baseline audit currently reports:

- 5 matching cases
- 4 behavioral gaps
- 1 parser error
- page-policy mismatch

Known semantic/parser gaps captured by the corpus:

1. A topic change without a heading is not detected.
2. A same-topic `Worked Example` subheading is incorrectly proposed as a split.
3. A standalone image cannot be selected as the boundary element, so the cut is
   placed before the image.
4. Standard Word `List Bullet` paragraphs and image-only paragraphs are lost or
   downgraded by the DOCX parser.
5. A blank PDF page raises `TypeError` because `SkippedPage` receives
   `page_number` instead of `page`.
6. Current defaults are 5/10/13 and have no separate soft maximum, rather than
   the desired 5/12/13/20 policy.

The machine-readable result is stored in `golden-results.json` beside this file.

## Additional baseline defect

Directly importing `doc_splitter.topic_reviews` currently triggers a circular
import through `doc_splitter.boundary.__init__` and `planner`. Existing entry
points happen to import modules in an order that masks the issue. The audit tool
uses the currently working planner import path so the corpus can still run.

## Verification commands

```bash
PYTHONPATH=src pytest -q
PYTHONPATH=src python3 scripts/audit-golden-corpus.py \
  --output docs/baseline/golden-results.json
npm ci --ignore-scripts
npm test
```

Results at this baseline:

- Python: `51 passed`
- Node: command succeeds but discovers `0 tests`; this remains a known gap for a
  later phase.

## Corpus maintenance rule

Expected outcomes in `tests/golden/corpus.json` represent product requirements,
not current implementation behavior. They must not be weakened to make a broken
implementation pass. Use `scripts/audit-golden-corpus.py --strict` only after
all required functionality has been implemented.
