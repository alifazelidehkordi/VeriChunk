"""Extract page ranges from source PDF into semantic-named chunk PDFs."""

from __future__ import annotations

from pathlib import Path

from doc_splitter.structure_analyzer import ChunkPageRange


def write_pdf_chunks(
    source_pdf: Path,
    page_ranges: list[ChunkPageRange],
    names: list[dict[str, str]],
    output_dir: Path,
) -> None:
    import pymupdf

    source_pdf = source_pdf.expanduser().resolve()
    if not source_pdf.is_file():
        raise FileNotFoundError(f"Source PDF not found: {source_pdf}")

    src = pymupdf.open(str(source_pdf))
    try:
        for i, pr in enumerate(page_ranges):
            meta = names[i]
            out_path = output_dir / meta["file"]
            if not pr.pdf_pages:
                continue
            out = pymupdf.open()
            try:
                for page_num in pr.pdf_pages:
                    page_index = page_num - 1
                    if 0 <= page_index < src.page_count:
                        out.insert_pdf(src, from_page=page_index, to_page=page_index)
                out.save(str(out_path))
            finally:
                out.close()
    finally:
        src.close()