"""Verify generated files against the source IR and source PDF content."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, Element
from doc_splitter.ir.serialize import save_json
from doc_splitter.markdown_codec import (
    normalize_markdown_block,
    parse_marked_elements,
    render_element,
    rendered_word_count,
)


def _chunk_expected_elements(
    ir: DocumentIR,
    chunk: dict[str, Any],
    chunk_label: str,
    errors: list[str],
) -> list[Element]:
    try:
        start = int(chunk["start_index"])
        end = int(chunk["end_index"])
    except (KeyError, TypeError, ValueError):
        errors.append(f"{chunk_label}: invalid or missing start_index/end_index")
        return []

    if start < 0 or end < start or end >= len(ir.elements):
        errors.append(
            f"{chunk_label}: invalid element range {start}-{end} for {len(ir.elements)} elements"
        )
        return []

    expected = ir.elements[start : end + 1]
    expected_ids = [element.id for element in expected]
    manifest_ids = [str(value) for value in chunk.get("element_ids", [])]
    if manifest_ids != expected_ids:
        errors.append(
            f"{chunk_label}: manifest element_ids do not match IR range; "
            f"expected {expected_ids}, found {manifest_ids}"
        )
    expected_words = sum(element.word_count for element in expected)
    try:
        manifest_words = int(chunk.get("word_count", -1))
    except (TypeError, ValueError):
        manifest_words = -1
    if manifest_words != expected_words:
        errors.append(
            f"{chunk_label}: manifest word_count={manifest_words}, expected {expected_words}"
        )
    return expected


def _verify_markdown_file(
    path: Path,
    expected: list[Element],
    output_dir: Path,
    chunk_label: str,
    errors: list[str],
) -> tuple[list[str], int]:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{chunk_label}: Markdown is not valid UTF-8: {exc}")
        return [], 0

    parsed, parse_errors = parse_marked_elements(content)
    errors.extend(f"{chunk_label}: {message}" for message in parse_errors)

    expected_ids = [element.id for element in expected]
    actual_ids = [item.element_id for item in parsed]
    if actual_ids != expected_ids:
        errors.append(
            f"{chunk_label}: actual Markdown element order/content markers differ; "
            f"expected {expected_ids}, found {actual_ids}"
        )

    actual_word_total = 0
    expected_by_id = {element.id: element for element in expected}
    for item in parsed:
        element = expected_by_id.get(item.element_id)
        if element is None:
            errors.append(f"{chunk_label}: unknown element marker {item.element_id}")
            actual_word_total += rendered_word_count(item.body, item.element_type)
            continue
        if item.element_type != element.type:
            errors.append(
                f"{chunk_label}: element {element.id} type changed from "
                f"{element.type} to {item.element_type}"
            )
        expected_body = normalize_markdown_block(render_element(element))
        actual_body = normalize_markdown_block(item.body)
        if actual_body != expected_body:
            errors.append(f"{chunk_label}: rendered content mismatch for element {element.id}")
        actual_word_total += rendered_word_count(actual_body, element.type)

        if element.type == "image" and element.ref:
            image_path = output_dir / element.ref
            if not image_path.is_file():
                errors.append(f"{chunk_label}: referenced image file is missing: {element.ref}")
            elif image_path.stat().st_size == 0:
                errors.append(f"{chunk_label}: referenced image file is empty: {element.ref}")
            elif element.content_sha256:
                actual_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
                if actual_hash != element.content_sha256:
                    errors.append(f"{chunk_label}: image content hash mismatch: {element.ref}")

    return actual_ids, actual_word_total


def _page_visual_digest(page: Any, pymupdf: Any) -> str:
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(1, 1),
        colorspace=pymupdf.csGRAY,
        alpha=False,
        annots=True,
    )
    digest = hashlib.sha256()
    digest.update(f"{pixmap.width}x{pixmap.height}:{page.rotation}".encode("ascii"))
    digest.update(pixmap.samples)
    return digest.hexdigest()


def _resolve_source_path(manifest: dict[str, Any], config: SplitConfig) -> Path | None:
    candidates: list[Path] = []
    if config.source_path:
        candidates.append(Path(config.source_path))
    source_path = manifest.get("source_path")
    if source_path:
        candidates.append(Path(str(source_path)))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    return None


def _verify_pdf_file(
    output_pdf: Path,
    source_doc: Any,
    source_pages: list[int],
    chunk_label: str,
    errors: list[str],
    pymupdf: Any,
) -> bool:
    try:
        output_doc = pymupdf.open(str(output_pdf))
    except Exception as exc:
        errors.append(f"{chunk_label}: cannot open output PDF: {exc}")
        return False

    matched = True
    try:
        if output_doc.page_count != len(source_pages):
            errors.append(
                f"{chunk_label}: PDF page count is {output_doc.page_count}; "
                f"expected {len(source_pages)}"
            )
            matched = False

        for output_index, source_page_number in enumerate(source_pages):
            if output_index >= output_doc.page_count:
                break
            source_index = source_page_number - 1
            if source_index < 0 or source_index >= source_doc.page_count:
                errors.append(
                    f"{chunk_label}: source page {source_page_number} is outside source PDF"
                )
                matched = False
                continue
            source_page = source_doc[source_index]
            output_page = output_doc[output_index]
            source_rect = tuple(round(value, 3) for value in source_page.rect)
            output_rect = tuple(round(value, 3) for value in output_page.rect)
            if source_rect != output_rect:
                errors.append(
                    f"{chunk_label}: output page {output_index + 1} dimensions differ "
                    f"from source page {source_page_number}"
                )
                matched = False
                continue
            if _page_visual_digest(source_page, pymupdf) != _page_visual_digest(
                output_page, pymupdf
            ):
                errors.append(
                    f"{chunk_label}: output page {output_index + 1} does not match "
                    f"source page {source_page_number}"
                )
                matched = False
    finally:
        output_doc.close()
    return matched


def verify_output(
    ir: DocumentIR,
    output_dir: Path,
    config: SplitConfig,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {output_dir}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest.json is invalid: {exc}") from exc

    chunks = manifest.get("chunks", [])
    if not isinstance(chunks, list):
        raise ValueError("manifest.json field 'chunks' must be a list")

    output_format = str(manifest.get("output_format", config.output_format))
    if output_format not in {"markdown", "pdf", "both"}:
        raise ValueError(f"Unsupported output format in manifest: {output_format}")

    errors: list[str] = []
    warnings: list[str] = []
    skipped_pages = {page.page for page in ir.meta.skipped_pages}
    expected_ids = [
        element.id
        for element in ir.elements
        if element.page_number is None or element.page_number not in skipped_pages
    ]

    source_doc = None
    pymupdf = None
    source_path: Path | None = None
    if output_format in {"pdf", "both"}:
        source_path = _resolve_source_path(manifest, config)
        if source_path is None:
            errors.append(
                "Cannot verify PDF content without a readable source_path in config or manifest"
            )
        else:
            try:
                import pymupdf as _pymupdf

                pymupdf = _pymupdf
                source_doc = pymupdf.open(str(source_path))
            except Exception as exc:
                errors.append(f"Cannot open source PDF for verification: {exc}")

    actual_ids: list[str] = []
    planned_ids: list[str] = []
    actual_word_total = 0
    covered_pages: set[int] = set()

    try:
        for position, raw_chunk in enumerate(chunks, start=1):
            if not isinstance(raw_chunk, dict):
                errors.append(f"Chunk {position}: manifest entry must be an object")
                continue
            chunk = raw_chunk
            chunk_label = f"Chunk {position}"
            expected_elements = _chunk_expected_elements(ir, chunk, chunk_label, errors)
            planned_ids.extend(element.id for element in expected_elements)

            markdown_name = chunk.get("markdown_file")
            primary_name = chunk.get("file")
            if not markdown_name and isinstance(primary_name, str) and primary_name.endswith(".md"):
                markdown_name = primary_name

            pdf_name = chunk.get("pdf_file")
            if not pdf_name and isinstance(primary_name, str) and primary_name.endswith(".pdf"):
                pdf_name = primary_name

            markdown_verified = False
            if output_format in {"markdown", "both"}:
                if not markdown_name:
                    errors.append(f"{chunk_label}: Markdown filename is missing")
                else:
                    markdown_path = output_dir / str(markdown_name)
                    if not markdown_path.is_file():
                        errors.append(f"Missing chunk file: {markdown_name}")
                    else:
                        ids, words = _verify_markdown_file(
                            markdown_path,
                            expected_elements,
                            output_dir,
                            chunk_label,
                            errors,
                        )
                        actual_ids.extend(ids)
                        actual_word_total += words
                        markdown_verified = True

            pdf_verified = False
            if output_format in {"pdf", "both"}:
                if not pdf_name:
                    errors.append(f"{chunk_label}: PDF filename is missing")
                else:
                    pdf_path = output_dir / str(pdf_name)
                    if not pdf_path.is_file():
                        errors.append(f"Missing chunk file: {pdf_name}")
                    elif source_doc is not None and pymupdf is not None:
                        raw_pages = chunk.get("pdf_pages", chunk.get("source_pages", []))
                        if not isinstance(raw_pages, (list, tuple)):
                            errors.append(f"{chunk_label}: invalid pdf_pages")
                            pdf_pages = []
                        else:
                            try:
                                pdf_pages = [int(page) for page in raw_pages]
                            except (TypeError, ValueError):
                                errors.append(f"{chunk_label}: invalid pdf_pages")
                                pdf_pages = []
                        pdf_verified = _verify_pdf_file(
                            pdf_path,
                            source_doc,
                            pdf_pages,
                            chunk_label,
                            errors,
                            pymupdf,
                        )
                        if pdf_verified:
                            covered_pages.update(
                                page for page in pdf_pages if page not in skipped_pages
                            )

            if output_format == "pdf" and pdf_verified:
                actual_ids.extend(element.id for element in expected_elements)
            if output_format == "both" and not markdown_verified and pdf_verified:
                # PDF content is still checked, but source-element verification requires Markdown.
                warnings.append(
                    f"{chunk_label}: PDF matched source pages but Markdown element verification failed"
                )
    finally:
        if source_doc is not None:
            source_doc.close()

    if planned_ids != expected_ids:
        errors.append("Manifest chunk ranges do not cover IR elements exactly once in source order")
    if actual_ids != expected_ids:
        errors.append("Verified chunk content does not preserve the complete source element order")

    planned_counts = Counter(planned_ids)
    for element_id, count in planned_counts.items():
        if count != 1:
            errors.append(f"Element {element_id} appears in {count} manifest ranges (expected 1)")

    id_counts = Counter(actual_ids)
    for element_id, count in id_counts.items():
        if count != 1:
            errors.append(f"Element {element_id} appears {count} times in actual files")

    expected_set = set(expected_ids)
    actual_set = set(actual_ids)
    missing = expected_set - actual_set
    extra = actual_set - expected_set
    for element_id in sorted(missing):
        errors.append(f"Element {element_id} missing from verified chunk content")
    for element_id in sorted(extra):
        errors.append(f"Unknown element {element_id} found in verified chunk content")

    word_method = (
        "rendered_markdown" if output_format in {"markdown", "both"} else "pdf_page_identity"
    )
    if output_format in {"markdown", "both"}:
        tolerance = config.word_count_tolerance(ir.meta.total_word_count)
        word_diff = abs(actual_word_total - ir.meta.total_word_count)
        word_ok = word_diff <= tolerance
        if not word_ok:
            errors.append(
                f"Word count mismatch from actual Markdown: chunks={actual_word_total}, "
                f"ir={ir.meta.total_word_count}, diff={word_diff}, tolerance={tolerance}"
            )
    else:
        tolerance = 0
        word_diff = 0
        word_ok = not missing and not extra

    if output_format in {"pdf", "both"}:
        expected_doc_pages = set(range(1, ir.meta.estimated_total_pages + 1)) - skipped_pages
        missing_pages = sorted(expected_doc_pages - covered_pages)
        if missing_pages:
            errors.append(
                "PDF page coverage gap after content comparison: "
                f"{missing_pages[:20]}" + ("..." if len(missing_pages) > 20 else "")
            )

    if skipped_pages:
        warnings.append(
            f"{len(skipped_pages)} page(s) skipped (OCR required, out of scope): "
            f"{sorted(skipped_pages)}"
        )

    report: dict[str, Any] = {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "coverage": {
            "expected_elements": len(expected_ids),
            "verified_elements": len(actual_set),
            "missing": sorted(missing),
            "duplicate": sorted(
                element_id for element_id, count in id_counts.items() if count != 1
            ),
        },
        "word_count": {
            "method": word_method,
            "ir_total": ir.meta.total_word_count,
            "chunk_total": actual_word_total if output_format in {"markdown", "both"} else None,
            "difference": word_diff if output_format in {"markdown", "both"} else None,
            "tolerance": tolerance if output_format in {"markdown", "both"} else None,
            "passed": word_ok,
        },
        "pdf_source": str(source_path) if source_path else None,
        "skipped_pages": [
            {"page": page.page, "reason": page.reason} for page in ir.meta.skipped_pages
        ],
        "reconciliation_notes": ir.meta.reconciliation_notes,
    }
    save_json(report, output_dir / "verification-report.json")
    return report
