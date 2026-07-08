import pytest

from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.section_titles import (
    infer_chunk_topic,
    list_section_headings,
    looks_like_section_title,
    normalize_title_text,
    pick_best_topic,
    validate_analysis,
    validate_topic,
)


def test_looks_like_section_title_recognizes_medlab_style():
    assert looks_like_section_title("INTRODUCTION – CLINICAL BIOCHEMISTRY")
    assert looks_like_section_title(
        "LABORATORY INVESTIGATIONS AIMED AT ASSESSING THE FUNCTIONAL / STRUCTURAL INTEGRITY OF THE MYOCARDIUM"
    )
    assert not looks_like_section_title("LABORATORY MEDICINE 2019/2020")
    assert not looks_like_section_title("CV = (SD/Mean) x 100")
    assert not looks_like_section_title("Biological variability – Intra-individual:")
    assert not looks_like_section_title(
        "HeFH is the most frequent genetic disease, HoFH is rarer and it is really dangerous."
    )


def test_infer_chunk_topic_from_paragraph_section_titles():
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
        meta=DocumentMeta(source_file="t.docx"),
    )
    assert infer_chunk_topic(ir, 0, 2) == "INTRODUCTION – CLINICAL BIOCHEMISTRY"
    assert list_section_headings(ir, 0, 2) == ["INTRODUCTION – CLINICAL BIOCHEMISTRY"]


def test_validate_topic_rejects_sentence_like_title():
    with pytest.raises(ValueError, match="body sentence"):
        validate_topic("HeFH is the most frequent genetic disease.")


def test_normalize_title_text_strips_pdf_markdown():
    assert (
        normalize_title_text("**INTRODUCTION – CLINICAL BIOCHEMISTRY**")
        == "INTRODUCTION – CLINICAL BIOCHEMISTRY"
    )
    assert normalize_title_text("<u>Biological samples:</u>") == "Biological samples:"


def test_pick_best_topic_skips_overlong_pdf_heading():
    headings = [
        "INTRODUCTION – CLINICAL BIOCHEMISTRY",
        "LABORATORY INVESTIGATIONS AIMED AT ASSESSING THE FUNCTIONAL / STRUCTURAL INTEGRITY OF THE PANCREAS",
        "placed on the needle (both before and after blood withdrawal).",
    ]
    assert pick_best_topic(headings) == "INTRODUCTION – CLINICAL BIOCHEMISTRY"


def test_validate_analysis_accepts_proper_fields():
    validate_analysis(
        topic_fa="مقدمه بیوشیمی بالینی",
        topic_en="Introduction to Clinical Biochemistry",
        study_focus_fa="نمونه‌گیری خون، serum/plasma، vacutainer، sensitivity/specificity و reference interval.",
        study_focus_en="Blood sampling, serum/plasma, vacutainer, sensitivity/specificity, and reference intervals.",
    )