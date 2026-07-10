from pathlib import Path

from doc_splitter.ir.models import BBox, DocumentIR, DocumentMeta, Element
from doc_splitter.ir.serialize import load_ir, save_ir

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


def test_element_page_number_and_bbox_roundtrip(tmp_path: Path):
    el = Element(
        id="el-001",
        type="paragraph",
        text="hello",
        page_number=5,
        bbox=BBox(x0=1.0, y0=2.0, x1=3.0, y1=4.0, page=5),
    )
    el.compute_word_count()
    ir = DocumentIR(elements=[el], meta=DocumentMeta(source_file="t.pdf"))
    out = tmp_path / "ir.json"
    save_ir(ir, out)
    loaded = load_ir(out)
    assert loaded.elements[0].page_number == 5
    assert loaded.elements[0].bbox is not None
    assert loaded.elements[0].bbox.page == 5
    assert loaded.elements[0].resolved_page_number() == 5


def test_resolved_page_number_from_bbox_only():
    el = Element(
        id="el-001",
        type="paragraph",
        text="hello",
        bbox=BBox(x0=0, y0=0, x1=10, y1=10, page=7),
    )
    assert el.resolved_page_number() == 7


def test_image_content_hash_roundtrip(tmp_path: Path):
    element = Element(
        id="el-001",
        type="image",
        ref="images/diagram.png",
        content_sha256="a" * 64,
    )
    ir = DocumentIR(elements=[element], meta=DocumentMeta(source_file="t.docx"))
    output = tmp_path / "ir.json"
    save_ir(ir, output)
    loaded = load_ir(output)
    assert loaded.elements[0].content_sha256 == "a" * 64
