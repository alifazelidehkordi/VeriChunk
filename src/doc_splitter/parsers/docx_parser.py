"""Parse DOCX files into DocumentIR using python-docx."""

from __future__ import annotations

import re
from pathlib import Path

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.parsers._ids import next_element_id

HEADING_STYLES = {
    "Heading 1": 1,
    "Heading 2": 2,
    "Heading 3": 3,
    "heading 1": 1,
    "heading 2": 2,
    "heading 3": 3,
    "Title": 1,
}


def _heading_level(style_name: str | None) -> int | None:
    if not style_name:
        return None
    if style_name in HEADING_STYLES:
        return HEADING_STYLES[style_name]
    match = re.match(r"heading\s*(\d+)", style_name, re.IGNORECASE)
    if match:
        return min(int(match.group(1)), 3)
    return None


def _table_rows(table) -> list[list[str]]:
    return [[cell.text.strip() for cell in row.cells] for row in table.rows]


def _iter_block_items(document):
    from docx.document import Document as DocxDocument
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    parent = document.element.body
    for child in parent.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def parse_docx(path: Path, config: SplitConfig, images_dir: Path | None = None) -> DocumentIR:
    try:
        from docx import Document
        from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is not installed. Install with: pip install python-docx"
        ) from exc

    path = path.expanduser().resolve()
    document = Document(str(path))
    elements: list[Element] = []
    counter = 0
    image_counter = 0

    if images_dir is not None and config.image_extraction:
        images_dir.mkdir(parents=True, exist_ok=True)

    for block in _iter_block_items(document):
        if block.__class__.__name__ == "Paragraph":
            text = block.text.strip()
            if not text:
                continue
            level = _heading_level(block.style.name if block.style else None)
            el_id, counter = next_element_id(counter)
            if level is not None:
                elements.append(Element(id=el_id, type="heading", text=text, level=level))
            elif re.match(r"^[\-\*\u2022\u2023\u25E6\u2043\u2219]", text):
                items = [line.strip().lstrip("-*• ").strip() for line in text.splitlines() if line.strip()]
                elements.append(Element(id=el_id, type="list", items=items))
            else:
                elements.append(Element(id=el_id, type="paragraph", text=text))

            for run in block.runs:
                for drawing in run._element.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"):
                    if not config.image_extraction or images_dir is None:
                        continue
                    embed_id = drawing.get(
                        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
                    )
                    if not embed_id:
                        continue
                    part = document.part.related_parts.get(embed_id)
                    if part is None:
                        continue
                    image_counter += 1
                    ref = f"images/img-{image_counter:02d}.png"
                    out_path = images_dir / f"img-{image_counter:02d}.png"
                    out_path.write_bytes(part.blob)
                    img_id, counter = next_element_id(counter)
                    elements.append(
                        Element(
                            id=img_id,
                            type="image",
                            ref=ref,
                            caption=text if block.alignment == WD_PARAGRAPH_ALIGNMENT.CENTER else None,
                        )
                    )
        else:
            rows = _table_rows(block)
            if not rows:
                continue
            el_id, counter = next_element_id(counter)
            elements.append(Element(id=el_id, type="table", rows=rows))

    meta = DocumentMeta(source_file=path.name)
    ir = DocumentIR(elements=elements, meta=meta)
    ir.recompute_word_counts()
    meta.estimated_total_pages = max(
        1, (meta.total_word_count + config.words_per_page - 1) // config.words_per_page
    )
    return ir