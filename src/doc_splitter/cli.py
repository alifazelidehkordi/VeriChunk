"""Standalone CLI for the document splitter pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from doc_splitter.agents import CommandAgentBackend, HeuristicAgentBackend, run_review_batch
from doc_splitter.boundary.planner import (
    commit_boundary,
    commit_topic_change_reviews,
    get_boundary_context,
    load_session,
    record_chunk_read,
)
from doc_splitter.config import SplitConfig, config_from_dict
from doc_splitter.content.analyzer import (
    commit_chunk_analysis,
    get_chunk_analysis_context,
    read_chunk_content,
)
from doc_splitter.index_generator import commit_study_indexes
from doc_splitter.ir.serialize import load_ir
from doc_splitter.repair import get_boundary_repair_context
from doc_splitter.orchestrator import (
    init_session,
    parse_document,
    run_boundary_repair,
    run_index_context,
    run_write_and_verify,
)
from doc_splitter.verifier import verify_output
from doc_splitter.topic_reviews import build_topic_change_review_batch
from doc_splitter.workflow import TOPIC_REVIEW, require_stage

_SESSION_RESTORE_COMMANDS = frozenset(
    {
        "boundary-context",
        "commit-boundary",
        "topic-review-context",
        "commit-topic-reviews",
        "run-topic-reviews",
        "write",
        "verify",
        "index",
        "commit-index",
        "analysis-context",
        "commit-analysis",
        "repair-context",
        "repair-boundary",
        "get-chunk",
    }
)


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    # None distinguishes an omitted option from an explicit override when a
    # command restores the run configuration from .split-session.json.
    parser.add_argument("--min-pages", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    parser.add_argument("--reading-speed-wpm", type=int, default=None,
                        help="Study reading speed in words per minute (default: 80 for technical/medical content)")
    parser.add_argument(
        "--output-format",
        choices=["markdown", "pdf", "both"],
        default=None,
        help="Chunk output format (default: markdown; persisted in session for run)",
    )
    parser.add_argument(
        "--overlap-pages",
        type=int,
        default=None,
        dest="overlap_boundary_pages",
        help="Extra PDF pages to include at chunk boundaries (default: 1)",
    )


def _config_from_args(args: argparse.Namespace) -> SplitConfig:
    defaults = SplitConfig()
    return SplitConfig(
        min_pages=(
            args.min_pages if getattr(args, "min_pages", None) is not None
            else defaults.min_pages
        ),
        max_pages=(
            args.max_pages if getattr(args, "max_pages", None) is not None
            else defaults.max_pages
        ),
        output_dir=args.output_dir,
        reading_speed_wpm=(
            args.reading_speed_wpm
            if getattr(args, "reading_speed_wpm", None) is not None
            else defaults.reading_speed_wpm
        ),
        output_format=getattr(args, "output_format", None) or defaults.output_format,
        overlap_boundary_pages=(
            args.overlap_boundary_pages
            if getattr(args, "overlap_boundary_pages", None) is not None
            else defaults.overlap_boundary_pages
        ),
    )


def _resolve_config(args: argparse.Namespace) -> SplitConfig:
    base = _config_from_args(args)
    command = getattr(args, "command", None)

    if command in _SESSION_RESTORE_COMMANDS:
        session_file = base.output_dir / ".split-session.json"
        if session_file.exists():
            session = load_session(base.output_dir)
            restored = config_from_dict(session.config)
            restored.output_dir = base.output_dir
            if getattr(args, "min_pages", None) is not None:
                restored.min_pages = args.min_pages
            if getattr(args, "max_pages", None) is not None:
                restored.max_pages = args.max_pages
            if getattr(args, "reading_speed_wpm", None) is not None:
                restored.reading_speed_wpm = args.reading_speed_wpm
            if getattr(args, "output_format", None):
                restored.output_format = args.output_format
            if getattr(args, "overlap_boundary_pages", None) is not None:
                restored.overlap_boundary_pages = args.overlap_boundary_pages
            return restored

    if getattr(args, "output_format", None):
        base.output_format = args.output_format  # type: ignore[assignment]
    if getattr(args, "overlap_boundary_pages", None) is not None:
        base.overlap_boundary_pages = args.overlap_boundary_pages
    return base


def cmd_run(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    input_path = args.input.expanduser().resolve()
    ir = parse_document(input_path, config)
    session = init_session(input_path, config, ir)
    if session.stage == TOPIC_REVIEW:
        ctx = build_topic_change_review_batch(ir, config, workers=4)
        next_step = (
            "Next: run topic-review-context and commit-topic-reviews until every "
            "candidate is resolved; boundary planning will then unlock."
        )
    else:
        ctx = get_boundary_context(ir, session, config)
        next_step = (
            "Next: use boundary-context / commit-boundary until status=complete, "
            "then run: doc-splitter write"
        )
    print(json.dumps({"stage": session.stage, "context": ctx}, ensure_ascii=False, indent=2))
    print(f"\n{next_step}", file=sys.stderr)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    ir = parse_document(args.input.expanduser().resolve(), config)
    print(json.dumps({"elements": len(ir.elements), "words": ir.meta.total_word_count}, indent=2))
    return 0


def cmd_boundary_context(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    ir = load_ir(config.output_dir / "ir.json")
    session = load_session(config.output_dir)
    ctx = get_boundary_context(ir, session, config)
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
    return 0


def cmd_commit_boundary(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    ir = load_ir(config.output_dir / "ir.json")
    session = load_session(config.output_dir)
    result = commit_boundary(
        ir,
        session,
        config,
        action=args.action,
        element_id=args.element_id,
        reason=args.reason,
        allow_oversize=args.allow_oversize,
        allow_topic_merge=args.allow_topic_merge,
        continuity_evidence=args.continuity_evidence,
        continuity_reviewers=args.continuity_reviewer,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_topic_review_context(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    session = load_session(config.output_dir)
    require_stage(session, TOPIC_REVIEW, "request topic-review context")
    ir = load_ir(config.output_dir / "ir.json")
    batch = build_topic_change_review_batch(ir, config, args.workers)
    print(json.dumps(batch, ensure_ascii=False, indent=2))
    return 0


def cmd_commit_topic_reviews(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    if args.reviews and args.reviews_file:
        raise ValueError("Use either --reviews or --reviews-file, not both")
    raw = args.reviews_file.read_text(encoding="utf-8") if args.reviews_file else args.reviews
    if raw is None:
        raise ValueError("--reviews or --reviews-file is required")
    try:
        reviews = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Reviews must be a JSON array: {exc.msg}") from exc
    if not isinstance(reviews, list):
        raise ValueError("Reviews must be a JSON array")
    ir = load_ir(config.output_dir / "ir.json")
    result = commit_topic_change_reviews(
        ir,
        load_session(config.output_dir),
        config,
        reviews,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_run_topic_reviews(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    session = load_session(config.output_dir)
    require_stage(session, TOPIC_REVIEW, "run topic-change reviews")
    ir = load_ir(config.output_dir / "ir.json")
    batch = build_topic_change_review_batch(ir, config, args.workers)
    if batch["total_tasks"] == 0:
        print(json.dumps({"status": "no_topic_candidates"}, indent=2))
        return 0
    if args.backend == "command":
        if not args.agent_command:
            raise ValueError("--agent-command is required for --backend command")
        backend = CommandAgentBackend(
            args.agent_command,
            timeout_seconds=args.timeout_seconds,
            max_output_bytes=args.agent_max_output_bytes,
        )
    else:
        backend = HeuristicAgentBackend()
    reviews = asyncio.run(
        run_review_batch(
            batch, backend, workers=args.workers, retries=args.retries
        )
    )
    result = commit_topic_change_reviews(ir, session, config, reviews)
    print(
        json.dumps(
            {
                "execution": {
                    "backend": args.backend,
                    "workers": args.workers,
                    "reviews_completed": len(reviews),
                },
                "result": result,
                "reviews": reviews,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    ir = load_ir(config.output_dir / "ir.json")
    report = run_write_and_verify(ir, config)
    print(json.dumps({"verification": report}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    ir = load_ir(config.output_dir / "ir.json")
    report = verify_output(ir, config.output_dir, config)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def cmd_get_chunk(args: argparse.Namespace) -> int:
    output_dir = args.output_dir
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    chunk = next((c for c in manifest.get("chunks", []) if c["id"] == args.chunk_id), None)
    if chunk is None:
        raise ValueError(f"Chunk {args.chunk_id} not found in manifest")

    record_chunk_read(output_dir, args.chunk_id)

    content = read_chunk_content(output_dir, chunk)
    payload = {
        "chunk_id": args.chunk_id,
        "file": chunk["file"],
        "format": chunk.get("format", manifest.get("output_format", "markdown")),
        "source_pages": chunk.get("source_pages", []),
        "pdf_pages": chunk.get("pdf_pages", []),
        "content": content,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_analysis_context(args: argparse.Namespace) -> int:
    ctx = get_chunk_analysis_context(args.output_dir, args.chunk_id)
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
    return 0


def cmd_commit_analysis(args: argparse.Namespace) -> int:
    result = commit_chunk_analysis(
        args.output_dir,
        args.chunk_id,
        topic_fa=args.topic_fa,
        topic_en=args.topic_en,
        study_focus_fa=args.study_focus_fa,
        study_focus_en=args.study_focus_en,
        coherence=args.coherence,
        reason=args.reason,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0



def cmd_repair_context(args: argparse.Namespace) -> int:
    ctx = get_boundary_repair_context(args.output_dir, args.chunk_id)
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
    return 0


def cmd_repair_boundary(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    result = run_boundary_repair(
        config,
        chunk_id=args.chunk_id,
        cut_element_ids=args.cut_element_id,
        reason=args.reason,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def cmd_index(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    ctx = run_index_context(config)
    print(json.dumps(ctx, ensure_ascii=False, indent=2))
    return 0


def _read_text_arg(value: str | None, file_value: Path | None, field: str) -> str:
    if value and file_value:
        raise ValueError(f"Use either --{field} or --{field}-file, not both")
    if file_value:
        return file_value.read_text(encoding="utf-8")
    if value:
        return value
    raise ValueError(f"--{field} or --{field}-file is required")


def cmd_commit_index(args: argparse.Namespace) -> int:
    index_fa = _read_text_arg(args.fa, args.fa_file, "fa")
    index_en = _read_text_arg(args.en, args.en_file, "en")
    study_map = _read_text_arg(args.map, args.map_file, "map")
    fa, en, study_map_path = commit_study_indexes(
        args.output_dir,
        index_fa=index_fa,
        index_en=index_en,
        study_map=study_map,
    )
    print(
        json.dumps(
            {
                "study_index_fa": str(fa),
                "study_index_en": str(en),
                "study_map": str(study_map_path),
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc-splitter", description="Conceptual document splitter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Parse document and start boundary session")
    p_run.add_argument("--input", type=Path, required=True)
    _add_config_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_parse = sub.add_parser("parse", help="Parse only, write ir.json")
    p_parse.add_argument("--input", type=Path, required=True)
    _add_config_args(p_parse)
    p_parse.set_defaults(func=cmd_parse)

    p_bc = sub.add_parser("boundary-context", help="Get boundary decision context")
    _add_config_args(p_bc)
    p_bc.set_defaults(func=cmd_boundary_context)

    p_cb = sub.add_parser("commit-boundary", help="Commit a boundary decision")
    p_cb.add_argument("--action", choices=["cut", "extend"], required=True)
    p_cb.add_argument("--element-id", default=None)
    p_cb.add_argument("--reason", default="")
    p_cb.add_argument(
        "--allow-oversize",
        action="store_true",
        help="Allow an explicit extension beyond --max-pages for an inseparable concept.",
    )
    p_cb.add_argument(
        "--allow-topic-merge",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p_cb.add_argument(
        "--continuity-evidence",
        action="append",
        default=None,
        help="Element ID proving the same topic continues; repeat at least twice beyond page 13.",
    )
    p_cb.add_argument(
        "--continuity-reviewer",
        action="append",
        default=None,
        help="Independent reviewer ID confirming continuity; repeat at least twice beyond page 13.",
    )
    _add_config_args(p_cb)
    p_cb.set_defaults(func=cmd_commit_boundary)

    p_trc = sub.add_parser(
        "topic-review-context",
        help="Build independent topic-change tasks for parallel host-agent review",
    )
    p_trc.add_argument("--workers", type=int, default=4)
    _add_config_args(p_trc)
    p_trc.set_defaults(func=cmd_topic_review_context)

    p_ctr = sub.add_parser(
        "commit-topic-reviews",
        help="Commit parallel topic-change review votes as JSON",
    )
    p_ctr.add_argument("--reviews", default=None)
    p_ctr.add_argument("--reviews-file", type=Path, default=None)
    _add_config_args(p_ctr)
    p_ctr.set_defaults(func=cmd_commit_topic_reviews)

    p_rtr = sub.add_parser(
        "run-topic-reviews",
        help="Execute semantic review tasks concurrently and commit their votes",
    )
    p_rtr.add_argument("--workers", type=int, default=4)
    p_rtr.add_argument("--backend", choices=["heuristic", "command"], default="command")
    p_rtr.add_argument("--agent-command", default=None)
    p_rtr.add_argument("--timeout-seconds", type=float, default=120.0)
    p_rtr.add_argument("--retries", type=int, default=1)
    p_rtr.add_argument("--agent-max-output-bytes", type=int, default=2 * 1024 * 1024)
    _add_config_args(p_rtr)
    p_rtr.set_defaults(func=cmd_run_topic_reviews)

    p_write = sub.add_parser("write", help="Write chunks and verify")
    _add_config_args(p_write)
    p_write.set_defaults(func=cmd_write)

    p_verify = sub.add_parser("verify", help="Re-run verification")
    _add_config_args(p_verify)
    p_verify.set_defaults(func=cmd_verify)

    p_gc = sub.add_parser("get-chunk", help="Read chunk content by id from manifest")
    p_gc.add_argument("--chunk-id", type=int, required=True)
    p_gc.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    p_gc.set_defaults(func=cmd_get_chunk)

    p_ac = sub.add_parser("analysis-context", help="Get chunk analysis context")
    p_ac.add_argument("--chunk-id", type=int, required=True)
    p_ac.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    p_ac.set_defaults(func=cmd_analysis_context)

    p_ca = sub.add_parser("commit-analysis", help="Commit chunk content analysis")
    p_ca.add_argument("--chunk-id", type=int, required=True)
    p_ca.add_argument("--topic-fa", required=True)
    p_ca.add_argument("--topic-en", required=True)
    p_ca.add_argument("--study-focus-fa", required=True)
    p_ca.add_argument("--study-focus-en", required=True)
    p_ca.add_argument("--coherence", choices=["confident", "needs_review"], required=True)
    p_ca.add_argument("--reason", default="")
    p_ca.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    p_ca.set_defaults(func=cmd_commit_analysis)


    p_rc = sub.add_parser("repair-context", help="Get a safe split-only repair context")
    p_rc.add_argument("--chunk-id", type=int, required=True)
    p_rc.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    p_rc.set_defaults(func=cmd_repair_context)

    p_rb = sub.add_parser("repair-boundary", help="Split an incoherent chunk and reverify output")
    p_rb.add_argument("--chunk-id", type=int, required=True)
    p_rb.add_argument("--cut-element-id", action="append", required=True)
    p_rb.add_argument("--reason", required=True)
    _add_config_args(p_rb)
    p_rb.set_defaults(func=cmd_repair_boundary)

    p_index = sub.add_parser("index", help="Get context for agent-authored study indexes")
    _add_config_args(p_index)
    p_index.set_defaults(func=cmd_index)

    p_ci = sub.add_parser("commit-index", help="Commit agent-authored study indexes")
    p_ci.add_argument("--fa", default=None, help="Persian index Markdown body")
    p_ci.add_argument("--en", default=None, help="English index Markdown body")
    p_ci.add_argument("--map", default=None, help="Document-level study map Markdown body")
    p_ci.add_argument("--fa-file", type=Path, default=None, help="Path to Persian index Markdown")
    p_ci.add_argument("--en-file", type=Path, default=None, help="Path to English index Markdown")
    p_ci.add_argument("--map-file", type=Path, default=None, help="Path to study map Markdown")
    p_ci.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    p_ci.set_defaults(func=cmd_commit_index)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
