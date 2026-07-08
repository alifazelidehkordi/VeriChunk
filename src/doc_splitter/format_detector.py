"""Detect input file format and select the appropriate parser."""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class InputFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


PDF_MAGIC = b"%PDF"
DOCX_MAGIC = b"PK\x03\x04"


class FormatError(ValueError):
    pass


def detect_format(path: Path) -> InputFormat:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FormatError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return InputFormat.PDF
    if suffix == ".docx":
        return InputFormat.DOCX

    header = path.read_bytes()[:4]
    if header.startswith(PDF_MAGIC):
        return InputFormat.PDF
    if header.startswith(DOCX_MAGIC):
        return InputFormat.DOCX

    raise FormatError(
        f"Unsupported file format for {path.name}. Supported: .pdf, .docx"
    )