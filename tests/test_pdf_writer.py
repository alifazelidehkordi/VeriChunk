from pathlib import Path

import pymupdf

from doc_splitter.structure_analyzer import ChunkPageRange
from doc_splitter.writers.pdf_writer import write_pdf_chunks


def _make_pdf(path: Path, pages: int) -> None:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")
    doc.save(str(path))
    doc.close()


def test_write_pdf_chunks_extracts_selected_pages(tmp_path: Path):
    source = tmp_path / "source.pdf"
    _make_pdf(source, 3)

    page_ranges = [
        ChunkPageRange(1, 2, [], [2], [1, 2], [1, 2, 3]),
        ChunkPageRange(3, 3, [2], [], [3], [2, 3]),
    ]
    names = [
        {"id": "1", "slug": "part-one", "file": "01_part-one.pdf", "title": ""},
        {"id": "2", "slug": "part-two", "file": "02_part-two.pdf", "title": ""},
    ]

    write_pdf_chunks(source, page_ranges, names, tmp_path)

    out1 = pymupdf.open(str(tmp_path / "01_part-one.pdf"))
    out2 = pymupdf.open(str(tmp_path / "02_part-two.pdf"))
    try:
        assert out1.page_count == 3
        assert out2.page_count == 2
        assert "Page 1" in out1[0].get_text()
        assert "Page 3" in out2[-1].get_text()
    finally:
        out1.close()
        out2.close()
