from doc_splitter.boundary.planner import SplitSession
from doc_splitter.config import SplitConfig
from doc_splitter.ir.serialize import load_ir
from doc_splitter.naming import resolve_chunk_names, slugify
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def test_slugify_ascii_and_length():
    assert slugify("Hello World!") == "hello-world"
    assert slugify("  Multiple   Spaces  ") == "multiple-spaces"
    long_title = "a" * 80
    assert len(slugify(long_title, max_length=20)) <= 20


def test_slugify_non_latin_falls_back_to_section():
    assert slugify("فصل اول") == ""


def test_resolve_chunk_names_semantic_and_unique():
    ir = load_ir(FIXTURE)
    session = SplitSession(
        source_file="sample.pdf",
        output_dir="output",
        config={},
        chunk_analyses={
            "1": {"topic_en": "Chapter One Overview"},
            "2": {"topic_en": "Chapter Two Overview"},
        },
    )
    ranges = [(0, 4), (5, 6)]
    names = resolve_chunk_names(ir, session, ranges, SplitConfig(), ext="md")

    assert names[0]["file"] == "01_chapter-one-overview.md"
    assert names[1]["file"] == "02_chapter-two-overview.md"
    assert names[0]["slug"] == "chapter-one-overview"