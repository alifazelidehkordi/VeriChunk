from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.structure_analyzer import compute_chunk_page_ranges


def _ir_with_shared_boundary_page() -> DocumentIR:
    elements = [
        Element(id="el-001", type="paragraph", text="p1", page_number=1),
        Element(id="el-002", type="paragraph", text="p2", page_number=2),
        Element(id="el-003", type="paragraph", text="p3", page_number=2),
        Element(id="el-004", type="paragraph", text="p4", page_number=3),
    ]
    for el in elements:
        el.compute_word_count()
    ir = DocumentIR(
        elements=elements,
        meta=DocumentMeta(source_file="t.pdf", estimated_total_pages=3),
    )
    ir.recompute_word_counts()
    return ir


def test_compute_chunk_page_ranges_overlap_on_shared_boundary():
    ir = _ir_with_shared_boundary_page()
    ranges = [(0, 1), (2, 3)]
    config = SplitConfig(overlap_boundary_pages=1)

    page_ranges = compute_chunk_page_ranges(ir, ranges, config)

    assert page_ranges[0].source_pages == [1, 2]
    assert page_ranges[1].source_pages == [2, 3]
    assert page_ranges[0].overlap_next == [2]
    assert page_ranges[1].overlap_prev == [2]
    assert 3 in page_ranges[0].pdf_pages
    assert 1 in page_ranges[1].pdf_pages


def test_compute_chunk_page_ranges_estimates_pages_without_page_number():
    ir = DocumentIR(
        elements=[Element(id="el-001", type="paragraph", text="no explicit page")],
        meta=DocumentMeta(source_file="t.pdf"),
    )
    ir.recompute_word_counts()
    page_ranges = compute_chunk_page_ranges(ir, [(0, 0)], SplitConfig())
    assert page_ranges[0].source_pages == [1]
