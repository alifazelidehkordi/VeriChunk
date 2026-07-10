"""JSON serialization for DocumentIR and session state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doc_splitter.ir.models import DocumentIR
from doc_splitter.storage import atomic_write_json


def save_ir(ir: DocumentIR, path: Path) -> None:
    atomic_write_json(path, ir.to_dict())


def load_ir(path: Path) -> DocumentIR:
    data = json.loads(path.read_text(encoding="utf-8"))
    return DocumentIR.from_dict(data)


def save_json(data: dict[str, Any], path: Path) -> None:
    atomic_write_json(path, data)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))