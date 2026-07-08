"""Pipeline configuration with design-doc defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

OutputFormat = Literal["markdown", "pdf", "both"]


@dataclass
class SplitConfig:
    min_pages: int = 5
    max_pages: int = 10
    boundary_window_pages: int = 15
    boundary_window_extension_pages: int = 10
    words_per_page: int = 400
    image_extraction: bool = True
    reading_speed_wpm: int = 80
    use_llm_chapter_grouping: bool = False
    ocr_enabled: bool = False
    on_missing_text_page: str = "skip_and_flag"
    word_count_tolerance_pct: float = 0.005
    word_count_tolerance_min: int = 10
    min_chunks_per_chapter: int = 2
    output_format: OutputFormat = "markdown"
    overlap_boundary_pages: int = 1
    slug_max_length: int = 60
    output_dir: Path = field(default_factory=lambda: Path("output"))
    source_path: Path | None = None

    def window_words(self, pages: int | None = None) -> int:
        return (pages or self.boundary_window_pages) * self.words_per_page

    def extension_words(self) -> int:
        return self.boundary_window_extension_pages * self.words_per_page

    def min_chunk_words(self) -> int:
        return self.min_pages * self.words_per_page

    def max_chunk_words(self) -> int:
        return self.max_pages * self.words_per_page

    def word_count_tolerance(self, total: int) -> int:
        return max(
            self.word_count_tolerance_min,
            int(total * self.word_count_tolerance_pct),
        )


def config_to_dict(config: SplitConfig) -> dict:
    data = asdict(config)
    data["output_dir"] = str(config.output_dir)
    if config.source_path:
        data["source_path"] = str(config.source_path)
    return data


def config_from_dict(data: dict) -> SplitConfig:
    payload = dict(data)
    output_dir = Path(payload.pop("output_dir", "output"))
    source_path = payload.pop("source_path", None)
    allowed = {f.name for f in SplitConfig.__dataclass_fields__.values()}
    kwargs = {k: v for k, v in payload.items() if k in allowed}
    return SplitConfig(
        output_dir=output_dir,
        source_path=Path(source_path) if source_path else None,
        **kwargs,
    )