from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
from doc_splitter.ir.serialize import load_ir, save_ir
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def test_ir_roundtrip(tmp_path: Path):
    ir = load_ir(FIXTURE)
    out = tmp_path / "ir.json"
    save_ir(ir, out)
    loaded = load_ir(out)
    assert len(loaded.elements) == len(ir.elements)
    assert loaded.meta.total_word_count == ir.meta.total_word_count


def test_recompute_word_counts():
    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="one two three"),
            Element(id="el-002", type="heading", text="Title", level=1),
        ],
        meta=DocumentMeta(source_file="t.docx"),
    )
    ir.recompute_word_counts()
    assert ir.meta.total_word_count == 4
    assert ir.elements[1].cumulative_word_count == 4