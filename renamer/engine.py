"""Planning, full-batch validation, no-overwrite moves, and journaled recovery.

Linux renameat2 prevents overwriting at the syscall boundary. The complete
move plan is saved first; each move has a durable pending record so recovery
can distinguish interruptions before and after the syscall. Recovery refuses
ambiguous states and changed files rather than guessing.
"""
from __future__ import annotations

import os
import random
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

from .operations import Op, split_name
from .native import rename_no_replace, sync_directories


class Cancelled(Exception):
    """An operation was cancelled at a journal-safe checkpoint."""


def checkpoint(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("Operation cancelled. Partially applied changes were rolled back.")


@dataclass(frozen=True)
class Rename:
    """One planned rename: ``src`` will become ``dst`` (both absolute,
    neither dereferenced)."""

    src: Path
    dst: Path

    def __str__(self) -> str:
        return f"{self.src.name} -> {self.dst.name}"


@dataclass(frozen=True)
class Move:
    """One primitive filesystem move (a single rename), absolute paths.

    A transaction records backup moves, ``src -> temp`` and
    ``temp -> dst`` moves in applied order; the inverse of that full list
    is a complete undo.
    """

    frm: str
    to: str


@dataclass(frozen=True)
class ValidationIssue:
    """A problem found while planning/validating a batch.

    ``severity`` is ``"error"`` (the batch must NOT be applied) or
    ``"warning"`` (an existing file would be overwritten; in safe-overwrite
    mode its content is preserved in a backup location, so undo still
    restores everything).
    """

    severity: str
    message: str
    paths: tuple = ()


def abspath(path: str) -> Path:
    """Absolute path WITHOUT dereferencing symlinks."""
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def lexists(path: Path) -> bool:
    """True if the entry exists, including broken/dangling symlinks."""
    return os.path.lexists(str(path))


def _rename(frm: str, to: str) -> None:
    """Single indirection over os.rename (a clean monkeypatch seam for
    tests; the only place os.rename is called)."""
    rename_no_replace(frm, to)
    sync_directories(Path(frm).parent, Path(to).parent)


def expand_paths(paths: Sequence[str], recursive: bool, cancel=None, progress=None, exclude=()) -> List[Path]:
    """Expand user-specified files/dirs into a deduplicated absolute list.

    A directory argument expands to its entries (recursively when
    ``recursive``); a file or symlink argument is taken as-is. Paths are
    absolutized with :func:`abspath`, never ``resolve()``: a symlink stays
    itself and gets renamed as a symlink. Only real directories are
    descended into; a symlink pointing at a directory is treated as an
    ordinary entry. Hidden files are included.
    """
    out: List[Path] = []
    for raw in paths:
        checkpoint(cancel)
        p = abspath(raw)
        if os.path.isdir(str(p)) and not os.path.islink(str(p)):
            out.extend(entry_files(p, recursive, cancel, progress, exclude))
        else:
            out.append(p)
    seen = set()
    unique: List[Path] = []
    for p in sorted(out, key=lambda x: str(x)):
        checkpoint(cancel)
        if str(p) not in seen:
            seen.add(str(p))
            unique.append(p)
    return unique


def entry_files(directory: Path, recursive: bool, cancel=None, progress=None, exclude=()) -> List[Path]:
    """Files/symlinks inside ``directory`` using a non-following walk."""
    results: List[Path] = []
    stack = [directory]
    excluded = [Path(p).resolve() for p in exclude]
    visited = set()
    while stack:
        checkpoint(cancel)
        current = stack.pop()
        if any(current.resolve().is_relative_to(p) for p in excluded):
            continue
        st = os.lstat(current)
        if stat.S_ISLNK(st.st_mode):
            results.append(current)
            continue
        key = (st.st_dev, st.st_ino)
        if key in visited:
            continue
        visited.add(key)
        fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != key:
                raise ValueError(f"Directory changed during discovery: {current}")
            with os.scandir(fd) as it:
                for entry in it:
                    checkpoint(cancel)
                    if entry.name.startswith(".renamer-"):
                        continue
                    p = abspath(current / entry.name)
                    if entry.is_dir(follow_symlinks=False):
                        if recursive:
                            stack.append(p)
                    elif entry.is_file(follow_symlinks=False) or entry.is_symlink():
                        results.append(p)
                    if progress:
                        progress(len(results), 0, "Discovering files")
        finally:
            os.close(fd)
    return sorted(results, key=lambda x: str(x))


def order_paths(paths: List[Path], mode: str) -> List[Path]:
    """Order files for numbering; the list position becomes the index.
    ``mtime``/``size`` use lstat so symlinks are not followed."""
    if mode == "name":
        return sorted(paths, key=lambda p: (str(p.parent), p.name))
    if mode == "natural":
        return sorted(paths, key=lambda p: (str(p.parent),
                      [int(part) if part.isdecimal() else part.casefold()
                       for part in re.split(r"(\d+)", p.name)], p.name))
    if mode == "mtime":
        return sorted(paths, key=lambda p: (os.lstat(str(p)).st_mtime, str(p)))
    if mode == "size":
        return sorted(paths, key=lambda p: (os.lstat(str(p)).st_size, str(p)))
    if mode == "random":
        shuffled = sorted(paths, key=lambda p: str(p))
        random.shuffle(shuffled)
        return shuffled
    raise ValueError(f"unknown order mode: {mode!r}")


def _is_valid_name(name: str) -> bool:
    return bool(name) and not name.startswith(".renamer-") and "/" not in name and "\x00" not in name and name not in (
        ".",
        "..",
    )


def plan(
    paths: Sequence[Path], ops: Sequence[Op], cancel=None, progress=None
) -> Tuple[List[Rename], List[ValidationIssue]]:
    """Apply every operation to every path's name; drop unchanged entries.

    Returns the planned renames and planning-time issues (e.g. an empty or
    invalid generated name). Never touches the filesystem.
    """
    total = len(paths)
    planned: List[Rename] = []
    issues: List[ValidationIssue] = []
    for index, path in enumerate(paths):
        checkpoint(cancel)
        stem, suffix = split_name(path.name)
        for op in ops:
            stem, suffix = op(stem, suffix, index, total)
        new_name = stem + suffix
        if not _is_valid_name(new_name):
            issues.append(
                ValidationIssue("error", f"invalid generated name {new_name!r} for {path}", (str(path),))
            )
            continue
        dest = path.parent / new_name
        if str(dest) == str(path):
            continue
        planned.append(Rename(path, dest))
        if progress:
            progress(index + 1, total, "Planning names")
    return planned, issues


def validate(renames: Sequence[Rename], force: bool = False, cancel=None) -> List[ValidationIssue]:
    """Validate a whole planned batch (pure: only reads the filesystem).

    Errors — the batch must not be applied, and ``force`` never bypasses
    any of them:
      - a source does not exist (lstat semantics: a dangling symlink does
        exist)
      - duplicate source paths
      - duplicate destinations (two or more sources resolve to one target)
      - a destination parent directory is missing

    Warnings — only when ``force`` is true (otherwise errors): the
    destination is occupied by a file outside the batch. With ``force`` the
    transaction moves the occupant to a protected backup path, so no data
    is destroyed and undo restores both files.
    """
    issues: List[ValidationIssue] = []
    keys = []
    for r in renames:
        checkpoint(cancel)
        keys.append((canonical(r.src), canonical(r.dst)))
    sources = {key[0] for key in keys}
    seen_sources, destinations, limits = set(), {}, {}
    for r, (src_key, dst_key) in zip(renames, keys):
        checkpoint(cancel)
        paths = (str(r.src), str(r.dst))
        def issue(message, severity="error", related=paths):
            issues.append(ValidationIssue(severity, message, related))
        if src_key in seen_sources:
            issue(f"duplicate source or aliased path: {r.src}")
        seen_sources.add(src_key)
        if dst_key in destinations:
            previous = destinations[dst_key]
            issue(f"duplicate destination {r.dst}: both {previous} and {r.src} point at it (force cannot bypass this)",
                  related=paths + (previous,))
        destinations[dst_key] = str(r.src)
        if src_key == dst_key:
            issue("Source and destination are identical")
        if r.src.name.startswith(".renamer-"):
            issue("Journal-managed temporary/backup entries cannot be selected")
        if not lexists(r.src):
            issue(f"source does not exist: {r.src}")
        else:
            mode = os.lstat(r.src).st_mode
            if stat.S_ISDIR(mode):
                issue("Directory renaming is not supported")
            elif not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                issue(f"Only regular files and symlinks can be renamed: {r.src}")
        if not _is_valid_name(r.dst.name):
            issue(f"invalid destination name: {r.dst}")
            continue
        if not r.dst.parent.is_dir():
            issue(f"destination parent missing: {r.dst.parent}")
            continue
        parent = str(r.dst.parent)
        if parent not in limits:
            limits[parent] = os.pathconf(parent, "PC_NAME_MAX")
        if limits[parent] > 0 and len(os.fsencode(r.dst.name)) > limits[parent]:
            issue(f"Filename exceeds {limits[parent]} bytes: {r.dst.name}")
            continue
        if lexists(r.dst):
            mode = os.lstat(r.dst).st_mode
            if stat.S_ISDIR(mode):
                issue(f"Cannot overwrite a directory: {r.dst}")
            elif not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                issue(f"Cannot overwrite a special file: {r.dst}")
            elif dst_key not in sources:
                if force:
                    issue(f"destination {r.dst} (from {r.src}) will be overwritten; occupant content preserved in backup", "warning")
                else:
                    issue(f"destination already exists: {r.dst} (from {r.src}) (use --force for a safe, undoable overwrite)")
    return issues


def has_errors(issues: Sequence[ValidationIssue]) -> bool:
    return any(i.severity == "error" for i in issues)


def summary(issues: Sequence[ValidationIssue]) -> str:
    return "\n".join(f"[{i.severity}] {i.message}" for i in issues)


def occupied_destinations(renames: Sequence[Rename]) -> List[Rename]:
    """Renames whose destination exists but is not itself a batch source."""
    sources = {canonical(r.src) for r in renames}
    return [r for r in renames if lexists(r.dst) and canonical(r.dst) not in sources]


def canonical(path):
    path = Path(path)
    return str(path.parent.resolve() / path.name)


def snapshot(renames):
    """Capture the sources and destination occupants shown by a preview."""
    return {str(p): fingerprint(p) if lexists(p) else None
            for r in renames for p in (r.src, r.dst)}


def fingerprint(path):
    st = os.lstat(path)
    return [st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns]


def execute(tx, renames: Sequence[Rename], force: bool = False, expected_state=None, cancel=None, progress=None) -> None:
    from .session import transaction_lock, check_pending
    with transaction_lock(tx.root):
        check_pending(tx.root, exclude=tx.id)
        if tx.moves or tx.status != "planned":
            raise ValueError("Use a fresh transaction for each batch")
        renames = [Rename(abspath(r.src), abspath(r.dst)) for r in renames]
        checkpoint(cancel)
        reviewed = snapshot(renames) if expected_state is None else expected_state
        if snapshot(renames) != reviewed:
            raise ValueError("Files changed since the reviewed preview. Refresh preview before applying.")
        state_root = Path(tx.root).resolve()
        if any(p.parent.resolve().is_relative_to(state_root) for r in renames for p in (r.src, r.dst)):
            raise ValueError("The transaction storage directory cannot be renamed")
        issues = validate(renames, force, cancel)
        if has_errors(issues):
            if occupied_destinations(renames) and not force:
                raise FileExistsError(summary(issues))
            raise ValueError(summary(issues))
        moves = []
        for r in occupied_destinations(renames):
            moves.append(Move(str(r.dst), str(_unique_sibling(r.dst, "bak"))))
        final = []
        for r in renames:
            temp = _unique_sibling(r.src, "tmp")
            moves.append(Move(str(r.src), str(temp)))
            final.append(Move(str(temp), str(r.dst)))
        state = {canonical(path): identity for path, identity in reviewed.items()}
        expected = []
        for move in moves + final:
            source, destination = canonical(move.frm), canonical(move.to)
            identity = state.get(source)
            if identity is None or state.get(destination) is not None:
                raise ValueError("Files changed since the reviewed preview. Refresh preview before applying.")
            expected.append(identity)
            state[destination], state[source] = identity, None
        _run(tx, moves + final, expected=expected, cancel=cancel, progress=progress)


def inverse_moves(moves: Sequence[Move]) -> List[Move]:
    return [Move(m.to, m.frm) for m in reversed(list(moves))]


def preflight(moves, expected=None, cancel=None):
    """Simulate the entire sequence, including occupied temporary names."""
    state = {}
    def get(path):
        key = canonical(path)
        if key not in state:
            state[key] = fingerprint(path) if lexists(Path(path)) else None
        return state[key]
    records = []
    for i, m in enumerate(moves):
        checkpoint(cancel)
        identity = get(m.frm)
        if identity is None:
            raise FileNotFoundError(m.frm)
        if expected is not None and identity != expected[i]:
            raise ValueError(f"File changed since transaction: {m.frm}")
        if get(m.to) is not None:
            raise FileExistsError(f"Refusing to overwrite: {m.to}")
        if not Path(m.to).parent.is_dir():
            raise FileNotFoundError(str(Path(m.to).parent))
        records.append(identity)
        state[canonical(m.to)], state[canonical(m.frm)] = identity, None
    return records


def apply_moves(tx, moves: Sequence[Move], expected=None, cancel=None, progress=None) -> None:
    _run(tx, list(moves), expected, cancel, progress)


def _run(tx, moves, expected=None, cancel=None, progress=None):
    checkpoint(cancel)
    tx.identities = preflight(moves, expected, cancel)
    tx.planned_moves = list(moves)
    tx.status = "phase1"
    tx.save()  # complete write-ahead plan, before ANY filesystem move
    try:
        for i, m in enumerate(moves):
            checkpoint(cancel)
            if fingerprint(m.frm) != tx.identities[i]:
                raise ValueError(f"Source changed: {m.frm}")
            tx.pending = {"from": m.frm, "to": m.to, "identity": tx.identities[i]}
            tx.save()
            _rename(m.frm, m.to)
            tx.moves.append(m)
            tx.pending = None
            tx.save()
            if progress:
                progress(i + 1, len(moves), "Renaming files")
        checkpoint(cancel)
        tx.status = "completed"
        tx.save()
    except Exception as exc:
        tx.status = "failed"
        try:
            recover_transaction(tx, progress=progress)
        except Exception as rollback_error:
            raise RuntimeError(f"Transaction interrupted; recovery needed for {tx.id}: {rollback_error}") from exc
        raise


def _settle_pending(tx):
    if not tx.pending:
        return
    p = tx.pending
    frm, to, identity = p["from"], p["to"], p["identity"]
    source = fingerprint(frm) if lexists(Path(frm)) else None
    dest = fingerprint(to) if lexists(Path(to)) else None
    if source == identity:
        pass  # move did not happen
    elif source is None and dest == identity:
        if p.get("rollback"):
            tx.moves.pop()
        else:
            tx.moves.append(Move(frm, to))
    else:
        raise ValueError(f"Ambiguous recovery state: {frm} -> {to}; files left untouched")
    tx.pending = None
    tx.save()


def recover_transaction(tx, cancel=None, progress=None):
    """Restore the original state; stop rather than overwrite changed files."""
    if tx.status in ("completed", "rolled_back"):
        raise ValueError(f"Session {tx.id} does not need recovery")
    _settle_pending(tx)
    tx.status = "recovering"
    tx.save()
    total = len(tx.moves)
    try:
        while tx.moves:
            if cancel is not None and cancel.is_set():
                raise Cancelled("Recovery paused. Resume it from History / recovery.")
            m = tx.moves[-1]
            identity = tx.identities[len(tx.moves)-1]
            if fingerprint(m.to) != identity:
                raise ValueError(f"Recovery file changed: {m.to}")
            tx.pending = {"from": m.to, "to": m.frm, "identity": identity, "rollback": True}
            tx.save()
            _rename(m.to, m.frm)
            tx.moves.pop()
            tx.pending = None
            tx.save()
            if progress:
                progress(total - len(tx.moves), total, "Restoring original names")
        tx.status = "rolled_back"
        tx.save()
    except Exception:
        tx.status = "failed"
        tx.save()
        raise


def _unique_sibling(path: Path, kind: str) -> Path:
    name = f".renamer-{kind}-{uuid.uuid4().hex}"
    candidate = path.parent / name
    if lexists(candidate):
        raise FileExistsError(f"internal name collision: {candidate}")
    return candidate
