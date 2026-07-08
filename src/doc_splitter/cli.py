"""Standalone CLI for the document splitter pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from doc_splitter.boundary.planner import commit_boundary, get_boundary_context, load_session
from doc_splitter.config import SplitConfig, config_from_dict
from doc_splitter.content.analyzer import (
    commit_chunk_analysis,
    get_chunk_analysis_context,
    read_chunk_content,
)
from doc_splitter.ir.serialize import load_ir
from doc_splitter.orchestrator import (
    init_session,
    parse_document,
    run_generate_index,
    run_write_and_verify,
)
from doc_splitter.verifier import verify_output

_SESSION_RESTORE_COMMANDS = frozenset(
    {
        "boundary-context",
        "commit-boundary",
        "write",
        "verify",
        "index",
        "analysis-context",
        "commit-analysis",
        "get-chunk",
    }
)


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-pages", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    parser.add_argument("--reading-speed-wpm", type=int, default=200)
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
    return SplitConfig(
        min_pages=args.min_pages,
        max_pages=args.max_pages,
        output_dir=args.output_dir,
        reading_speed_wpm=getattr(args, "reading_speed_wpm", 200),
        output_format=getattr(args, "output_format", None) or "markdown",
        overlap_boundary_pages=(
            args.overlap_boundary_pages
            if getattr(args, "overlap_boundary_pages", None) is not None
            else 1
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
            restored.min_pages = base.min_pages
            restored.max_pages = base.max_pages
            restored.reading_speed_wpm = base.reading_speed_wpm
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
    init_session(input_path, config)
    ctx = get_boundary_context(ir, load_session(config.output_dir), config)
    print(json.dumps({"stage": "boundary", "context": ctx}, ensure_ascii=False, indent=2))
    print(
        "\nNext: use boundary-context / commit-boundary until status=complete, "
        "then run: doc-splitter write",
        file=sys.stderr,
    )
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
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
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
        coherence=args.coherence,
        reason=args.reason,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    config = _resolve_config(args)
    fa, en = run_generate_index(config)
    print(json.dumps({"study_index_fa": str(fa), "study_index_en": str(en)}, indent=2))
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
    _add_config_args(p_cb)
    p_cb.set_defaults(func=cmd_commit_boundary)

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
    p_ca.add_argument("--coherence", choices=["confident", "needs_review"], required=True)
    p_ca.add_argument("--reason", default="")
    p_ca.add_argument("--out", type=Path, default=Path("output"), dest="output_dir")
    p_ca.set_defaults(func=cmd_commit_analysis)

    p_index = sub.add_parser("index", help="Generate study indexes")
    _add_config_args(p_index)
    p_index.set_defaults(func=cmd_index)

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