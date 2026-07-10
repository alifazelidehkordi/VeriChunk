from pathlib import Path

from doc_splitter.boundary.planner import SplitSession, save_session
from doc_splitter.cli import _resolve_config, build_parser


def test_session_settings_are_preserved_when_cli_options_are_omitted(tmp_path: Path):
    session = SplitSession(
        source_file="book.pdf",
        output_dir=str(tmp_path),
        config={
            "min_pages": 2,
            "max_pages": 7,
            "hard_max_pages": 13,
            "reading_speed_wpm": 123,
            "output_format": "markdown",
            "overlap_boundary_pages": 1,
            "output_dir": str(tmp_path),
        },
    )
    save_session(session, tmp_path)
    args = build_parser().parse_args(["boundary-context", "--out", str(tmp_path)])

    config = _resolve_config(args)

    assert config.min_pages == 2
    assert config.max_pages == 7
    assert config.reading_speed_wpm == 123


def test_explicit_cli_settings_override_the_saved_session(tmp_path: Path):
    session = SplitSession(
        source_file="book.pdf",
        output_dir=str(tmp_path),
        config={
            "min_pages": 2,
            "max_pages": 7,
            "reading_speed_wpm": 123,
            "output_dir": str(tmp_path),
        },
    )
    save_session(session, tmp_path)
    args = build_parser().parse_args(
        [
            "boundary-context",
            "--out",
            str(tmp_path),
            "--max-pages",
            "9",
            "--reading-speed-wpm",
            "150",
        ]
    )

    config = _resolve_config(args)

    assert config.min_pages == 2
    assert config.max_pages == 9
    assert config.reading_speed_wpm == 150
