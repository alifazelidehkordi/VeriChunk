import json
from pathlib import Path

from doc_splitter.boundary.planner import SplitSession, save_session
from doc_splitter.config import SplitConfig
from doc_splitter.ir.serialize import load_ir
from doc_splitter.verifier import verify_output
from doc_splitter.writer import write_chunks

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ir.json"


def _resolved_review(decision: str) -> dict:
    return {
        "topic-change:el-006": {
            "heading_element_id": "el-006",
            "heading_text": "Chapter Two",
            "boundary_element_id": "el-005",
            "boundary_index": 4,
            "consensus": decision,
            "votes": {
                "reviewer-a": {"decision": decision, "reason": "semantic review"},
                "reviewer-b": {"decision": decision, "reason": "semantic review"},
            },
        }
    }


def _complete_session(tmp_path: Path, *, split: bool) -> SplitSession:
    boundaries = (
        [
            {"end_element_id": "el-005", "end_index": 4, "reason": "test", "start_index": 0},
            {"end_element_id": "el-007", "end_index": 6, "reason": "test", "start_index": 5},
        ]
        if split
        else [
            {"end_element_id": "el-007", "end_index": 6, "reason": "test", "start_index": 0},
        ]
    )
    return SplitSession(
        source_file="sample.pdf",
        output_dir=str(tmp_path),
        config={},
        stage="boundary_complete",
        cursor_index=7,
        boundaries=boundaries,
        topic_change_reviews=_resolved_review("split" if split else "merge"),
    )


def test_verifier_passes_complete_coverage(tmp_path: Path):
    ir = load_ir(FIXTURE)
    config = SplitConfig(output_dir=tmp_path)

    session = _complete_session(tmp_path, split=True)
    save_session(session, tmp_path)
    write_chunks(ir, session, config, tmp_path)

    report = verify_output(ir, tmp_path, config)
    assert report["passed"] is True
    assert (tmp_path / "verification-report.json").exists()


def test_verifier_fails_on_missing_element(tmp_path: Path):
    ir = load_ir(FIXTURE)
    config = SplitConfig(output_dir=tmp_path)

    session = _complete_session(tmp_path, split=False)
    save_session(session, tmp_path)
    write_chunks(ir, session, config, tmp_path)

    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["chunks"][0]["element_ids"] = [
        eid for eid in manifest["chunks"][0]["element_ids"] if eid != "el-005"
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = verify_output(ir, tmp_path, config)
    assert report["passed"] is False
    assert any("el-005" in e for e in report["errors"])


def test_verifier_fails_when_both_output_pdf_file_is_missing(tmp_path: Path):
    ir = load_ir(FIXTURE)
    config = SplitConfig(output_dir=tmp_path)

    session = _complete_session(tmp_path, split=True)
    save_session(session, tmp_path)
    write_chunks(ir, session, config, tmp_path)

    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing_pdf = manifest["chunks"][0]["file"].replace(".md", ".pdf")
    manifest["output_format"] = "both"
    manifest["chunks"][0]["format"] = "both"
    manifest["chunks"][0]["pdf_file"] = missing_pdf
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = verify_output(ir, tmp_path, config)

    assert report["passed"] is False
    assert f"Missing chunk file: {missing_pdf}" in report["errors"]


def test_verifier_fails_when_actual_markdown_text_is_replaced(tmp_path: Path):
    ir = load_ir(FIXTURE)
    config = SplitConfig(output_dir=tmp_path)
    session = _complete_session(tmp_path, split=True)
    save_session(session, tmp_path)
    manifest = write_chunks(ir, session, config, tmp_path)

    chunk_path = tmp_path / manifest["chunks"][0]["markdown_file"]
    content = chunk_path.read_text(encoding="utf-8")
    chunk_path.write_text(
        content.replace(
            "First paragraph with some words.",
            "This text was replaced after generation.",
        ),
        encoding="utf-8",
    )

    report = verify_output(ir, tmp_path, config)
    assert report["passed"] is False
    assert any(
        "rendered content mismatch for element el-002" in error for error in report["errors"]
    )


def test_verifier_fails_when_markdown_integrity_markers_are_removed(tmp_path: Path):
    ir = load_ir(FIXTURE)
    config = SplitConfig(output_dir=tmp_path)
    session = _complete_session(tmp_path, split=True)
    save_session(session, tmp_path)
    manifest = write_chunks(ir, session, config, tmp_path)

    chunk_path = tmp_path / manifest["chunks"][0]["markdown_file"]
    chunk_path.write_text("Completely unrelated replacement content.\n", encoding="utf-8")

    report = verify_output(ir, tmp_path, config)
    assert report["passed"] is False
    assert any("element-region start marker" in error for error in report["errors"])


def test_verifier_compares_actual_pdf_pages_to_source(tmp_path: Path):
    import pymupdf

    from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
    from doc_splitter.ir.serialize import save_json
    from doc_splitter.structure_analyzer import ChunkPageRange
    from doc_splitter.writers.pdf_writer import write_pdf_chunks

    source = tmp_path / "source.pdf"
    source_doc = pymupdf.open()
    for number in (1, 2):
        page = source_doc.new_page()
        page.insert_text((72, 72), f"Source page {number}")
    source_doc.save(str(source))
    source_doc.close()

    ir = DocumentIR(
        elements=[
            Element(id="el-001", type="paragraph", text="Source page 1", page_number=1),
            Element(id="el-002", type="paragraph", text="Source page 2", page_number=2),
        ],
        meta=DocumentMeta(source_file="source.pdf", estimated_total_pages=2),
    )
    ir.recompute_word_counts()
    names = [{"id": "1", "slug": "whole", "file": "01_whole.pdf", "title": ""}]
    write_pdf_chunks(
        source,
        [ChunkPageRange(1, 2, [], [], [1, 2], [1, 2])],
        names,
        tmp_path,
    )
    save_json(
        {
            "source_file": "source.pdf",
            "source_path": str(source),
            "output_format": "pdf",
            "chunks": [
                {
                    "id": 1,
                    "file": "01_whole.pdf",
                    "pdf_file": "01_whole.pdf",
                    "start_index": 0,
                    "end_index": 1,
                    "element_ids": ["el-001", "el-002"],
                    "word_count": ir.meta.total_word_count,
                    "pdf_pages": [1, 2],
                }
            ],
        },
        tmp_path / "manifest.json",
    )
    config = SplitConfig(output_dir=tmp_path, output_format="pdf", source_path=source)
    assert verify_output(ir, tmp_path, config)["passed"] is True

    # Replace the second page with a duplicate of page one while leaving the
    # manifest untouched. Metadata-only verification would miss this.
    source_doc = pymupdf.open(str(source))
    tampered = pymupdf.open()
    tampered.insert_pdf(source_doc, from_page=0, to_page=0)
    tampered.insert_pdf(source_doc, from_page=0, to_page=0)
    source_doc.close()
    output_pdf = tmp_path / "01_whole.pdf"
    output_pdf.unlink()
    tampered.save(str(output_pdf))
    tampered.close()

    report = verify_output(ir, tmp_path, config)
    assert report["passed"] is False
    assert any("does not match source page 2" in error for error in report["errors"])


def test_verifier_detects_tampered_image_bytes(tmp_path: Path):
    import hashlib

    from doc_splitter.ir.models import DocumentIR, DocumentMeta, Element
    from doc_splitter.ir.serialize import save_json
    from doc_splitter.markdown_codec import (
        ELEMENTS_END,
        ELEMENTS_START,
        render_marked_element,
    )

    image_bytes = b"original-image-payload"
    image_path = tmp_path / "images" / "asset.bin"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(image_bytes)
    element = Element(
        id="el-001",
        type="image",
        ref="images/asset.bin",
        caption="Diagram",
        content_sha256=hashlib.sha256(image_bytes).hexdigest(),
        page_number=1,
    )
    ir = DocumentIR(
        elements=[element],
        meta=DocumentMeta(source_file="source.docx", estimated_total_pages=1),
    )
    ir.recompute_word_counts()
    chunk_name = "01_diagram.md"
    (tmp_path / chunk_name).write_text(
        f"{ELEMENTS_START}\n\n{render_marked_element(element)}\n\n{ELEMENTS_END}\n",
        encoding="utf-8",
    )
    save_json(
        {
            "source_file": "source.docx",
            "output_format": "markdown",
            "chunks": [
                {
                    "id": 1,
                    "file": chunk_name,
                    "markdown_file": chunk_name,
                    "start_index": 0,
                    "end_index": 0,
                    "element_ids": ["el-001"],
                    "word_count": ir.meta.total_word_count,
                }
            ],
        },
        tmp_path / "manifest.json",
    )
    config = SplitConfig(output_dir=tmp_path)
    assert verify_output(ir, tmp_path, config)["passed"] is True

    image_path.write_bytes(b"tampered-image-payload")
    report = verify_output(ir, tmp_path, config)
    assert report["passed"] is False
    assert any("image content hash mismatch" in error for error in report["errors"])
