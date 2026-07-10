"""Pipeline orchestrator coordinating all stages."""

from __future__ import annotations

from pathlib import Path

from doc_splitter.boundary.planner import (
    SplitSession,
    load_session,
    save_session,
)
from doc_splitter.config import SplitConfig, config_from_dict, config_to_dict
from doc_splitter.format_detector import InputFormat, detect_format
from doc_splitter.index_generator import get_index_context
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import save_ir
from doc_splitter.parsers import parse_docx, parse_pdf
from doc_splitter.verifier import verify_output
from doc_splitter.writer import write_chunks


class PipelineError(RuntimeError):
    pass


def parse_document(input_path: Path, config: SplitConfig) -> DocumentIR:
    input_path = input_path.expanduser().resolve()
    config.source_path = input_path
    config.output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = config.output_dir / "images" if config.image_extraction else None

    fmt = detect_format(input_path)
    if fmt == InputFormat.PDF:
        ir = parse_pdf(input_path, config, images_dir)
    else:
        ir = parse_docx(input_path, config, images_dir)

    save_ir(ir, config.output_dir / "ir.json")
    return ir


def init_session(input_path: Path, config: SplitConfig) -> SplitSession:
    session = SplitSession(
        source_file=input_path.name,
        output_dir=str(config.output_dir.resolve()),
        config=config_to_dict(config),
        window_pages=min(config.max_pages, config.hard_max_pages),
        stage="boundary",
    )
    save_session(session, config.output_dir)
    return session


def run_write_and_verify(ir: DocumentIR, config: SplitConfig) -> dict:
    session = load_session(config.output_dir)
    session_cfg = session.config
    if config.source_path is None and session_cfg.get("source_path"):
        config.source_path = Path(session_cfg["source_path"])

    input_format = None
    if config.source_path:
        try:
            input_format = detect_format(config.source_path)
        except Exception:
            pass

    write_chunks(
        ir,
        session,
        config,
        config.output_dir,
        input_format=input_format,
    )
    report = verify_output(ir, config.output_dir, config)
    if not report["passed"]:
        raise PipelineError(
            "Verification failed: " + "; ".join(report.get("errors", []))
        )
    session.stage = "content_analysis"
    save_session(session, config.output_dir)
    return report


def run_index_context(config: SplitConfig) -> dict:
    session = load_session(config.output_dir)
    # Validate every index prerequisite before persisting the index stage.
    ctx = get_index_context(config.output_dir, config)
    session.stage = "index"
    save_session(session, config.output_dir)
    return ctx
