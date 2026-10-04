import os
from pathlib import Path

import pytest


def abspath_tmp(p):
    return Path(os.path.abspath(str(p)))


from renamer.engine import Move, Rename, execute  # noqa: E402
from renamer.session import (
    Transaction,
    create_transaction,
    list_session_ids,
    load_transaction,
    newest_session,
    new_session_id,
)


def test_create_load_roundtrip(tmp_path):
    tx = create_transaction(tmp_path, sid="sid-1")
    tx.moves.append(Move("/a/x", "/a/y"))
    tx.status = "completed"
    tx.save()
    loaded = load_transaction(tmp_path, "sid-1")
    assert loaded.id == "sid-1"
    assert loaded.status == "completed"
    assert loaded.moves == [Move("/a/x", "/a/y")]
    assert list_session_ids(tmp_path) == ["sid-1"]


def test_newest_is_last_added(tmp_path):
    for sid in ("20240101-000000-0000000", "30000101-000000-0000001"):
        tx = create_transaction(tmp_path, sid=sid)
        tx.status = "completed"
        tx.save()
    assert newest_session(tmp_path) == "30000101-000000-0000001"


def test_newest_empty_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        newest_session(tmp_path)


def test_ids_unique(tmp_path):
    assert new_session_id() != new_session_id()


def test_journal_written_before_changes(tmp_path):
    """The journal exists in planned state before the first move happens."""
    created = {}
    import renamer.engine as eng

    (tmp_path / "a.txt").write_text("A")
    tx = Transaction(id="s", root=tmp_path / "home")
    real = eng._rename

    def wrapper(frm, to):
        created["seen"] = sorted(
            str(p) for p in (tmp_path / "home" / "sessions").glob("*.json")
        )
        real(frm, to)

    eng._rename = wrapper
    try:
        execute(tx, [Rename(abspath_tmp(tmp_path / "a.txt"), abspath_tmp(tmp_path / "b.txt"))])
    finally:
        eng._rename = real
    assert created["seen"] == [str((tmp_path / "home" / "sessions" / "s.json"))]


def abspath_tmp(p):
    import os

    return type(p)(os.path.abspath(str(p)))
