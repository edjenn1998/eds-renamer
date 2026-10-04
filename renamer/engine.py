"""Planning, full-batch validation, no-overwrite moves, and journaled recovery.

Linux renameat2 prevents overwriting at the syscall boundary. The complete
move plan is saved first; each move has a durable pending record so recovery
can distinguish interruptions before and after the syscall. Recovery refuses
ambiguous states and changed files rather than guessing.
"""
from __future__ import annotations

import os
import random
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

from .operations import Op, split_name


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


def abspath(path: str) -> Path:
    """Absolute path WITHOUT dereferencing symlinks."""
    return Path(os.path.abspath(str(path)))


def lexists(path: Path) -> bool:
    """True if the entry exists, including broken/dangling symlinks."""
    return os.path.lexists(str(path))


def _rename(frm: str, to: str) -> None:
    """Single indirection over os.rename (a clean monkeypatch seam for
    tests; the only place os.rename is called)."""
    # Linux renameat2(RENAME_NOREPLACE) prevents a last-moment overwrite.
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    if fn is None:
        raise OSError(errno.ENOSYS, "Safe no-overwrite rename requires Linux renameat2")
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    if fn(-100, os.fsencode(frm), -100, os.fsencode(to), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), to)
    for parent in {str(Path(frm).parent), str(Path(to).parent)}:
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def expand_paths(paths: Sequence[str], recursive: bool) -> List[Path]:
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
        p = abspath(raw)
        if os.path.isdir(str(p)) and not os.path.islink(str(p)):
            out.extend(entry_files(p, recursive))
        else:
            out.append(p)
    seen = set()
    unique: List[Path] = []
    for p in sorted(out, key=lambda x: str(x)):
        if str(p) not in seen:
            seen.add(str(p))
            unique.append(p)
    return unique


def entry_files(directory: Path, recursive: bool) -> List[Path]:
    """Files/symlinks inside ``directory`` using a non-following walk."""
    results: List[Path] = []
    stack = [directory]
    while stack:
        current = stack.pop()
        with os.scandir(str(current)) as it:
            for entry in it:
                if entry.name.startswith(".renamer-"):
                    continue  # preserve journal-managed backups and temporary entries
                p = abspath(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if recursive:
                        stack.append(p)
                else:
                    results.append(p)
    return sorted(results, key=lambda x: str(x))


def order_paths(paths: List[Path], mode: str) -> List[Path]:
    """Order files for numbering; the list position becomes the index.
    ``mtime``/``size`` use lstat so symlinks are not followed."""
    if mode == "name":
        return sorted(paths, key=lambda p: (str(p.parent), p.name))
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
    paths: Sequence[Path], ops: Sequence[Op]
) -> Tuple[List[Rename], List[ValidationIssue]]:
    """Apply every operation to every path's name; drop unchanged entries.

    Returns the planned renames and planning-time issues (e.g. an empty or
    invalid generated name). Never touches the filesystem.
    """
    total = len(paths)
    planned: List[Rename] = []
    issues: List[ValidationIssue] = []
    for index, path in enumerate(paths):
        stem, suffix = split_name(path.name)
        for op in ops:
            stem, suffix = op(stem, suffix, index, total)
        new_name = stem + suffix
        if not _is_valid_name(new_name):
            issues.append(
                ValidationIssue("error", f"invalid generated name {new_name!r} for {path}")
            )
            continue
        dest = path.parent / new_name
        if str(dest) == str(path):
            continue
        planned.append(Rename(path, dest))
    return planned, issues


def validate(renames: Sequence[Rename], force: bool = False) -> List[ValidationIssue]:
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
    sources, destinations = set(), set()
    for r in renames:
        src_key = str(r.src.parent.resolve() / r.src.name)
        dst_key = str(r.dst.parent.resolve() / r.dst.name)
        if src_key in sources or dst_key in destinations:
            issues.append(ValidationIssue("error", "Duplicate or aliased source/destination path"))
        sources.add(src_key)
        destinations.add(dst_key)
        if src_key == dst_key:
            issues.append(ValidationIssue("error", "Source and destination are identical"))
        if r.src.name.startswith(".renamer-"):
            issues.append(ValidationIssue("error", "Journal-managed temporary/backup entries cannot be selected"))
        if r.src.is_dir() and not r.src.is_symlink():
            issues.append(ValidationIssue("error", "Directory renaming is not supported"))
    for r in renames:
        if not _is_valid_name(r.dst.name):
            issues.append(
                ValidationIssue("error", f"invalid destination name: {r.dst}")
            )
    seen_src = set()
    for r in renames:
        if str(r.src) in seen_src:
            issues.append(ValidationIssue("error", f"duplicate source: {r.src}"))
        seen_src.add(str(r.src))
    for r in renames:
        if not lexists(r.src):
            issues.append(ValidationIssue("error", f"source does not exist: {r.src}"))
        if not os.path.isdir(str(r.dst.parent)):
            issues.append(
                ValidationIssue("error", f"destination parent missing: {r.dst.parent}")
            )
    dst_seen = {}
    for r in renames:
        key = str(r.dst)
        if key in dst_seen:
            issues.append(
                ValidationIssue(
                    "error",
                    f"duplicate destination {key}: both {dst_seen[key]} and"
                    f" {r.src} point at it (force cannot bypass this)",
                )
            )
        else:
            dst_seen[key] = str(r.src)
    for r in renames:
        if lexists(r.dst) and str(r.dst) not in {str(x.src) for x in renames}:
            if force:
                issues.append(
                    ValidationIssue(
                        "warning",
                        f"destination {r.dst} (from {r.src}) will be overwritten;"
                        " occupant content preserved in backup",
                    )
                )
            else:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"destination already exists: {r.dst} (from {r.src})"
                        " (use --force for a safe, undoable overwrite)",
                    )
                )
    return issues


def has_errors(issues: Sequence[ValidationIssue]) -> bool:
    return any(i.severity == "error" for i in issues)


def summary(issues: Sequence[ValidationIssue]) -> str:
    return "\n".join(f"[{i.severity}] {i.message}" for i in issues)


def occupied_destinations(renames: Sequence[Rename]) -> List[Rename]:
    """Renames whose destination exists but is not itself a batch source."""
    sources = {str(r.src) for r in renames}
    return [r for r in renames if lexists(r.dst) and str(r.dst) not in sources]


def fingerprint(path):
    st = os.lstat(path)
    return [st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns]


def execute(tx, renames: Sequence[Rename], force: bool = False) -> None:
    from .session import transaction_lock, check_pending
    with transaction_lock(tx.root):
        check_pending(tx.root, exclude=tx.id)
        if tx.moves or tx.status != "planned":
            raise ValueError("Use a fresh transaction for each batch")
        renames = [Rename(abspath(r.src), abspath(r.dst)) for r in renames]
        state_root = Path(tx.root).resolve()
        if any(p.parent.resolve().is_relative_to(state_root) for r in renames for p in (r.src, r.dst)):
            raise ValueError("The transaction storage directory cannot be renamed")
        issues = validate(renames, force)
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
        _run(tx, moves + final)


def inverse_moves(moves: Sequence[Move]) -> List[Move]:
    return [Move(m.to, m.frm) for m in reversed(list(moves))]


def preflight(moves, expected=None):
    """Simulate the entire sequence, including occupied temporary names."""
    state = {}
    def get(path):
        if path not in state:
            state[path] = fingerprint(path) if lexists(Path(path)) else None
        return state[path]
    records = []
    for i, m in enumerate(moves):
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
        state[m.to], state[m.frm] = identity, None
    return records


def apply_moves(tx, moves: Sequence[Move], expected=None) -> None:
    _run(tx, list(moves), expected)


def _run(tx, moves, expected=None):
    tx.identities = preflight(moves, expected)
    tx.planned_moves = list(moves)
    tx.status = "phase1"
    tx.save()  # complete write-ahead plan, before ANY filesystem move
    try:
        for i, m in enumerate(moves):
            if fingerprint(m.frm) != tx.identities[i]:
                raise ValueError(f"Source changed: {m.frm}")
            tx.pending = {"from": m.frm, "to": m.to, "identity": tx.identities[i]}
            tx.save()
            _rename(m.frm, m.to)
            tx.moves.append(m)
            tx.pending = None
            tx.save()
        tx.status = "completed"
        tx.save()
    except Exception as exc:
        tx.status = "failed"
        try:
            recover_transaction(tx)
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


def recover_transaction(tx):
    """Restore the original state; stop rather than overwrite changed files."""
    if tx.status in ("completed", "rolled_back"):
        raise ValueError(f"Session {tx.id} does not need recovery")
    _settle_pending(tx)
    tx.status = "recovering"
    tx.save()
    try:
        while tx.moves:
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
