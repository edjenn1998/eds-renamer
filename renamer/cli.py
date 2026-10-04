"""Command line interface: a thin adapter over the library.

The future GUI should not use this module; it imports the library directly.
The pieces used here: :func:`renamer.engine.expand_paths`,
:func:`renamer.engine.order_paths`, :func:`renamer.engine.plan`,
:func:`renamer.engine.validate`, :func:`renamer.engine.execute`, and the
session helpers (:func:`renamer.session.create_transaction`,
:func:`renamer.session.load_transaction`, and ``Transaction.undo``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from . import operations as ops
from .engine import (
    execute,
    expand_paths,
    has_errors,
    order_paths,
    plan,
    validate,
)
from .session import (
    DEFAULT_ROOT,
    create_transaction,
    list_session_ids,
    load_transaction,
    newest_session,
)


def add_operation_args(parser: argparse.ArgumentParser) -> None:
    ops_group = parser.add_argument_group("operations (applied in this order)")
    ops_group.add_argument(
        "--replace",
        nargs=2,
        action="append",
        metavar=("OLD", "NEW"),
        help="replace every occurrence of OLD with NEW in the stem",
    )
    ops_group.add_argument(
        "--regex",
        nargs=2,
        action="append",
        metavar=("PATTERN", "REPL"),
        help="regex replace in the stem; \\1 groups work; see --ignore-case",
    )
    ops_group.add_argument(
        "--ignore-case",
        action="store_true",
        help="make --regex patterns case-insensitive",
    )
    ops_group.add_argument(
        "--cut",
        action="append",
        nargs=2,
        metavar=("MODE", "N"),
        help="MODE=front: delete first N chars; MODE=end: keep first N chars",
    )
    ops_group.add_argument(
        "--case",
        action="append",
        choices=("lower", "upper", "title", "sentence"),
        help="change stem case",
    )
    ops_group.add_argument(
        "--number",
        action="store_true",
        help="insert numbering (into a ### token in the name, else per --number-mode)",
    )
    ops_group.add_argument(
        "--number-mode", choices=("token", "prefix", "suffix"), default="token"
    )
    ops_group.add_argument("--start", type=int, default=1, help="counter start (default 1)")
    ops_group.add_argument("--step", type=int, default=1, help="counter increment (default 1)")
    ops_group.add_argument("--pad", type=int, default=1, help="digits when no ### token exists")
    ops_group.add_argument(
        "--set-ext", metavar="EXT", help="replace the extension (dot optional), e.g. .txt"
    )
    ops_group.add_argument("--add-ext", metavar="EXT", help="set extension only if none")
    ops_group.add_argument("--strip-ext", action="store_true", help="remove the extension")
    ops_group.add_argument(
        "--ext-case", choices=("lower", "upper"), help="change extension case"
    )
    ops_group.add_argument(
        "--name", metavar="NAME", help="ignore the old name and use NAME exactly"
    )


def make_ops(args: argparse.Namespace) -> List[ops.Op]:
    """Build the fixed-order operation pipeline from parsed args."""
    result: List[ops.Op] = []
    if args.name is not None:
        result.append(ops.stem_set_op(args.name))
    for old, new in args.replace or []:
        result.append(ops.replace_op(old, new))
    for pattern, repl in args.regex or []:
        result.append(ops.regex_op(pattern, repl, args.ignore_case))
    for mode, n in args.cut or []:
        result.append(ops.cut_op(mode, int(n)))
    for kind in args.case or []:
        result.append(ops.case_op(kind))
    if args.number:
        result.append(
            ops.numbering_op(args.number_mode, args.start, args.step, args.pad)
        )
    if args.strip_ext:
        result.append(ops.ext_strip_op())
    if args.set_ext is not None:
        result.append(ops.ext_set_op(args.set_ext))
    if args.add_ext is not None:
        result.append(ops.ext_add_op(args.add_ext))
    if args.ext_case:
        result.append(ops.ext_case_op(args.ext_case))
    return result


def cmd_rename(args: argparse.Namespace) -> int:
    paths = expand_paths(args.paths, args.recursive)
    if not paths:
        print("no files matched", file=sys.stderr)
        return 1
    ordered = order_paths(paths, args.order)
    renames, issues = plan(ordered, make_ops(args))
    issues = issues + validate(renames, force=args.force)
    if has_errors(issues):
        print("cannot apply:", file=sys.stderr)
        from .engine import summary

        print(summary(issues), file=sys.stderr)
        return 2
    if not renames:
        print("nothing to rename")
        return 0
    for r in renames:
        print(f"{r.src} -> {r.dst.name}")
    for issue in issues:
        print(f"[{issue.severity}] {issue.message}")
    if not args.apply:
        print(f"\n[dry run] {len(renames)} file(s); re-run with --apply")
        return 0
    tx = create_transaction(Path(args.home))
    execute(tx, renames, force=args.force)
    print(
        f"renamed {len(renames)} file(s); session {tx.id}"
        f" (undo with: undo --session {tx.id})"
    )
    print(f"journal: {tx.path()}")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    root = Path(args.home)
    sid = args.session or newest_session(root)
    tx = load_transaction(root, sid)
    if not args.yes:
        print(f"undo session {sid} ({len(tx.moves)} moves, reversed):")
        answer = input("proceed? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted")
            return 1
    new = tx.undo()
    print(
        f"undone session {sid}; new session {new.id}"
        " (undoing that redoes the original rename)"
    )
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    ids = list_session_ids(Path(args.home))
    if not ids:
        print("no saved sessions")
        return 0
    for sid in ids:
        print(f"{sid}  {load_transaction(Path(args.home), sid).status}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rename",
        description="bulk file renamer (dry-run by default)",
    )
    parser.add_argument(
        "--home",
        default=str(DEFAULT_ROOT),
        help="state dir for session journals (default ~/.renamer)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rename_p = sub.add_parser(
        "rename",
        help="rename files",
        description=(
            "plan and (with --apply) transactionally rename files. The whole"
            " batch is validated BEFORE anything moves: duplicate destinations,"
            " missing sources, and missing destination parents always abort."
            " Without --force, an existing destination aborts; with --force the"
            " occupant is moved to a journal-tracked backup so nothing is lost"
            " and undo restores both files. Duplicate destinations are never"
            " bypassed, not even by --force."
        ),
    )
    add_operation_args(rename_p)
    rename_p.add_argument("--recursive", action="store_true", help="recurse into dirs")
    rename_p.add_argument(
        "--order", choices=("name", "mtime", "size", "random"), default="name"
    )
    rename_p.add_argument(
        "--apply",
        action="store_true",
        help="actually rename (default: dry run, no filesystem changes)",
    )
    rename_p.add_argument(
        "--force",
        action="store_true",
        help="safe-overwrite existing destinations: occupant is moved to a"
        " backup path (undoable); duplicate destinations are still refused",
    )
    rename_p.add_argument("paths", nargs="+", metavar="FILE_OR_DIR")
    rename_p.set_defaults(func=cmd_rename)

    undo_p = sub.add_parser(
        "undo",
        help="undo a previous batch (undoing an undo redoes it)",
    )
    undo_p.add_argument("--session", help="session id (default: newest)")
    undo_p.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    undo_p.set_defaults(func=cmd_undo)

    sessions_p = sub.add_parser("sessions", help="list saved sessions")
    sessions_p.set_defaults(func=cmd_sessions)
    recovery = sub.add_parser("recover", help="roll back an interrupted session")
    recovery.add_argument("--session", required=True)
    recovery.set_defaults(func=lambda args: (load_transaction(Path(args.home), args.session).recover() and 0))
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
