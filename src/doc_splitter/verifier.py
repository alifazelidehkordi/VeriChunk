"""Verify output integrity: coverage, word count, tables, images."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import save_json

TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _parse_chunk_element_ids(chunk_path: Path) -> list[str]:
    """Element IDs are tracked via manifest; chunks don't embed IDs."""
    return []


def verify_output(
    ir: DocumentIR,
    output_dir: Path,
    config: SplitConfig,
) -> dict:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {output_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunks = manifest.get("chunks", [])
    errors: list[str] = []
    warnings: list[str] = []

    skipped_pages = {p.page for p in ir.meta.skipped_pages}
    expected_ids = [
        el.id
        for el in ir.elements
        if el.page is None or el.page not in skipped_pages
    ]
    found_ids: list[str] = []
    chunk_word_total = 0

    for chunk in chunks:
        chunk_file = output_dir / chunk["file"]
        if not chunk_file.exists():
            errors.append(f"Missing chunk file: {chunk['file']}")
            continue
        found_ids.extend(chunk.get("element_ids", []))
        chunk_word_total += int(chunk.get("word_count", 0))

        content = chunk_file.read_text(encoding="utf-8")
        for el_id in chunk.get("element_ids", []):
            el = ir.element_by_id(el_id)
            if el is None:
                continue
            if el.type == "table":
                expected_rows = len(el.rows)
                actual_rows = sum(
                    1 for line in content.splitlines() if TABLE_ROW_RE.match(line)
                )
                if actual_rows < expected_rows:
                    errors.append(
                        f"Table {el_id} in {chunk['file']}: expected {expected_rows} rows, found {actual_rows}"
                    )
            if el.type == "image" and el.ref:
                if el.ref not in content:
                    errors.append(f"Image ref {el.ref} missing from {chunk['file']}")

    id_counts = Counter(found_ids)
    for el_id, count in id_counts.items():
        if count != 1:
            errors.append(f"Element {el_id} appears {count} times (expected 1)")

    expected_set = set(expected_ids)
    found_set = set(found_ids)
    missing = expected_set - found_set
    extra = found_set - expected_set
    for el_id in sorted(missing):
        errors.append(f"Element {el_id} missing from all chunks")
    for el_id in sorted(extra):
        errors.append(f"Unknown element {el_id} in chunks")

    tolerance = config.word_count_tolerance(ir.meta.total_word_count)
    word_diff = abs(chunk_word_total - ir.meta.total_word_count)
    word_ok = word_diff <= tolerance
    if not word_ok:
        errors.append(
            f"Word count mismatch: chunks={chunk_word_total}, ir={ir.meta.total_word_count}, "
            f"diff={word_diff}, tolerance={tolerance}"
        )

    if skipped_pages:
        warnings.append(
            f"{len(skipped_pages)} page(s) skipped (OCR required, out of scope): "
            f"{sorted(skipped_pages)}"
        )

    report = {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "coverage": {
            "expected_elements": len(expected_ids),
            "found_elements": len(found_set),
            "missing": sorted(missing),
            "duplicate": [eid for eid, c in id_counts.items() if c != 1],
        },
        "word_count": {
            "ir_total": ir.meta.total_word_count,
            "chunk_total": chunk_word_total,
            "difference": word_diff,
            "tolerance": tolerance,
            "passed": word_ok,
        },
        "skipped_pages": [
            {"page": p.page, "reason": p.reason} for p in ir.meta.skipped_pages
        ],
        "reconciliation_notes": ir.meta.reconciliation_notes,
    }

    save_json(report, output_dir / "verification-report.json")
    return report