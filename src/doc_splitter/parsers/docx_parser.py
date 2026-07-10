"""Parse DOCX files into DocumentIR using python-docx."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Protocol

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.parsers._ids import next_element_id
from doc_splitter.section_titles import looks_like_section_title

HEADING_STYLES = {
    "Heading 1": 1,
    "Heading 2": 2,
    "Heading 3": 3,
    "heading 1": 1,
    "heading 2": 2,
    "heading 3": 3,
    "Title": 1,
}
_BULLET_PREFIX_RE = re.compile(r"^[\-\*\u2022\u2023\u25E6\u2043\u2219]\s*")
_DRAWING_BLIP_TAG = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_EMBED_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


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


def _is_list_paragraph(paragraph) -> bool:
    style_name = paragraph.style.name if paragraph.style else ""
    if style_name and style_name.casefold().startswith("list"):
        return True
    paragraph_properties = paragraph._p.pPr
    if paragraph_properties is not None and paragraph_properties.numPr is not None:
        return True
    return bool(_BULLET_PREFIX_RE.match(paragraph.text.strip()))


def _clean_list_item(text: str) -> str:
    return _BULLET_PREFIX_RE.sub("", text.strip()).strip()


class _ImagePart(Protocol):
    blob: bytes
    partname: object
    content_type: str


def _image_suffix(part: _ImagePart) -> str:
    part_name = str(getattr(part, "partname", ""))
    suffix = Path(part_name).suffix.lower()
    if suffix:
        return suffix
    content_type = str(getattr(part, "content_type", ""))
    guessed = mimetypes.guess_extension(content_type) if content_type else None
    return guessed or ".bin"


def _paragraph_image_parts(paragraph, document) -> list[_ImagePart]:
    parts: list[_ImagePart] = []
    for run in paragraph.runs:
        for node in run._element.iter():
            if node.tag != _DRAWING_BLIP_TAG:
                continue
            embed_id = node.get(_EMBED_ATTR)
            if not embed_id:
                continue
            part = document.part.related_parts.get(embed_id)
            if part is not None:
                parts.append(part)
    return parts


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
    pending_list_items: list[str] = []

    if images_dir is not None and config.image_extraction:
        images_dir.mkdir(parents=True, exist_ok=True)

    def append_element(**kwargs) -> None:
        nonlocal counter
        element_id, counter = next_element_id(counter)
        elements.append(Element(id=element_id, **kwargs))

    def flush_list() -> None:
        if not pending_list_items:
            return
        append_element(type="list", items=list(pending_list_items))
        pending_list_items.clear()

    for block in _iter_block_items(document):
        if block.__class__.__name__ != "Paragraph":
            flush_list()
            rows = _table_rows(block)
            if rows:
                append_element(type="table", rows=rows)
            continue

        text = block.text.strip()
        image_parts = _paragraph_image_parts(block, document)
        level = _heading_level(block.style.name if block.style else None)
        is_list = bool(text) and _is_list_paragraph(block)

        if is_list:
            item = _clean_list_item(text)
            if item:
                pending_list_items.append(item)
        else:
            flush_list()
            if text:
                if level is not None:
                    append_element(type="heading", text=text, level=level)
                elif looks_like_section_title(text):
                    append_element(type="heading", text=text, level=2)
                else:
                    append_element(type="paragraph", text=text)

        if image_parts:
            # Images are source elements even when their paragraph contains no text.
            # A centered text paragraph may act as a caption; ordinary surrounding
            # prose remains a separate paragraph and is not duplicated as a caption.
            flush_list()
            caption = text if text and block.alignment == WD_PARAGRAPH_ALIGNMENT.CENTER else None
            for part in image_parts:
                if not config.image_extraction or images_dir is None:
                    continue
                image_counter += 1
                suffix = _image_suffix(part)
                filename = f"img-{image_counter:02d}{suffix}"
                output_path = images_dir / filename
                output_path.write_bytes(part.blob)
                append_element(
                    type="image",
                    ref=f"images/{filename}",
                    caption=caption,
                    content_sha256=hashlib.sha256(part.blob).hexdigest(),
                )

    flush_list()

    meta = DocumentMeta(source_file=path.name)
    ir = DocumentIR(elements=elements, meta=meta)
    ir.recompute_word_counts()
    for element in ir.elements:
        if element.page_number is None:
            prior_words = element.cumulative_word_count - element.word_count
            element.page_number = max(
                1,
                (prior_words + config.words_per_page - 1) // config.words_per_page,
            )
    meta.estimated_total_pages = max(
        1,
        (meta.total_word_count + config.words_per_page - 1) // config.words_per_page,
    )
    return ir
