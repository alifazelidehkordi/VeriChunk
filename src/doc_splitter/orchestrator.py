"""Pipeline orchestrator coordinating all stages."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from doc_splitter.boundary.planner import (
    SplitSession,
    commit_boundary,
    get_boundary_context,
    load_session,
    save_session,
)
from doc_splitter.config import SplitConfig
from doc_splitter.content.analyzer import commit_chunk_analysis, get_chunk_analysis_context
from doc_splitter.format_detector import InputFormat, detect_format
from doc_splitter.index_generator import generate_study_indexes
from doc_splitter.ir.models import DocumentIR
from doc_splitter.ir.serialize import save_ir
from doc_splitter.parsers import parse_docx, parse_pdf
from doc_splitter.verifier import verify_output
from doc_splitter.writer import write_chunks


class PipelineError(RuntimeError):
    pass


def _config_to_dict(config: SplitConfig) -> dict:
    data = asdict(config)
    data["output_dir"] = str(config.output_dir)
    return data


def _config_from_dict(data: dict) -> SplitConfig:
    output_dir = Path(data.pop("output_dir", "output"))
    return SplitConfig(output_dir=output_dir, **data)


def parse_document(input_path: Path, config: SplitConfig) -> DocumentIR:
    input_path = input_path.expanduser().resolve()
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
        config=_config_to_dict(config),
        stage="boundary",
    )
    save_session(session, config.output_dir)
    return session


def run_write_and_verify(ir: DocumentIR, config: SplitConfig) -> dict:
    session = load_session(config.output_dir)
    write_chunks(ir, session, config, config.output_dir)
    report = verify_output(ir, config.output_dir, config)
    if not report["passed"]:
        raise PipelineError(
            "Verification failed: " + "; ".join(report.get("errors", []))
        )
    session.stage = "content_analysis"
    save_session(session, config.output_dir)
    return report


def run_generate_index(config: SplitConfig) -> tuple[Path, Path]:
    session = load_session(config.output_dir)
    missing = []
    manifest_chunks = (config.output_dir / "manifest.json").read_text(encoding="utf-8")
    import json

    total = json.loads(manifest_chunks).get("total_chunks", 0)
    for i in range(1, total + 1):
        if str(i) not in session.chunk_analyses:
            missing.append(i)
    if missing:
        raise PipelineError(
            f"Missing content analyses for chunks: {missing}. "
            "Use get_chunk_analysis_context / commit_chunk_analysis first."
        )
    paths = generate_study_indexes(config.output_dir, config)
    session.stage = "complete"
    save_session(session, config.output_dir)
    return paths