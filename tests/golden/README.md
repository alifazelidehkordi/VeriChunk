# Phase-zero golden corpus

This corpus freezes the desired behavior before the semantic segmentation engine
is redesigned. It is deliberately independent from the current implementation.

## Contents

- Eight format-independent IR scenarios for topic boundaries and page policy.
- A three-page PDF whose middle page has no extractable text.
- A DOCX containing standard Word bullets, an image-only paragraph, and a table.
- `corpus.json`, which stores the expected semantic and parser outcomes.

Regenerate deterministic fixtures with:

```bash
PYTHONPATH=src python3 scripts/generate-golden-corpus.py
```

Record current behavior without failing on known gaps with:

```bash
PYTHONPATH=src python3 scripts/audit-golden-corpus.py \
  --output docs/baseline/golden-results.json
```

Use `--strict` only after the implementation is expected to satisfy every case.
The normal test suite validates corpus integrity; it does not redefine expected
results to match current bugs.
