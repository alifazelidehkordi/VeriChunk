"""JSON serialization for DocumentIR and session state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doc_splitter.ir.models import DocumentIR


def save_ir(ir: DocumentIR, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ir.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_ir(path: Path) -> DocumentIR:
    data = json.loads(path.read_text(encoding="utf-8"))
    return DocumentIR.from_dict(data)


def save_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))