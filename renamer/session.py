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
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .engine import Move, inverse_moves

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

    def path(self) -> Path:
        if not self.id or Path(self.id).name != self.id or self.id in (".", "..") or "\\" in self.id:
            raise ValueError("Invalid session id")
        return Path(self.root) / "sessions" / f"{self.id}.json"

    def save(self) -> Path:
        """Atomically rewrite the journal file for this transaction."""
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "id": self.id,
            "status": self.status,
            "moves": [[m.frm, m.to] for m in self.moves],
            "planned_moves": [[m.frm, m.to] for m in self.planned_moves],
            "identities": self.identities,
            "pending": self.pending,
            "version": 2,
        }
        tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex[:8]}")
        with tmp.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(tmp), str(path))
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return path

    def undo(self) -> "Transaction":
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
            preflight(moves, expected)  # refuse conflicts before creating a session
            new_tx = create_transaction(self.root)
            apply_moves(new_tx, moves, expected)
            return new_tx

    def recover(self):
        from .engine import recover_transaction
        with transaction_lock(self.root):
            current = load_transaction(self.root, self.id)
            recover_transaction(current)
            return current



def create_transaction(root: Path, sid: Optional[str] = None) -> Transaction:
    """Create (and journal) a new empty transaction in ``planned`` state."""
    tx = Transaction(id=sid or new_session_id(), root=Path(root))
    if tx.path().exists():
        raise FileExistsError("Session id already exists")
    tx.save()
    return tx


def load_transaction(root: Path, sid: str) -> Transaction:
    path = Transaction(id=sid, root=Path(root)).path()
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return Transaction(id=sid, root=Path(root), status="completed", moves=[Move(frm,to) for frm,to in data])
    return Transaction(
        id=data["id"],
        root=Path(root),
        status=data["status"],
        moves=[Move(frm, to) for frm, to in data["moves"]],
        planned_moves=[Move(frm, to) for frm, to in data.get("planned_moves", [])],
        identities=data.get("identities", []),
        pending=data.get("pending"),
    )


def list_session_ids(root: Path) -> List[str]:
    """Session ids ordered oldest -> newest (by file mtime, then name)."""
    directory = Path(root) / "sessions"
    if not directory.is_dir():
        return []
    files = list(directory.glob("*.json"))
    files.sort(key=lambda p: (p.stat().st_mtime, p.name))
    return [p.stem for p in files]


def newest_session(root: Path) -> str:
    ids = [sid for sid in list_session_ids(root) if load_transaction(root, sid).status == "completed"]
    if not ids:
        raise FileNotFoundError("no saved sessions to undo")
    return ids[-1]


from contextlib import contextmanager

@contextmanager
def transaction_lock(root):
    import fcntl
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
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
    pending = [sid for sid in list_session_ids(root)
               if sid != exclude and load_transaction(root, sid).status not in
               ("completed", "rolled_back", "planned")]
    if pending:
        raise RuntimeError("Recover interrupted sessions first: " + ", ".join(pending))
