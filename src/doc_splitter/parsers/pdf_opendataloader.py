"""Parse PDF layout JSON using OpenDataLoader (deterministic local mode)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LayoutElement:
    text: str
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    kind: str
    rows: list[list[str]] | None = None


class OpenDataLoaderError(RuntimeError):
    pass


def check_java_available() -> None:
    if shutil.which("java") is None:
        raise OpenDataLoaderError(
            "Java 11+ is required for OpenDataLoader. Install JDK from https://adoptium.net/"
        )
    proc = subprocess.run(
        ["java", "-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise OpenDataLoaderError("Java runtime not working. Run: java -version")


def parse_pdf_opendataloader(path: Path) -> list[LayoutElement]:
    check_java_available()
    try:
        import opendataloader_pdf
    except ImportError as exc:
        raise OpenDataLoaderError(
            "opendataloader-pdf not installed. Install with: pip install opendataloader-pdf"
        ) from exc

    path = path.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix=".odl-") as tmp:
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        opendataloader_pdf.convert(
            input_path=str(path),
            output_dir=str(out_dir),
            format="json",
        )
        json_files = list(out_dir.glob("*.json"))
        if not json_files:
            raise OpenDataLoaderError(f"No JSON output from OpenDataLoader for {path.name}")

        data = json.loads(json_files[0].read_text(encoding="utf-8"))
        return _extract_layout_elements(data)


def _extract_layout_elements(data: Any) -> list[LayoutElement]:
    elements: list[LayoutElement] = []
    pages = data if isinstance(data, list) else data.get("pages", data.get("elements", []))

    if isinstance(pages, dict):
        pages = pages.get("pages", [])

    if not isinstance(pages, list):
        return elements

    for page_idx, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        page_num = int(page.get("page_number", page.get("page", page_idx + 1)))
        children = page.get("elements", page.get("blocks", page.get("content", [])))
        if not isinstance(children, list):
            continue
        for child in children:
            el = _layout_from_node(child, page_num)
            if el is not None:
                elements.append(el)
    return elements


def _bbox_from(obj: dict[str, Any], page: int) -> tuple[float, float, float, float] | None:
    box = obj.get("bbox") or obj.get("bounding_box") or obj.get("rect")
    if isinstance(box, dict):
        try:
            return (
                float(box.get("x0", box.get("left", 0))),
                float(box.get("y0", box.get("top", 0))),
                float(box.get("x1", box.get("right", 0))),
                float(box.get("y1", box.get("bottom", 0))),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        return float(box[0]), float(box[1]), float(box[2]), float(box[3])
    return None


def _layout_from_node(node: dict[str, Any], page: int) -> LayoutElement | None:
    kind = str(node.get("type", node.get("kind", "text"))).lower()
    text = str(node.get("text", node.get("content", ""))).strip()
    bbox = _bbox_from(node, page)
    rows: list[list[str]] | None = None

    if kind in {"table", "tabular"}:
        raw_rows = node.get("rows") or node.get("cells") or []
        if isinstance(raw_rows, list) and raw_rows:
            rows = []
            for row in raw_rows:
                if isinstance(row, list):
                    rows.append([str(c) for c in row])
                elif isinstance(row, dict):
                    rows.append([str(row.get("text", ""))])

    if not text and not rows:
        return None

    if bbox is None:
        x0 = y0 = x1 = y1 = 0.0
    else:
        x0, y0, x1, y1 = bbox

    return LayoutElement(
        text=text,
        page=page,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        kind=kind,
        rows=rows,
    )