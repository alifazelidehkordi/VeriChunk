from doc_splitter.boundary.planner import SplitSession, commit_boundary, get_boundary_context
from doc_splitter.config import SplitConfig
from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element


def _paragraphs(n: int) -> list[Element]:
    return [
        Element(id=f"el-{i:03d}", type="paragraph", text=f"word{i} " * 50)
        for i in range(1, n + 1)
    ]


def test_get_boundary_context_offers_tail_candidates_when_remainder_is_short():
    ir = DocumentIR(elements=_paragraphs(12), meta=DocumentMeta(source_file="t.pdf"))
    ir.recompute_word_counts()
    session = SplitSession(
        source_file="t.pdf",
        output_dir="output",
        config={},
        cursor_index=10,
        window_pages=15,
    )
    config = SplitConfig(min_pages=5, max_pages=10, words_per_page=400)

    ctx = get_boundary_context(ir, session, config)

    assert ctx["status"] == "needs_agent_decision"
    assert ctx["safe_candidates"]
    assert ctx["safe_candidates"][-1]["element_id"] == "el-011"