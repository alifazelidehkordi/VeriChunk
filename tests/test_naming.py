from pathlib import Path

from doc_splitter.boundary.planner import SplitSession
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.ir.serialize import load_ir
from doc_splitter.naming import resolve_chunk_names, slugify

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


def test_resolve_chunk_names_uses_inferred_section_title_not_body_text():
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="LABORATORY MEDICINE 2019/2020"),
            Element(id="el-002", type="paragraph", text="INTRODUCTION – CLINICAL BIOCHEMISTRY"),
            Element(
                id="el-003",
                type="paragraph",
                text="Laboratory medicine is a clinical discipline studying biological samples.",
            ),
        ],
        meta=DocumentMeta(source_file="medlab.docx"),
    )
    session = SplitSession(source_file="medlab.docx", output_dir="output", config={})
    names = resolve_chunk_names(ir, session, [(0, 2)], SplitConfig(), ext="md")

    assert names[0]["title"] == "INTRODUCTION – CLINICAL BIOCHEMISTRY"
    assert names[0]["file"].startswith("01_introduction")
    assert "laboratory-medicine-is-a-clinical" not in names[0]["file"]