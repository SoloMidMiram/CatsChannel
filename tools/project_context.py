"""Validate, generate, and select CatsChannel's auditable project context."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Preserve the documented file entry point as well as python -m tools.project_context.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.context_render import (
    check_generated,
    generated_outputs,
    render_decision,
    render_overview,
    write_generated,
)
from tools.context_select import render_json_selection, render_selection, select_records
from tools.context_store import (
    ROOT,
    ContextDataError,
    _local_locator_error,
    _sensitive_memory_locations,
    _validate_freshness,
    load_context,
    validate_repository,
)

__all__ = [
    "ROOT",
    "ContextDataError",
    "_local_locator_error",
    "_sensitive_memory_locations",
    "_validate_freshness",
    "check_generated",
    "generated_outputs",
    "load_context",
    "main",
    "render_decision",
    "render_json_selection",
    "render_overview",
    "render_selection",
    "select_records",
    "validate_repository",
    "write_generated",
]


def _print_errors(errors: list[str]) -> None:
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("validate", help="validate taxonomy, sources, records, and evidence")
    generate = actions.add_parser("generate", help="write or check generated context")
    generate.add_argument("--check", action="store_true")
    select = actions.add_parser("select", help="select compact context for a question")
    select.add_argument("query")
    select.add_argument("--kind", action="append", dest="kinds")
    select.add_argument("--area", action="append", dest="areas")
    select.add_argument("--max-records", type=int, default=8)
    select.add_argument("--max-chars", type=int, default=6000)
    select.add_argument("--include-details", action="store_true")
    select.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = args.root.resolve()
    errors = validate_repository(root)
    if errors:
        _print_errors(errors)
        return 1
    _taxonomy, sources, records = load_context(root)
    if args.action == "validate":
        print(f"Validated {len(records)} records and {len(sources)} evidence sources.")
        return 0
    if args.action == "generate":
        if args.check:
            generated_errors = check_generated(root)
            if generated_errors:
                _print_errors(generated_errors)
                return 1
            print("Generated project context is current.")
        else:
            written = write_generated(root)
            print(f"Generated {len(written)} project-context files.")
        return 0
    if args.max_records < 1 or args.max_chars < 300:
        print(
            "ERROR: max-records must be positive and max-chars must be at least 300",
            file=sys.stderr,
        )
        return 2
    selected = select_records(
        records,
        sources,
        args.query,
        kinds=set(args.kinds) if args.kinds else None,
        areas=set(args.areas) if args.areas else None,
        max_records=args.max_records,
    )
    if args.as_json:
        print(
            render_json_selection(
                selected,
                include_details=args.include_details,
                max_chars=args.max_chars,
            ),
            end="",
        )
    else:
        print(
            render_selection(
                args.query,
                selected,
                sources,
                include_details=args.include_details,
                max_chars=args.max_chars,
            ),
            end="",
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except (OSError, UnicodeError, ContextDataError):
        print("ERROR: context_io_or_data_error", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
