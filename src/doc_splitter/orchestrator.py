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
from doc_splitter.writer import validate_boundary_plan, write_chunks
from doc_splitter.topic_reviews import find_topic_change_candidates
from doc_splitter.workflow import (
    BOUNDARY,
    BOUNDARY_COMPLETE,
    CONTENT_ANALYSIS,
    FAILED,
    INDEX,
    TOPIC_REVIEW,
    VERIFICATION,
    WRITING,
    mark_failed,
    require_stage,
    transition_stage,
)


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


def init_session(
    input_path: Path,
    config: SplitConfig,
    ir: DocumentIR,
) -> SplitSession:
    initial_stage = (
        TOPIC_REVIEW
        if find_topic_change_candidates(ir, config)
        else BOUNDARY
    )
    session = SplitSession(
        source_file=input_path.name,
        output_dir=str(config.output_dir.resolve()),
        config=config_to_dict(config),
        window_pages=min(config.max_pages, config.hard_max_pages),
        stage=initial_stage,
    )
    save_session(session, config.output_dir)
    return session


def run_write_and_verify(ir: DocumentIR, config: SplitConfig) -> dict:
    session = load_session(config.output_dir)
    session_cfg = session.config
    if config.source_path is None and session_cfg.get("source_path"):
        config.source_path = Path(session_cfg["source_path"])

    if session.stage == FAILED:
        if session.failed_from not in {WRITING, VERIFICATION}:
            raise PipelineError(
                "The failed session cannot be retried by write; "
                f"failed_from={session.failed_from}."
            )
        transition_stage(session, WRITING)
    else:
        require_stage(session, BOUNDARY_COMPLETE, "write and verify chunks")
        validate_boundary_plan(ir, session, config)
        transition_stage(session, WRITING)
    save_session(session, config.output_dir)

    input_format = None
    if config.source_path:
        try:
            input_format = detect_format(config.source_path)
        except Exception:
            pass

    try:
        write_chunks(
            ir,
            session,
            config,
            config.output_dir,
            input_format=input_format,
        )
        transition_stage(session, VERIFICATION)
        save_session(session, config.output_dir)

        report = verify_output(ir, config.output_dir, config)
        if not report["passed"]:
            raise PipelineError(
                "Verification failed: " + "; ".join(report.get("errors", []))
            )
        transition_stage(session, CONTENT_ANALYSIS)
        save_session(session, config.output_dir)
        return report
    except Exception as exc:
        failed_from = session.stage if session.stage in {WRITING, VERIFICATION} else WRITING
        mark_failed(session, failed_from=failed_from, message=str(exc))
        save_session(session, config.output_dir)
        raise


def run_index_context(config: SplitConfig) -> dict:
    session = load_session(config.output_dir)
    require_stage(session, INDEX, "build index context")
    return get_index_context(config.output_dir, config)
