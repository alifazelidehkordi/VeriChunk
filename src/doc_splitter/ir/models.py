"""Intermediate representation models for format-independent processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ElementType = Literal["heading", "paragraph", "table", "list", "image"]


@dataclass
class BBox:
    x0: float
    y0: float
    x1: float
    y1: float
    page: int

    def to_dict(self) -> dict[str, float | int]:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1, "page": self.page}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BBox | None:
        try:
            return cls(
                x0=float(data["x0"]),
                y0=float(data["y0"]),
                x1=float(data["x1"]),
                y1=float(data["y1"]),
                page=int(data["page"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class SkippedPage:
    page: int
    reason: str

    def to_dict(self) -> dict[str, str | int]:
        return {"page": self.page, "reason": self.reason}


@dataclass
class Element:
    id: str
    type: ElementType
    text: str = ""
    level: int | None = None
    rows: list[list[str]] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    ref: str | None = None
    caption: str | None = None
    content_sha256: str | None = None
    page_number: int | None = None
    bbox: BBox | None = None
    word_count: int = 0
    cumulative_word_count: int = 0

    @property
    def page(self) -> int | None:
        """Backward-compatible alias for page_number."""
        return self.page_number

    @page.setter
    def page(self, value: int | None) -> None:
        self.page_number = value

    def resolved_page_number(self) -> int | None:
        if self.page_number is not None:
            return self.page_number
        if self.bbox is not None:
            return self.bbox.page
        return None

    def compute_word_count(self) -> int:
        if self.type == "table":
            words = " ".join(" ".join(row) for row in self.rows)
        elif self.type == "list":
            words = " ".join(self.items)
        elif self.type == "image":
            words = self.caption or ""
        else:
            words = self.text
        self.word_count = len(words.split()) if words else 0
        return self.word_count

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.type == "heading":
            data["level"] = self.level
            data["text"] = self.text
        elif self.type == "paragraph":
            data["text"] = self.text
        elif self.type == "table":
            data["rows"] = self.rows
        elif self.type == "list":
            data["items"] = self.items
        elif self.type == "image":
            data["ref"] = self.ref
            if self.caption:
                data["caption"] = self.caption
            if self.content_sha256:
                data["content_sha256"] = self.content_sha256
        data["page_number"] = self.page_number
        data["bbox"] = self.bbox.to_dict() if self.bbox is not None else None
        data["word_count"] = self.word_count
        data["cumulative_word_count"] = self.cumulative_word_count
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Element:
        page_number = data.get("page_number", data.get("page"))
        return cls(
            id=str(data["id"]),
            type=data["type"],
            text=data.get("text", ""),
            level=data.get("level"),
            rows=data.get("rows", []),
            items=data.get("items", []),
            ref=data.get("ref"),
            caption=data.get("caption"),
            content_sha256=data.get("content_sha256"),
            page_number=int(page_number) if page_number is not None else None,
            bbox=BBox.from_dict(data["bbox"]) if data.get("bbox") else None,
            word_count=int(data.get("word_count", 0)),
            cumulative_word_count=int(data.get("cumulative_word_count", 0)),
        )


@dataclass
class DocumentMeta:
    source_file: str
    total_word_count: int = 0
    estimated_total_pages: int = 0
    skipped_pages: list[SkippedPage] = field(default_factory=list)
    reconciliation_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "total_word_count": self.total_word_count,
            "estimated_total_pages": self.estimated_total_pages,
            "skipped_pages": [p.to_dict() for p in self.skipped_pages],
            "reconciliation_notes": self.reconciliation_notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentMeta:
        return cls(
            source_file=data["source_file"],
            total_word_count=int(data.get("total_word_count", 0)),
            estimated_total_pages=int(data.get("estimated_total_pages", 0)),
            skipped_pages=[
                SkippedPage(page=int(p["page"]), reason=str(p["reason"]))
                for p in data.get("skipped_pages", [])
            ],
            reconciliation_notes=list(data.get("reconciliation_notes", [])),
        )


@dataclass
class DocumentIR:
    elements: list[Element] = field(default_factory=list)
    meta: DocumentMeta = field(default_factory=lambda: DocumentMeta(source_file=""))

    def recompute_word_counts(self) -> None:
        total = 0
        for el in self.elements:
            total += el.compute_word_count()
            el.cumulative_word_count = total
        self.meta.total_word_count = total

    def element_by_id(self, element_id: str) -> Element | None:
        for el in self.elements:
            if el.id == element_id:
                return el
        return None

    def index_of(self, element_id: str) -> int:
        for i, el in enumerate(self.elements):
            if el.id == element_id:
                return i
        raise KeyError(f"Unknown element id: {element_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "elements": [el.to_dict() for el in self.elements],
            "meta": self.meta.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentIR:
        return cls(
            elements=[Element.from_dict(e) for e in data.get("elements", [])],
            meta=DocumentMeta.from_dict(data.get("meta", {"source_file": ""})),
        )