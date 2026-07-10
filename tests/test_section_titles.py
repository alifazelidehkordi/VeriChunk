import pytest

from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.section_titles import (
    infer_chunk_topic,
    list_section_headings,
    looks_like_section_title,
    normalize_title_text,
    pick_best_topic,
    validate_analysis,
    validate_analysis_reason,
    validate_boundary_reason,
    validate_topic,
)


def test_looks_like_section_title_recognizes_generic_titles():
    assert looks_like_section_title("RECURSIVE TREE TRAVERSAL")
    assert looks_like_section_title("SYSTEM DESIGN TRADEOFFS FOR DISTRIBUTED QUEUES")
    assert looks_like_section_title("مبانی طراحی الگوریتم")
    assert not looks_like_section_title("CV = (SD/Mean) x 100")
    assert not looks_like_section_title("This page intentionally left blank")
    assert not looks_like_section_title(
        "Recursive calls are useful because they simplify repeated work."
    )
    assert not looks_like_section_title(
        "This chapter explains several examples, and it is really important."
    )


def test_infer_chunk_topic_from_paragraph_section_titles():
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="This page intentionally left blank"),
            Element(id="el-002", type="paragraph", text="RECURSIVE TREE TRAVERSAL"),
            Element(
                id="el-003",
                type="paragraph",
                text="Recursive traversal visits nodes by repeatedly applying the same operation.",
            ),
        ],
        meta=DocumentMeta(source_file="t.docx"),
    )
    assert infer_chunk_topic(ir, 0, 2) == "RECURSIVE TREE TRAVERSAL"
    assert list_section_headings(ir, 0, 2) == ["RECURSIVE TREE TRAVERSAL"]


def test_validate_topic_rejects_sentence_like_title():
    with pytest.raises(ValueError, match="body sentence"):
        validate_topic("Recursive calls are useful because they simplify repeated work.")


def test_normalize_title_text_strips_pdf_markdown():
    assert normalize_title_text("**RECURSIVE TREE TRAVERSAL**") == "RECURSIVE TREE TRAVERSAL"
    assert normalize_title_text("<u>Design constraints:</u>") == "Design constraints:"


def test_pick_best_topic_skips_overlong_pdf_heading():
    headings = [
        "RECURSIVE TREE TRAVERSAL",
        "SYSTEM DESIGN TRADEOFFS FOR DISTRIBUTED QUEUES WITH MULTIPLE CONSUMER GROUPS AND FAILURE MODES",
        "this paragraph continues the explanation with a full sentence.",
    ]
    assert pick_best_topic(headings) == "RECURSIVE TREE TRAVERSAL"


def test_validate_analysis_accepts_proper_fields():
    validate_analysis(
        topic_fa="پیمایش بازگشتی درخت",
        topic_en="Recursive Tree Traversal",
        study_focus_fa="حالت پایه، ترتیب بازدید گره‌ها، پشته فراخوانی و خطاهای رایج پیاده‌سازی را مرور کنید.",
        study_focus_en="Review base cases, node visit order, call stack behavior, and common implementation mistakes.",
    )


class TestValidateBoundaryReason:
    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_boundary_reason("")

    def test_rejects_auto_cut_pattern(self):
        with pytest.raises(ValueError, match="not an auto-cut"):
            validate_boundary_reason("auto-cut ~6047 words")

    def test_rejects_auto_prefix(self):
        with pytest.raises(ValueError, match="not auto-generated"):
            validate_boundary_reason("auto generated boundary")

    def test_rejects_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            validate_boundary_reason("ok")

    def test_rejects_punctuation_only(self):
        with pytest.raises(ValueError, match="actual words"):
            validate_boundary_reason(",,,")

    def test_accepts_proper_reason(self):
        validate_boundary_reason(
            "Examples 1-3 belong together; new topic starts after summary paragraph."
        )


class TestValidateAnalysisReason:
    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_analysis_reason("")

    def test_rejects_auto_from_section_headings(self):
        with pytest.raises(ValueError, match="not acceptable"):
            validate_analysis_reason("auto from section_headings")

    def test_rejects_auto_populated_from_headings(self):
        with pytest.raises(ValueError, match="not acceptable|not auto-generated"):
            validate_analysis_reason("auto populated from section headings")

    def test_rejects_auto_generated(self):
        with pytest.raises(ValueError, match="not auto-generated"):
            validate_analysis_reason("auto generated analysis")

    def test_rejects_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            validate_analysis_reason("ok")

    def test_rejects_punctuation_only(self):
        with pytest.raises(ValueError, match="actual words"):
            validate_analysis_reason(";;;")

    def test_accepts_proper_reason(self):
        validate_analysis_reason(
            "Chunk covers glucose metabolism investigations cohesively with clear diagnostic flow."
        )
