"""Parse PDF layout JSON using OpenDataLoader in an isolated subprocess."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
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


def check_java_available(timeout_seconds: float = 10.0) -> None:
    if shutil.which("java") is None:
        raise OpenDataLoaderError(
            "Java 11+ is required for OpenDataLoader. Install a supported JDK."
        )
    try:
        proc = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenDataLoaderError(
            f"Java runtime check timed out after {timeout_seconds:g} seconds"
        ) from exc
    if proc.returncode != 0:
        raise OpenDataLoaderError("Java runtime not working. Run: java -version")


def parse_pdf_opendataloader(
    path: Path,
    *,
    timeout_seconds: float = 120.0,
) -> list[LayoutElement]:
    check_java_available()
    if importlib.util.find_spec("opendataloader_pdf") is None:
        raise OpenDataLoaderError(
            "opendataloader-pdf not installed. Install with: pip install opendataloader-pdf"
        )

    path = path.expanduser().resolve()
    converter = (
        "import opendataloader_pdf, sys; "
        "opendataloader_pdf.convert(input_path=sys.argv[1], "
        "output_dir=sys.argv[2], format='json')"
    )
    with tempfile.TemporaryDirectory(prefix=".odl-") as tmp:
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        try:
            proc = subprocess.run(
                [sys.executable, "-c", converter, str(path), str(out_dir)],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise OpenDataLoaderError(
                f"OpenDataLoader conversion timed out after {timeout_seconds:g} seconds"
            ) from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "unknown converter error").strip()
            if len(detail) > 600:
                detail = detail[-600:]
            raise OpenDataLoaderError(f"OpenDataLoader conversion failed: {detail}")

        json_files = sorted(out_dir.glob("*.json"))
        if not json_files:
            raise OpenDataLoaderError(f"No JSON output from OpenDataLoader for {path.name}")
        try:
            data = json.loads(json_files[0].read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenDataLoaderError(
                f"Invalid JSON output from OpenDataLoader for {path.name}: {exc}"
            ) from exc
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
        raw_page_num = page.get("page_number", page.get("page", page_idx + 1))
        page_num = int(page_idx + 1 if raw_page_num is None else raw_page_num)
        children = page.get("elements", page.get("blocks", page.get("content", [])))
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            element = _layout_from_node(child, page_num)
            if element is not None:
                elements.append(element)
    return elements


def _bbox_from(obj: dict[str, Any], page: int) -> tuple[float, float, float, float] | None:
    del page
    box = obj.get("bbox") or obj.get("bounding_box") or obj.get("rect")
    if isinstance(box, dict):
        try:
            x0 = box.get("x0", box.get("left", 0))
            y0 = box.get("y0", box.get("top", 0))
            x1 = box.get("x1", box.get("right", 0))
            y1 = box.get("y1", box.get("bottom", 0))
            return (
                float(0 if x0 is None else x0),
                float(0 if y0 is None else y0),
                float(0 if x1 is None else x1),
                float(0 if y1 is None else y1),
            )
        except (TypeError, ValueError):
            return None
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        try:
            return float(box[0]), float(box[1]), float(box[2]), float(box[3])
        except (TypeError, ValueError):
            return None
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
                    rows.append([str(cell) for cell in row])
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
