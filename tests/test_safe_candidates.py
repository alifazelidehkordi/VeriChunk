from pathlib import Path

from doc_splitter.boundary.safe_candidates import find_safe_candidates
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import load_ir

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def test_safe_candidates_include_last_element_for_explicit_completion():
    ir = load_ir(FIXTURE)
    candidates = find_safe_candidates(ir, 0, len(ir.elements) - 1)
    ids = [c.element_id for c in candidates]
    assert "el-007" in ids
    assert "el-002" in ids
    assert "el-005" in ids


def test_table_is_atomic_candidate_point():
    ir = DocumentIR.from_dict(load_ir(FIXTURE).to_dict())
    candidates = find_safe_candidates(ir, 0, 4)
    assert any(c.element_id == "el-005" for c in candidates)


def test_image_is_atomic_candidate_point():
    from doc_splitter.ir.models import DocumentMeta, Element

    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="Topic text."),
            Element(id="el-002", type="image", ref="images/figure.png", caption="Figure"),
            Element(id="el-003", type="heading", level=1, text="NEW TOPIC"),
        ],
        meta=DocumentMeta(source_file="sample.docx"),
    )
    candidates = find_safe_candidates(ir, 0, 1)
    assert any(c.element_id == "el-002" for c in candidates)
