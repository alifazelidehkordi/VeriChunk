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
