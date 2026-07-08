from doc_splitter.boundary.safe_candidates import find_safe_candidates
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import load_ir
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def test_safe_candidates_exclude_last_element():
    ir = load_ir(FIXTURE)
    candidates = find_safe_candidates(ir, 0, len(ir.elements) - 1)
    ids = [c.element_id for c in candidates]
    assert "el-007" not in ids
    assert "el-002" in ids
    assert "el-005" in ids


def test_table_is_atomic_candidate_point():
    ir = DocumentIR.from_dict(load_ir(FIXTURE).to_dict())
    candidates = find_safe_candidates(ir, 0, 4)
    assert any(c.element_id == "el-005" for c in candidates)