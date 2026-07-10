"""Full PDF parse pipeline: pymupdf4llm + OpenDataLoader reconciliation."""

from __future__ import annotations

from pathlib import Path

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR
from doc_splitter.parsers.pdf_opendataloader import parse_pdf_opendataloader
from doc_splitter.parsers.pdf_pymupdf import parse_pdf_pymupdf
from doc_splitter.parsers.reconciler import reconcile_pdf_ir


def parse_pdf(path: Path, config: SplitConfig, images_dir: Path | None = None) -> DocumentIR:
    ir = parse_pdf_pymupdf(path, config, images_dir)
    try:
        layouts = parse_pdf_opendataloader(path)
        if layouts:
            ir = reconcile_pdf_ir(ir, layouts)
    except Exception as exc:
        ir.meta.reconciliation_notes.append(f"OpenDataLoader skipped: {type(exc).__name__}: {exc}")
    return ir
