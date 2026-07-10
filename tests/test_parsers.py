from __future__ import annotations

from pathlib import Path
import hashlib
import sys
import types

from doc_splitter.config import SplitConfig
from doc_splitter.parsers.docx_parser import parse_docx
from doc_splitter.parsers.pdf_pipeline import parse_pdf
from doc_splitter.parsers.pdf_pymupdf import parse_pdf_pymupdf

GOLDEN = Path(__file__).parent / "golden" / "source"


def _fake_pymupdf4llm(monkeypatch, *, fail: bool = False) -> None:
    module = types.ModuleType("pymupdf4llm")

    def to_markdown(*_args, **_kwargs):
        if fail:
            raise RuntimeError("synthetic parser failure")
        return [
            {"metadata": {"page_number": 1}, "text": "# FIRST TOPIC\n\nText."},
            {"metadata": {"page_number": 2}, "text": ""},
            {"metadata": {"page_number": 3}, "text": "# SECOND TOPIC\n\nText."},
        ]

    module.to_markdown = to_markdown
    monkeypatch.setitem(sys.modules, "pymupdf4llm", module)


def test_pdf_blank_page_is_recorded_without_crashing(tmp_path: Path, monkeypatch):
    _fake_pymupdf4llm(monkeypatch)
    ir = parse_pdf_pymupdf(
        GOLDEN / "blank-middle-page.pdf",
        SplitConfig(),
        tmp_path / "images",
    )

    assert [page.page for page in ir.meta.skipped_pages] == [2]
    assert {element.page_number for element in ir.elements} == {1, 3}


def test_pdf_uses_native_fallback_when_pymupdf4llm_fails(tmp_path: Path, monkeypatch):
    _fake_pymupdf4llm(monkeypatch, fail=True)
    ir = parse_pdf_pymupdf(
        GOLDEN / "blank-middle-page.pdf",
        SplitConfig(),
        tmp_path / "images",
    )

    assert [page.page for page in ir.meta.skipped_pages] == [2]
    assert ir.elements
    assert any("native PyMuPDF text fallback" in note for note in ir.meta.reconciliation_notes)


def test_pdf_pipeline_survives_unexpected_opendataloader_failure(tmp_path: Path, monkeypatch):
    _fake_pymupdf4llm(monkeypatch)

    def crash(_path):
        raise ValueError("malformed third-party output")

    monkeypatch.setattr("doc_splitter.parsers.pdf_pipeline.parse_pdf_opendataloader", crash)
    ir = parse_pdf(
        GOLDEN / "blank-middle-page.pdf",
        SplitConfig(),
        tmp_path / "images",
    )

    assert ir.elements
    assert any(
        "OpenDataLoader skipped: ValueError" in note
        for note in ir.meta.reconciliation_notes
    )


def test_docx_preserves_standard_list_and_standalone_image(tmp_path: Path):
    images_dir = tmp_path / "images"
    ir = parse_docx(
        GOLDEN / "list-and-standalone-image.docx",
        SplitConfig(),
        images_dir,
    )

    lists = [element for element in ir.elements if element.type == "list"]
    images = [element for element in ir.elements if element.type == "image"]
    assert len(lists) == 1
    assert lists[0].items == [
        "First standard Word bullet",
        "Second standard Word bullet",
    ]
    assert len(images) == 1
    assert images[0].ref == "images/img-01.png"
    extracted = tmp_path / images[0].ref
    assert extracted.is_file()
    assert extracted.read_bytes().startswith(b"\x89PNG")
    assert images[0].content_sha256 == hashlib.sha256(extracted.read_bytes()).hexdigest()
