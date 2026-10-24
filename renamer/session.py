"""Durable version-2 journals, guarded undo/redo, and interrupted-batch recovery.

Legacy journals remain readable but automatic undo is refused because they
lack the identities needed to detect changed files safely.
"""
from __future__ import annotations

import itertools
import json
import os
import time
import uuid
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .engine import Move, inverse_moves
from .native import rename_no_replace, sync_directories

DEFAULT_ROOT = Path.home() / ".renamer"

_counter = itertools.count()


def new_session_id() -> str:
    base = time.strftime("%Y%m%d-%H%M%S")
    return f"{base}-{int(time.time() * 1000) % 1000:03d}{next(_counter):04d}-{uuid.uuid4().hex[:8]}"


@dataclass
class Transaction:
    """A journaled rename transaction (mutable; saved after every change)."""

    id: str
    root: Path
    status: str = "planned"
    moves: List[Move] = field(default_factory=list)
    planned_moves: List[Move] = field(default_factory=list)
    identities: list = field(default_factory=list)
    pending: Optional[dict] = None
    action: str = "rename"
    reverses: Optional[str] = None
    _persisted: bool = field(default=False, init=False, repr=False)

    def path(self) -> Path:
        if not isinstance(self.id, str) or not self.id or Path(self.id).name != self.id or self.id in (".", "..") or "\\" in self.id or "\x00" in self.id:
            raise ValueError("Invalid session id")
        return Path(self.root) / "sessions" / f"{self.id}.json"

    def save(self, exclusive=False) -> Path:
        """Atomically rewrite the journal file for this transaction."""
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = {
            "id": self.id,
            "status": self.status,
            "moves": [[m.frm, m.to] for m in self.moves],
            "planned_moves": [[m.frm, m.to] for m in self.planned_moves],
            "identities": self.identities,
            "pending": self.pending,
            "version": 2,
            "action": self.action,
            "reverses": self.reverses,
        }
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            if exclusive or not self._persisted:
                rename_no_replace(tmp, path)
            else:
                os.replace(tmp, path)
            sync_directories(path.parent)
            self._persisted = True
        finally:
            tmp.unlink(missing_ok=True)
        return path

    def undo(self, cancel=None, progress=None) -> "Transaction":
        """Perform the inverse of this transaction and record it as a new
        journal entry, which is itself undoable (i.e. redo)."""
        from .engine import apply_moves, preflight
        with transaction_lock(self.root):
            check_pending(self.root)
            current = load_transaction(self.root, self.id)
            if current.status != "completed":
                raise ValueError("Only completed transactions can be undone")
            if len(current.identities) != len(current.moves):
                raise ValueError("Legacy session lacks file identities; automatic undo refused")
            moves = inverse_moves(current.moves)
            expected = list(reversed(current.identities))
            preflight(moves, expected, cancel)  # refuse conflicts before creating a session
            new_tx = create_transaction(self.root)
            new_tx.action = "redo" if current.action == "undo" else "undo"
            new_tx.reverses = current.id
            apply_moves(new_tx, moves, expected, cancel, progress)
            return new_tx

    def recover(self, cancel=None, progress=None):
        from .engine import recover_transaction
        with transaction_lock(self.root):
            current = load_transaction(self.root, self.id)
            recover_transaction(current, cancel, progress)
            return current



def create_transaction(root: Path, sid: Optional[str] = None) -> Transaction:
    """Create (and journal) a new empty transaction in ``planned`` state."""
    tx = Transaction(id=sid or new_session_id(), root=Path(os.path.abspath(Path(root).expanduser())))
    tx.save(exclusive=True)
    return tx


def load_transaction(root: Path, sid: str) -> Transaction:
    path = Transaction(id=sid, root=Path(root)).path()
    try:
        def loaded(**values):
            tx = Transaction(id=sid, root=Path(root), **values)
            tx._persisted = True
            return tx
        if path.is_symlink():
            raise ValueError("journal is a symlink")
        data = json.loads(path.read_text(encoding="utf-8"))
        def moves(value):
            if not isinstance(value, list):
                raise ValueError("move list is invalid")
            result = []
            for pair in value:
                if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(p, str) or not p or "\x00" in p for p in pair):
                    raise ValueError("move record is invalid")
                result.append(Move(*pair))
            return result
        if isinstance(data, list):
            return loaded(status="completed", moves=moves(data))
        if not isinstance(data, dict) or data.get("id") != sid or data.get("version") != 2:
            raise ValueError("unsupported journal version or mismatched session ID")
        if data.get("status") not in {"planned", "phase1", "phase2", "completed", "failed", "recovering", "rolled_back"}:
            raise ValueError("invalid transaction status")
        applied, planned = moves(data["moves"]), moves(data.get("planned_moves", []))
        identities = data.get("identities", [])
        if not isinstance(identities, list) or any(not isinstance(v, list) or len(v) != 5 or any(type(n) is not int for n in v) for v in identities):
            raise ValueError("invalid file identities")
        if identities and (len(identities) < len(applied) or (planned and len(identities) != len(planned))):
            raise ValueError("identity and move counts do not match")
        if data["status"] == "completed" and identities and len(identities) != len(applied):
            raise ValueError("completed journal contains an incomplete move list")
        if data["status"] == "planned" and (applied or planned or identities or data.get("pending")):
            raise ValueError("planned journal already contains execution records")
        if data["status"] == "rolled_back" and applied:
            raise ValueError("rolled-back journal still contains applied moves")
        pending = data.get("pending")
        if pending is not None:
            if data["status"] in {"completed", "rolled_back"}:
                raise ValueError("finished journal still contains a pending move")
            if not identities:
                raise ValueError("pending journal lacks file identities")
            if not isinstance(pending, dict):
                raise ValueError("invalid pending move")
            moves([[pending["from"], pending["to"]]])
            identity = pending["identity"]
            if not isinstance(identity, list) or len(identity) != 5 or any(type(n) is not int for n in identity):
                raise ValueError("invalid pending identity")
            if "rollback" in pending and type(pending["rollback"]) is not bool:
                raise ValueError("invalid pending rollback marker")
        action = data.get("action", "rename")
        if action not in {"rename", "undo", "redo"}:
            raise ValueError("invalid transaction action")
        reverses = data.get("reverses")
        if reverses is not None:
            Transaction(id=reverses, root=Path(root)).path()
        return loaded(status=data["status"], moves=applied, planned_moves=planned,
                      identities=identities, pending=pending, action=action, reverses=reverses)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Cannot read session {sid}: {exc}") from exc


def inspect_sessions(root):
    """Keep history accessible even when a journal is damaged; never ignore it for mutations."""
    result = []
    for sid in list_session_ids(root):
        try:
            tx = load_transaction(root, sid)
            result.append((sid, tx.status, len(tx.moves), tx.action, ""))
        except (OSError, ValueError) as exc:
            result.append((sid, "unreadable", 0, "", str(exc)))
    return result


def list_session_ids(root: Path) -> List[str]:
    """Session ids ordered oldest -> newest (by file mtime, then name)."""
    directory = Path(root) / "sessions"
    if not directory.is_dir():
        return []
    files = list(directory.glob("*.json"))
    files.sort(key=lambda p: (p.lstat().st_mtime_ns, p.name))
    return [p.stem for p in files]


def newest_session(root: Path) -> str:
    ids = [sid for sid, status, _, _, _ in inspect_sessions(root) if status == "completed"]
    if not ids:
        raise FileNotFoundError("no saved sessions to undo")
    return ids[-1]


from contextlib import contextmanager

@contextmanager
def transaction_lock(root):
    import fcntl
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another renamer transaction is running")
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def check_pending(root, exclude=None):
    records = [record for record in inspect_sessions(root) if record[0] != exclude]
    unreadable = [f"{sid}: {error}" for sid, status, _, _, error in records if status == "unreadable"]
    if unreadable:
        raise RuntimeError("History contains unreadable journals; restore/repair them before changing files: " + "; ".join(unreadable))
    pending = [sid for sid, status, _, _, _ in records if status not in ("completed", "rolled_back", "planned")]
    if pending:
        raise RuntimeError("Recover interrupted sessions first: " + ", ".join(pending))
