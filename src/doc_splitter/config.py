"""Pipeline configuration with semantic-first splitting defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

OutputFormat = Literal["markdown", "pdf", "both"]
ABSOLUTE_PAGE_CAP = 20


@dataclass
class SplitConfig:
    # Page targets are deliberately soft except for hard_max_pages. A confirmed
    # topic change always overrides min_pages.
    min_pages: int = 5
    max_pages: int = 12
    soft_max_pages: int = 13
    hard_max_pages: int = 20

    topic_change_min_votes: int = 2
    topic_change_reviewers: int = 3
    topic_change_merge_min_votes: int = 2
    topic_change_score_threshold: float = 0.72
    semantic_context_elements: int = 4
    semantic_context_chars: int = 2400
    semantic_nms_radius: int = 2

    boundary_window_pages: int = 12
    boundary_window_extension_pages: int = 1
    continuity_min_reviewers: int = 2

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

    def __post_init__(self) -> None:
        if self.min_pages < 1:
            raise ValueError("min_pages must be at least 1")
        if self.hard_max_pages > ABSOLUTE_PAGE_CAP:
            raise ValueError(
                f"hard_max_pages cannot exceed the absolute cap of {ABSOLUTE_PAGE_CAP}"
            )
        if not (self.min_pages <= self.max_pages <= self.soft_max_pages <= self.hard_max_pages):
            raise ValueError(
                "Page policy must satisfy min_pages <= max_pages <= "
                "soft_max_pages <= hard_max_pages"
            )
        if self.boundary_window_extension_pages < 1:
            raise ValueError("boundary_window_extension_pages must be at least 1")
        if self.topic_change_min_votes < 1:
            raise ValueError("topic_change_min_votes must be at least 1")
        if self.topic_change_reviewers < self.topic_change_min_votes:
            raise ValueError("topic_change_reviewers cannot be smaller than topic_change_min_votes")
        if self.continuity_min_reviewers < 1:
            raise ValueError("continuity_min_reviewers must be at least 1")

    @property
    def preferred_max_pages(self) -> int:
        """Explicit name for the legacy ``max_pages`` setting."""
        return self.max_pages

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
