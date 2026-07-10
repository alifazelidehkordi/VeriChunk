#!/usr/bin/env python3
"""Audit current behavior against the phase-zero golden corpus.

By default this command records gaps without failing. Use --strict when the
implementation is expected to satisfy every golden requirement.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import types
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doc_splitter.boundary.planner import find_topic_change_candidates  # noqa: E402
from doc_splitter.config import SplitConfig  # noqa: E402
from doc_splitter.ir.serialize import load_ir  # noqa: E402
from doc_splitter.parsers.docx_parser import parse_docx  # noqa: E402
from doc_splitter.parsers.pdf_pymupdf import parse_pdf_pymupdf  # noqa: E402

GOLDEN = ROOT / "tests" / "golden"


@contextmanager
def _fake_pymupdf4llm_for_blank_page() -> Iterator[None]:
    """Inject deterministic page chunks so blank-page handling is exercised."""
    previous = sys.modules.get("pymupdf4llm")
    module = types.ModuleType("pymupdf4llm")

    def to_markdown(*_args, **_kwargs):
        return [
            {"metadata": {"page_number": 1}, "text": "# FIRST TOPIC\n\nText."},
            {"metadata": {"page_number": 2}, "text": ""},
            {"metadata": {"page_number": 3}, "text": "# SECOND TOPIC\n\nText."},
        ]

    module.to_markdown = to_markdown
    sys.modules["pymupdf4llm"] = module
    try:
        yield
    finally:
        if previous is None:
            sys.modules.pop("pymupdf4llm", None)
        else:
            sys.modules["pymupdf4llm"] = previous


def _audit_ir(case: dict) -> dict:
    ir = load_ir(GOLDEN / case["source"])
    current = find_topic_change_candidates(ir, SplitConfig())
    detected = [candidate.boundary_element_id for candidate in current]
    expected = case["expected"].get("topic_boundaries_after", [])
    return {
        "id": case["id"],
        "kind": case["kind"],
        "status": "match" if detected == expected else "gap",
        "expected_topic_boundaries_after": expected,
        "detected_topic_boundaries_after": detected,
        "unexpected": sorted(set(detected) - set(expected)),
        "missing": sorted(set(expected) - set(detected)),
        "page_policy": case["expected"].get("page_policy"),
    }


def _audit_pdf(case: dict) -> dict:
    source = GOLDEN / case["source"]
    try:
        with tempfile.TemporaryDirectory(prefix="golden-pdf-") as tmp:
            with _fake_pymupdf4llm_for_blank_page():
                ir = parse_pdf_pymupdf(source, SplitConfig(), Path(tmp))
        skipped = [page.page for page in ir.meta.skipped_pages]
        expected = case["expected"]["skipped_pages"]
        status = "match" if skipped == expected else "gap"
        return {
            "id": case["id"],
            "kind": case["kind"],
            "status": status,
            "expected_skipped_pages": expected,
            "detected_skipped_pages": skipped,
        }
    except Exception as exc:  # Baseline audit must record, not hide, current failures.
        return {
            "id": case["id"],
            "kind": case["kind"],
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _audit_docx(case: dict) -> dict:
    source = GOLDEN / case["source"]
    try:
        with tempfile.TemporaryDirectory(prefix="golden-docx-") as tmp:
            ir = parse_docx(source, SplitConfig(), Path(tmp))
        counts = Counter(element.type for element in ir.elements)
        expected_counts = case["expected"]["minimum_element_counts"]
        missing_counts = {
            kind: minimum - counts.get(kind, 0)
            for kind, minimum in expected_counts.items()
            if counts.get(kind, 0) < minimum
        }
        expected_items = case["expected"]["list_items"]
        actual_items = [
            item for element in ir.elements if element.type == "list" for item in element.items
        ]
        missing_items = [item for item in expected_items if item not in actual_items]
        status = "match" if not missing_counts and not missing_items else "gap"
        return {
            "id": case["id"],
            "kind": case["kind"],
            "status": status,
            "element_counts": dict(sorted(counts.items())),
            "missing_element_counts": missing_counts,
            "missing_list_items": missing_items,
        }
    except Exception as exc:
        return {
            "id": case["id"],
            "kind": case["kind"],
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _audit_page_policy(corpus: dict) -> dict:
    desired = corpus["desired_page_policy"]
    current = SplitConfig()
    observed = {
        "target_min_pages": current.min_pages,
        "preferred_max_pages": current.max_pages,
        "soft_max_pages": current.soft_max_pages,
        "hard_max_pages": current.hard_max_pages,
    }
    comparable = {
        "target_min_pages": desired["target_min_pages"],
        "preferred_max_pages": desired["preferred_max_pages"],
        "soft_max_pages": desired["soft_max_pages"],
        "hard_max_pages": desired["hard_max_pages"],
    }
    return {
        "status": "match" if observed == comparable else "gap",
        "desired": comparable,
        "observed": observed,
    }


def run() -> dict:
    corpus = json.loads((GOLDEN / "corpus.json").read_text(encoding="utf-8"))
    results = []
    for case in corpus["cases"]:
        if case["kind"] == "ir":
            results.append(_audit_ir(case))
        elif case["kind"] == "pdf":
            results.append(_audit_pdf(case))
        elif case["kind"] == "docx":
            results.append(_audit_docx(case))
        else:
            results.append({"id": case["id"], "kind": case["kind"], "status": "unsupported"})

    counts = Counter(result["status"] for result in results)
    return {
        "schema_version": 1,
        "corpus_schema_version": corpus["schema_version"],
        "page_policy": _audit_page_policy(corpus),
        "summary": dict(sorted(counts.items())),
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report = run()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")

    has_gap = report["page_policy"]["status"] != "match" or any(
        case["status"] != "match" for case in report["cases"]
    )
    return 1 if args.strict and has_gap else 0


if __name__ == "__main__":
    raise SystemExit(main())
