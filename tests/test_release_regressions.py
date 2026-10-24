import json
import os
import threading
from pathlib import Path

import pytest

from renamer import engine
from renamer.engine import Rename, Cancelled, snapshot, execute, expand_paths, order_paths, validate, has_errors
from renamer.operations import regex_op
from renamer.session import create_transaction, inspect_sessions, load_transaction, Transaction
from renamer.cli import main as cli_main


def pair(tmp_path):
    source = tmp_path / "original.txt"
    source.write_text("original contents")
    return source, tmp_path / "renamed.txt"


@pytest.mark.parametrize("change", ["source", "destination", "new_destination"])
def test_reviewed_preview_blocks_changed_files(tmp_path, change):
    src, dst = pair(tmp_path)
    if change == "destination":
        dst.write_text("old occupant")
    renames = [Rename(src, dst)]
    reviewed = snapshot(renames)
    if change == "source":
        src.write_text("changed source")
    else:
        dst.write_text("new occupant")
        if change == "destination":
            # A filesystem's clock tick may cover both equal-length writes.
            # Exercise the metadata contract deterministically, not clock speed.
            assert dst.stat().st_size == reviewed[str(dst)][3]
            os.utime(dst, ns=(dst.stat().st_atime_ns, reviewed[str(dst)][4] + 1_000_000_000))
    tx = create_transaction(tmp_path / "state")
    with pytest.raises(ValueError, match="reviewed preview"):
        execute(tx, renames, True, expected_state=reviewed)
    assert src.exists()
    if change != "source":
        assert dst.read_text() == "new occupant"
    assert not list(tmp_path.glob(".renamer-*"))


def test_force_cannot_move_directory_to_backup(tmp_path):
    src, dst = pair(tmp_path)
    dst.mkdir(); (dst / "important.txt").write_text("keep")
    renames = [Rename(src, dst)]
    assert has_errors(validate(renames, True))
    with pytest.raises(ValueError, match="directory"):
        execute(create_transaction(tmp_path / "state"), renames, True)
    assert src.read_text() == "original contents"
    assert (dst / "important.txt").read_text() == "keep"


def test_special_entries_are_not_renamed(tmp_path):
    src = tmp_path / "pipe"
    os.mkfifo(src)
    assert has_errors(validate([Rename(src, tmp_path / "newpipe")]))


def test_overlong_utf8_name_is_blocked_before_moves(tmp_path):
    src, _ = pair(tmp_path)
    dst = tmp_path / ("日" * 100)
    assert has_errors(validate([Rename(src, dst)]))
    with pytest.raises(ValueError):
        execute(create_transaction(tmp_path / "state"), [Rename(src, dst)])
    assert src.exists()
    assert not list(tmp_path.glob(".renamer-*"))


@pytest.mark.parametrize("after", [1, 2])
def test_cancellation_rolls_back_even_after_last_move(tmp_path, after):
    src, dst = pair(tmp_path)
    cancel = threading.Event()
    tx = create_transaction(tmp_path / "state")
    def progress(current, total, message):
        if current == after:
            cancel.set()
    with pytest.raises(Cancelled):
        execute(tx, [Rename(src, dst)], cancel=cancel, progress=progress)
    assert src.read_text() == "original contents" and not dst.exists()
    assert load_transaction(tx.root, tx.id).status == "rolled_back"
    assert not list(tmp_path.glob(".renamer-*"))


def test_cancelled_recovery_can_resume(tmp_path, monkeypatch):
    src, dst = pair(tmp_path)
    tx = create_transaction(tmp_path / "state")
    real = engine._rename
    def crash(frm, to):
        real(frm, to)
        raise KeyboardInterrupt()
    monkeypatch.setattr(engine, "_rename", crash)
    with pytest.raises(KeyboardInterrupt):
        execute(tx, [Rename(src, dst)])
    monkeypatch.setattr(engine, "_rename", real)
    cancel = threading.Event(); cancel.set()
    with pytest.raises(Cancelled, match="paused"):
        tx.recover(cancel)
    assert load_transaction(tx.root, tx.id).status == "failed"
    tx.recover()
    assert src.read_text() == "original contents"


def test_alias_paths_in_swap_share_the_simulation_state(tmp_path):
    src, dst = pair(tmp_path)
    dst.write_text("other")
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    tx = create_transaction(tmp_path / "state")
    execute(tx, [Rename(src, alias / dst.name), Rename(dst, src)])
    assert src.read_text() == "other" and dst.read_text() == "original contents"
    tx.undo()
    assert src.read_text() == "original contents" and dst.read_text() == "other"


def test_discovery_excludes_journal_root(tmp_path):
    src, _ = pair(tmp_path)
    state = tmp_path / "state"
    create_transaction(state)
    assert expand_paths([str(tmp_path)], True, exclude=[state]) == [src]


def test_discovery_cancel_is_cooperative(tmp_path):
    pair(tmp_path)
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        expand_paths([str(tmp_path)], True, cancel, lambda *args: cancel.set())


def test_natural_numbering_order(tmp_path):
    paths = [tmp_path / name for name in ("page10.txt", "page2.txt", "page1.txt")]
    assert [p.name for p in order_paths(paths, "natural")] == ["page1.txt", "page2.txt", "page10.txt"]


def test_exclusive_session_creation_preserves_concurrent_journal(tmp_path, monkeypatch):
    import renamer.session as session
    real = session.rename_no_replace
    def race(frm, to):
        Path(to).write_text("other journal")
        real(frm, to)
    monkeypatch.setattr(session, "rename_no_replace", race)
    with pytest.raises(FileExistsError):
        create_transaction(tmp_path, "same-id")
    assert (tmp_path / "sessions/same-id.json").read_text() == "other journal"
    assert len(list((tmp_path / "sessions").iterdir())) == 1


def test_failed_journal_rewrite_cleans_private_temp(tmp_path, monkeypatch):
    import renamer.session as session
    tx = create_transaction(tmp_path)
    original = tx.path().read_bytes()
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(session.os, "replace", fail)
    with pytest.raises(OSError):
        tx.save()
    assert tx.path().read_bytes() == original
    assert len(list(tx.path().parent.iterdir())) == 1
    assert tx.path().stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("data", ["{broken", '{"version":99}', '{"version":2,"id":"different"}', '[["/one"]]'])
def test_damaged_journal_is_reported_and_blocks_mutations(tmp_path, data):
    src, dst = pair(tmp_path)
    root = tmp_path / "state"; (root / "sessions").mkdir(parents=True)
    (root / "sessions/damaged.json").write_text(data)
    assert inspect_sessions(root)[0][1] == "unreadable"
    with pytest.raises(RuntimeError, match="unreadable"):
        execute(create_transaction(root), [Rename(src, dst)])
    assert src.exists() and not dst.exists()
    assert cli_main(["--home", str(root), "sessions"]) == 2


def test_journal_id_cannot_redirect_updates(tmp_path):
    tx = create_transaction(tmp_path, "original")
    data = json.loads(tx.path().read_text()); data["id"] = "another"
    tx.path().write_text(json.dumps(data))
    with pytest.raises(ValueError, match="session ID"):
        load_transaction(tmp_path, "original")
    assert not (tmp_path / "sessions/another.json").exists()


def test_undo_and_redo_record_their_relationship(tmp_path):
    src, dst = pair(tmp_path)
    tx = create_transaction(tmp_path / "state")
    execute(tx, [Rename(src, dst)])
    undo = tx.undo(); redo = undo.undo()
    assert load_transaction(tx.root, undo.id).action == "undo"
    assert load_transaction(tx.root, redo.id).action == "redo"
    assert undo.reverses == tx.id and redo.reverses == undo.id


def test_pathological_regex_times_out_instead_of_hanging():
    op = regex_op(r"(a|aa)+$", "x")
    with pytest.raises(ValueError, match="too long"):
        op("a" * 250 + "!", ".txt", 0, 1)


@pytest.mark.parametrize("args", [["--regex", "[", "x"], ["--regex", "(a)", r"\2"]])
def test_cli_bad_patterns_are_readable_errors_not_tracebacks(tmp_path, capsys, args):
    src, _ = pair(tmp_path)
    assert cli_main(["rename", str(src), *args]) == 2
    assert "error:" in capsys.readouterr().err


def test_invalid_session_id_type_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        Transaction(123, tmp_path).path()


@pytest.mark.parametrize("changed", ["source", "destination"])
def test_changes_during_validation_cannot_replace_reviewed_identities(tmp_path, monkeypatch, changed):
    src, dst = pair(tmp_path)
    renames = [Rename(src, dst)]
    reviewed = snapshot(renames)
    real = engine.validate
    def race(*args, **kwargs):
        issues = real(*args, **kwargs)
        (src if changed == "source" else dst).write_text("changed during validation")
        return issues
    monkeypatch.setattr(engine, "validate", race)
    with pytest.raises(ValueError):
        execute(create_transaction(tmp_path / "state"), renames, True, expected_state=reviewed)
    assert src.exists() and not list(tmp_path.glob(".renamer-*"))
    if changed == "destination":
        assert dst.read_text() == "changed during validation"


def test_cli_interrupt_reports_recovery_and_can_be_recovered(tmp_path, monkeypatch, capsys):
    src, dst = pair(tmp_path)
    real = engine._rename
    def crash(frm, to):
        real(frm, to)
        raise KeyboardInterrupt()
    monkeypatch.setattr(engine, "_rename", crash)
    root = tmp_path / "state"
    assert cli_main(["--home", str(root), "rename", str(src), "--name", "renamed", "--apply"]) == 130
    assert "recover" in capsys.readouterr().err
    monkeypatch.setattr(engine, "_rename", real)
    sid = inspect_sessions(root)[-1][0]
    assert cli_main(["--home", str(root), "recover", "--session", sid]) == 0
    assert src.read_text() == "original contents" and not dst.exists()


def test_finished_journal_with_pending_move_is_not_silently_accepted(tmp_path):
    src, dst = pair(tmp_path)
    tx = create_transaction(tmp_path / "state")
    execute(tx, [Rename(src, dst)])
    data = json.loads(tx.path().read_text())
    data["pending"] = {"from": str(src), "to": str(dst), "identity": data["identities"][0]}
    tx.path().write_text(json.dumps(data))
    assert inspect_sessions(tx.root)[-1][1] == "unreadable"


def test_cancellation_stops_preflight_before_any_move(tmp_path, monkeypatch):
    src, dst = pair(tmp_path)
    cancel = threading.Event()
    real = engine.fingerprint
    def cancel_after_read(path):
        result = real(path)
        cancel.set()
        return result
    monkeypatch.setattr(engine, "fingerprint", cancel_after_read)
    with pytest.raises(Cancelled):
        engine.preflight([engine.Move(str(src), str(dst)), engine.Move(str(dst), str(src))], cancel=cancel)
    assert src.exists() and not dst.exists()


def test_direct_transaction_cannot_overwrite_an_existing_journal(tmp_path):
    src, dst = pair(tmp_path)
    root = tmp_path / "state"
    original = create_transaction(root, "same-id")
    data = original.path().read_bytes()
    replacement = Transaction("same-id", root)
    with pytest.raises(FileExistsError):
        execute(replacement, [Rename(src, dst)])
    assert original.path().read_bytes() == data
    assert src.read_text() == "original contents" and not dst.exists()
