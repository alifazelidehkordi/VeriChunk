"""Pipeline orchestrator coordinating all stages."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from doc_splitter.boundary.planner import (
    SplitSession,
    load_session,
    save_session,
)
from doc_splitter.config import SplitConfig, config_to_dict
from doc_splitter.format_detector import InputFormat, detect_format
from doc_splitter.index_generator import get_index_context
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import save_ir, save_json
from doc_splitter.parsers import parse_docx, parse_pdf
from doc_splitter.repair import commit_boundary_repair_plan
from doc_splitter.semantic import build_semantic_map
from doc_splitter.verifier import verify_output
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
from doc_splitter.writer import validate_boundary_plan, write_chunks


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
    semantic_map = build_semantic_map(ir, config)
    save_json(semantic_map, config.output_dir / "semantic-map.json")
    initial_stage = TOPIC_REVIEW if semantic_map["change_candidates"] else BOUNDARY
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

    repair_mode = session.stage == WRITING and bool(session.active_repair)
    if session.stage == FAILED:
        if session.failed_from not in {WRITING, VERIFICATION}:
            raise PipelineError(
                f"The failed session cannot be retried by write; failed_from={session.failed_from}."
            )
        transition_stage(session, WRITING)
        repair_mode = bool(session.active_repair)
    elif repair_mode:
        validate_boundary_plan(ir, session, config)
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
        manifest = write_chunks(
            ir,
            session,
            config,
            config.output_dir,
            input_format=input_format,
            reuse_existing=repair_mode,
        )
        transition_stage(session, VERIFICATION)
        save_session(session, config.output_dir)

        report = verify_output(ir, config.output_dir, config)
        if not report["passed"]:
            raise PipelineError("Verification failed: " + "; ".join(report.get("errors", [])))
        if repair_mode and session.active_repair:
            completed = dict(session.active_repair)
            completed["completed_at"] = datetime.now(timezone.utc).isoformat()
            completed["verification_passed"] = True
            completed["write_summary"] = manifest.get("write_summary", {})
            session.repair_history.append(completed)
            session.active_repair = None
            session.repair_queue = []
            stale_report = config.output_dir / "semantic-review-report.json"
            stale_report.unlink(missing_ok=True)
        transition_stage(session, CONTENT_ANALYSIS)
        save_session(session, config.output_dir)
        return report
    except Exception as exc:
        failed_from = session.stage if session.stage in {WRITING, VERIFICATION} else WRITING
        mark_failed(session, failed_from=failed_from, message=str(exc))
        save_session(session, config.output_dir)
        raise


def run_boundary_repair(
    config: SplitConfig,
    *,
    chunk_id: int,
    cut_element_ids: list[str],
    reason: str,
) -> dict:
    """Commit a split-only repair plan, rewrite changed chunks, and verify it."""
    ir, _session, restored_config, repair = commit_boundary_repair_plan(
        config.output_dir,
        chunk_id,
        cut_element_ids=cut_element_ids,
        reason=reason,
    )
    restored_config.source_path = config.source_path or restored_config.source_path
    report = run_write_and_verify(ir, restored_config)
    return {
        "status": "repair_applied",
        "repair": repair,
        "verification": report,
        "next_stage": load_session(restored_config.output_dir).stage,
    }


def run_index_context(config: SplitConfig) -> dict:
    session = load_session(config.output_dir)
    require_stage(session, INDEX, "build index context")
    return get_index_context(config.output_dir, config)
