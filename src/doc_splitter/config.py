"""Pipeline configuration with design-doc defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SplitConfig:
    min_pages: int = 5
    max_pages: int = 10
    boundary_window_pages: int = 15
    boundary_window_extension_pages: int = 10
    words_per_page: int = 400
    image_extraction: bool = True
    reading_speed_wpm: int = 200
    use_llm_chapter_grouping: bool = False
    ocr_enabled: bool = False
    on_missing_text_page: str = "skip_and_flag"
    word_count_tolerance_pct: float = 0.005
    word_count_tolerance_min: int = 10
    min_chunks_per_chapter: int = 2
    output_dir: Path = field(default_factory=lambda: Path("output"))

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