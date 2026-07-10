"""Parse PDF into IR using pymupdf4llm."""

from __future__ import annotations

import hashlib
import importlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element, SkippedPage
from doc_splitter.parsers._ids import next_element_id
from doc_splitter.section_titles import BOLD_ONLY_RE, looks_like_section_title, normalize_title_text

HEADING_MD_RE = re.compile(r"^(#{1,3})\s+(.+)$")
TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
LIST_ITEM_RE = re.compile(r"^[\-\*]\s+(.+)$")
IMAGE_MD_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")


def _load(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise RuntimeError(f"Missing dependency {name}: {exc}") from exc


def _page_number(chunk: dict[str, Any]) -> int | None:
    meta = chunk.get("metadata")
    if isinstance(meta, dict):
        page = meta.get("page_number")
        if isinstance(page, int):
            return page
    return None


def _parse_markdown_lines(
    lines: list[str],
    page: int,
    counter: int,
    images_dir: Path | None,
    image_counter: int,
) -> tuple[list[Element], int, int]:
    elements: list[Element] = []
    paragraph_buf: list[str] = []
    list_buf: list[str] = []
    table_buf: list[list[str]] = []

    def flush_paragraph() -> None:
        nonlocal counter
        if not paragraph_buf:
            return
        text = "\n".join(paragraph_buf).strip()
        paragraph_buf.clear()
        if not text:
            return
        el_id, counter = next_element_id(counter)
        elements.append(Element(id=el_id, type="paragraph", text=text, page_number=page))

    def flush_list() -> None:
        nonlocal counter
        if not list_buf:
            return
        items = list_buf[:]
        list_buf.clear()
        el_id, counter = next_element_id(counter)
        elements.append(Element(id=el_id, type="list", items=items, page_number=page))

    def flush_table() -> None:
        nonlocal counter
        if not table_buf:
            return
        rows = table_buf[:]
        table_buf.clear()
        if len(rows) >= 1:
            el_id, counter = next_element_id(counter)
            elements.append(Element(id=el_id, type="table", rows=rows, page_number=page))

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_table()
            continue

        bold_only = BOLD_ONLY_RE.match(line.strip())
        if bold_only:
            flush_paragraph()
            flush_list()
            flush_table()
            title = normalize_title_text(bold_only.group(1))
            if title and looks_like_section_title(f"**{title}**"):
                el_id, counter = next_element_id(counter)
                elements.append(
                    Element(
                        id=el_id,
                        type="heading",
                        level=2,
                        text=title,
                        page_number=page,
                    )
                )
                continue

        heading = HEADING_MD_RE.match(line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_table()
            level = len(heading.group(1))
            el_id, counter = next_element_id(counter)
            elements.append(
                Element(
                    id=el_id,
                    type="heading",
                    level=min(level, 3),
                    text=heading.group(2).strip(),
                    page_number=page,
                )
            )
            continue

        if TABLE_ROW_RE.match(line):
            flush_paragraph()
            flush_list()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and all(set(c) <= {"-", ":"} for c in cells):
                continue
            table_buf.append(cells)
            continue

        if table_buf:
            flush_table()

        img = IMAGE_MD_RE.match(line)
        if img:
            flush_paragraph()
            flush_list()
            caption, src = img.group(1), img.group(2)
            ref = src
            content_sha256 = None
            if images_dir is not None and not src.startswith("images/"):
                src_path = Path(src)
                if src_path.is_file():
                    image_counter += 1
                    dest_name = f"img-{image_counter:02d}{src_path.suffix or '.png'}"
                    dest = images_dir / dest_name
                    shutil.copy2(src_path, dest)
                    ref = f"images/{dest_name}"
                    content_sha256 = hashlib.sha256(dest.read_bytes()).hexdigest()
            el_id, counter = next_element_id(counter)
            elements.append(
                Element(
                    id=el_id,
                    type="image",
                    ref=ref,
                    caption=caption or None,
                    content_sha256=content_sha256,
                    page_number=page,
                )
            )
            continue

        item = LIST_ITEM_RE.match(line)
        if item:
            flush_paragraph()
            flush_table()
            list_buf.append(item.group(1).strip())
            continue

        if list_buf:
            flush_list()

        paragraph_buf.append(line)

    flush_paragraph()
    flush_list()
    flush_table()
    return elements, counter, image_counter


def _native_page_chunks(path: Path, pymupdf: Any) -> list[dict[str, Any]]:
    """Fallback page extraction when pymupdf4llm is unavailable or fails."""
    chunks: list[dict[str, Any]] = []
    document = pymupdf.open(str(path))
    try:
        for index, page in enumerate(document):
            chunks.append(
                {
                    "metadata": {"page_number": index + 1},
                    "text": page.get_text("text") or "",
                }
            )
    finally:
        document.close()
    return chunks


def _record_missing_page(
    skipped: list[SkippedPage],
    page: int,
    config: SplitConfig,
) -> None:
    if config.on_missing_text_page == "error":
        raise RuntimeError(f"Page {page} has no extractable text.")
    if not any(existing.page == page for existing in skipped):
        skipped.append(SkippedPage(page=page, reason="ocr_required_out_of_scope"))


def parse_pdf_pymupdf(
    path: Path,
    config: SplitConfig,
    images_dir: Path | None = None,
) -> DocumentIR:
    pymupdf = _load("pymupdf")

    path = path.expanduser().resolve()
    document = pymupdf.open(str(path))
    try:
        if document.needs_pass:
            raise RuntimeError("Password-protected PDFs are not supported.")
        page_count = document.page_count
    finally:
        document.close()

    if images_dir is not None and config.image_extraction:
        images_dir.mkdir(parents=True, exist_ok=True)

    skipped: list[SkippedPage] = []
    all_elements: list[Element] = []
    reconciliation_notes: list[str] = []
    counter = 0
    image_counter = 0

    with tempfile.TemporaryDirectory(prefix=".doc-splitter-") as tmp:
        staging = Path(tmp)
        staged_pdf = staging / path.name
        staged_images = staging / "images"
        shutil.copy2(path, staged_pdf)

        try:
            pymupdf4llm = _load("pymupdf4llm")
            result = pymupdf4llm.to_markdown(
                str(staged_pdf),
                page_chunks=True,
                write_images=config.image_extraction,
                image_path=str(staged_images) if config.image_extraction else None,
                image_format="png",
                use_ocr=config.ocr_enabled,
            )
            if not isinstance(result, list):
                raise RuntimeError("Unexpected pymupdf4llm result format.")
        except Exception as exc:
            result = _native_page_chunks(staged_pdf, pymupdf)
            reconciliation_notes.append(
                "pymupdf4llm failed; native PyMuPDF text fallback used: "
                f"{type(exc).__name__}: {exc}"
            )

        seen_pages: set[int] = set()
        for position, chunk in enumerate(result, start=1):
            if not isinstance(chunk, dict):
                continue
            page = _page_number(chunk) or position
            if page < 1 or page > page_count:
                reconciliation_notes.append(
                    f"Ignored parser chunk with invalid page number {page}."
                )
                continue
            seen_pages.add(page)
            text = chunk.get("text", "")
            if not isinstance(text, str) or not text.strip():
                _record_missing_page(skipped, page, config)
                continue

            lines = text.splitlines()
            page_elements, counter, image_counter = _parse_markdown_lines(
                lines, page, counter, images_dir, image_counter
            )
            all_elements.extend(page_elements)

        for page in range(1, page_count + 1):
            if page not in seen_pages:
                _record_missing_page(skipped, page, config)

        if config.image_extraction and staged_images.exists():
            for image_file in sorted(staged_images.iterdir()):
                if not image_file.is_file():
                    continue
                destination = images_dir / image_file.name if images_dir else image_file
                if images_dir and not destination.exists():
                    shutil.copy2(image_file, destination)

    meta = DocumentMeta(
        source_file=path.name,
        estimated_total_pages=page_count,
        skipped_pages=sorted(skipped, key=lambda item: item.page),
        reconciliation_notes=reconciliation_notes,
    )
    ir = DocumentIR(elements=all_elements, meta=meta)
    ir.recompute_word_counts()
    return ir
