import os
from pathlib import Path

import pytest

from renamer import operations as ops
from renamer.engine import (
    Move,
    Rename,
    abspath,
    execute,
    expand_paths,
    has_errors,
    inverse_moves,
    lexists,
    order_paths,
    plan,
    validate,
)
from renamer.session import Transaction


def tx_of(root) -> Transaction:
    return Transaction(id="test-tx", root=Path(root))


def run_renames(root, paths, ops_list, force=False):
    renames, issues = plan(paths, ops_list)
    issues = issues + validate(renames, force=force)
    if has_errors(issues):
        raise ValueError("; ".join(i.message for i in issues))
    tx = tx_of(root)
    execute(tx, renames, force=force)
    return tx


# ---------------------------------------------------------------- planning

def test_plan_replace_keeps_extension():
    p = abspath("/nowhere/vacation.jpg")
    renames, issues = plan([p], [ops.replace_op("vacation", "trip")])
    assert not issues
    assert len(renames) == 1
    assert renames[0].dst.name == "trip.jpg"


def test_cut_front_does_not_touch_ext(tmp_path):
    f = tmp_path / "IMG_001.jpg"
    f.write_text("x")
    renames, issues = plan([abspath(f)], [ops.cut_op("front", 4)])
    assert not issues
    assert renames[0].dst.name == "001.jpg"


def test_plan_drops_unchanged():
    f = Path(abspath("/x/same.txt"))
    renames, issues = plan([f], [ops.case_op("lower")])
    assert renames == [] and issues == []


def test_plan_flags_invalid_generated_name(tmp_path):
    f = tmp_path / "a"  # no extension: cut end 0 produces an empty name
    f.write_text("x")
    renames, issues = plan([abspath(f)], [ops.cut_op("end", 0)])
    assert renames == []
    assert has_errors(issues)


# ---------------------------------------------------------------- validate

def test_validate_duplicate_destinations_rejected_never_force(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    s = tmp_path / "same.txt"
    a.write_text("A")
    b.write_text("B")
    s.write_text("S")
    renames = [
        Rename(abspath(a), abspath(s)),
        Rename(abspath(b), abspath(s)),
    ]
    for force in (False, True):
        issues = validate(renames, force=force)
        assert has_errors(issues), f"force={force} must not bypass duplicates"
        msgs = " ".join(i.message for i in issues)
        assert "duplicate destination" in msgs
        assert str(b) in msgs and str(s) in msgs


def test_validate_missing_source(tmp_path):
    missing = abspath(tmp_path / "nope.txt")
    renames = [Rename(missing, abspath(tmp_path / "x.txt"))]
    issues = validate(renames)
    assert any("does not exist" in i.message for i in issues)


def test_validate_duplicate_sources(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("A")
    p = abspath(f)
    renames = [Rename(p, abspath(tmp_path / "x.txt")), Rename(p, abspath(tmp_path / "y.txt"))]
    assert any("duplicate source" in i.message for i in validate(renames))


def test_validate_external_occupied_error_without_force(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("A")
    dst = tmp_path / "b.txt"
    dst.write_text("B")
    renames = [Rename(abspath(src), abspath(dst))]
    issues = validate(renames, force=False)
    assert has_errors(issues)
    assert not any(i.severity == "warning" for i in issues)


def test_validate_external_occupied_warning_with_force(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("A")
    dst = tmp_path / "b.txt"
    dst.write_text("B")
    renames = [Rename(abspath(src), abspath(dst))]
    issues = validate(renames, force=True)
    assert not has_errors(issues)
    assert any(i.severity == "warning" for i in issues)


# ---------------------------------------------------------------- expand

def test_expand_dedupes_and_absolute(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("A")
    assert expand_paths([str(f), str(f)], False) == [abspath(f)]
    rel = expand_paths(["a.txt"], False)
    assert rel and os.path.isabs(str(rel[0]))


def test_expand_recursive_and_no_symlink_dir_follow(tmp_path):
    (tmp_path / "top.txt").write_text("x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("x")
    linkdir = tmp_path / "linkdir"
    os.symlink(str(sub), str(linkdir))
    got = expand_paths([str(tmp_path)], recursive=True)
    names = sorted(p.name for p in got)
    # linkdir is a symlink (to a dir): listed as an entry, never descended
    assert names == ["deep.txt", "linkdir", "top.txt"]
    assert all(not os.path.islink(str(p)) or p.name == "linkdir" for p in got)
    flat = expand_paths([str(tmp_path)], recursive=False)
    assert sorted(p.name for p in flat) == ["linkdir", "top.txt"]


# ---------------------------------------------------------------- execute

def test_execute_direct_and_undo_restores_content(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    tx = run_renames(tmp_path / "home", [abspath(tmp_path / "a.txt")], [ops.stem_set_op("b")])
    assert (tmp_path / "b.txt").read_text() == "A"
    assert not (tmp_path / "a.txt").exists()
    assert tx.status == "completed"
    tx.undo()
    assert (tmp_path / "a.txt").read_text() == "A"
    assert not (tmp_path / "b.txt").exists()


def test_execute_swap(tmp_path):
    (tmp_path / "a").write_text("A")
    (tmp_path / "b").write_text("B")
    pa = abspath(tmp_path / "a")
    pb = abspath(tmp_path / "b")
    renames = [
        Rename(pa, pb),  # a -> b
        Rename(pb, pa),  # b -> a
    ]
    tx = tx_of(tmp_path / "home")
    execute(tx, renames)
    assert (tmp_path / "a").read_text() == "B"
    assert (tmp_path / "b").read_text() == "A"
    tx.undo()
    assert (tmp_path / "a").read_text() == "A"
    assert (tmp_path / "b").read_text() == "B"


def test_execute_three_file_cycle(tmp_path):
    for n in "abc":
        (tmp_path / n).write_text(n.upper())
    paths = [abspath(tmp_path / n) for n in "abc"]
    renames = [
        Rename(paths[0], paths[1]),  # a -> b
        Rename(paths[1], paths[2]),  # b -> c
        Rename(paths[2], paths[0]),  # c -> a
    ]
    tx = tx_of(tmp_path / "home")
    execute(tx, renames)
    assert (tmp_path / "a").read_text() == "C"
    assert (tmp_path / "b").read_text() == "A"
    assert (tmp_path / "c").read_text() == "B"
    tx.undo()
    assert (tmp_path / "a").read_text() == "A"
    assert (tmp_path / "b").read_text() == "B"
    assert (tmp_path / "c").read_text() == "C"


def test_force_overwrite_preserves_content_and_undoes(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    renames = [Rename(abspath(tmp_path / "a.txt"), abspath(tmp_path / "b.txt"))]
    tx = tx_of(tmp_path / "home")
    execute(tx, renames, force=True)
    # B was backed up; a's content moved onto the a-name slot? check both.
    assert (tmp_path / "b.txt").read_text() == "A"
    # original B content preserved under a hidden backup entry
    backups = [p for p in tmp_path.iterdir() if ".renamer-bak-" in p.name]
    assert backups, "occupant was not preserved"
    tx.undo()
    assert (tmp_path / "a.txt").read_text() == "A"
    assert (tmp_path / "b.txt").read_text() == "B"
    assert not [p for p in tmp_path.iterdir() if ".renamer-" in p.name]


def test_execute_refuses_occupied_without_force(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    renames = [Rename(abspath(tmp_path / "a.txt"), abspath(tmp_path / "b.txt"))]
    tx = tx_of(tmp_path / "home")
    with pytest.raises(FileExistsError):
        execute(tx, renames, force=False)
    assert tx.moves == []
    assert (tmp_path / "a.txt").exists() and (tmp_path / "b.txt").exists()


# ------------------------------------------------------------- rollback

def _fail_on_nth_call(real_rename, n):
    """Rename that fails once, on its (1-based) nth call, then works."""
    state = {"n": 0}

    def side(frm, to):
        state["n"] += 1
        if state["n"] == n:
            raise OSError(9, "simulated filesystem failure", frm)
        real_rename(frm, to)

    return side


def test_phase1_failure_rolls_back_cleanly(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    renames = [
        Rename(abspath(tmp_path / "a.txt"), abspath(tmp_path / "a2.txt")),
        Rename(abspath(tmp_path / "b.txt"), abspath(tmp_path / "b2.txt")),
    ]
    import renamer.engine as eng

    real = os.rename
    monkeypatch.setattr(eng, "_rename", _fail_on_nth_call(real, 2))
    tx = tx_of(tmp_path / "home")
    with pytest.raises(OSError):
        execute(tx, renames)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt", "b.txt", "home"]
    assert (tmp_path / "a.txt").read_text() == "A"
    assert (tmp_path / "b.txt").read_text() == "B"
    assert tx.status == "rolled_back"
    # no leftover temp/bak files
    assert not [p.name for p in tmp_path.iterdir() if ".renamer-" in p.name]


def test_phase2_failure_rolls_back_cleanly(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    renames = [
        Rename(abspath(tmp_path / "a.txt"), abspath(tmp_path / "a2.txt")),
        Rename(abspath(tmp_path / "b.txt"), abspath(tmp_path / "b2.txt")),
    ]
    import renamer.engine as eng

    real = os.rename
    # phase1 is 2 moves; fail on the 3rd (first phase2 move)
    monkeypatch.setattr(eng, "_rename", _fail_on_nth_call(real, 3))
    tx = tx_of(tmp_path / "home")
    with pytest.raises(OSError):
        execute(tx, renames)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.txt", "b.txt", "home"]
    assert (tmp_path / "a.txt").read_text() == "A"
    assert tx.status == "rolled_back"
    assert not [p.name for p in tmp_path.iterdir() if ".renamer-" in p.name]


def test_backup_failure_rolls_back(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    renames = [Rename(abspath(tmp_path / "a.txt"), abspath(tmp_path / "b.txt"))]
    import renamer.engine as eng

    real = os.rename
    monkeypatch.setattr(eng, "_rename", _fail_on_nth_call(real, 1))
    tx = tx_of(tmp_path / "home")
    with pytest.raises(OSError):
        execute(tx, renames, force=True)
    assert (tmp_path / "a.txt").read_text() == "A"
    assert (tmp_path / "b.txt").read_text() == "B"
    assert tx.status == "rolled_back"
    assert not [p.name for p in tmp_path.iterdir() if ".renamer-" in p.name]


# ---------------------------------------------------------------- symlink

def test_symlink_is_renamed_not_target(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("REAL")
    link = tmp_path / "link.txt"
    os.symlink(str(real), str(link))
    renames = [Rename(abspath(link), abspath(tmp_path / "gone.txt"))]
    tx = tx_of(tmp_path / "home")
    execute(tx, renames)
    assert not os.path.lexists(str(link))
    moved = tmp_path / "gone.txt"
    assert os.path.islink(str(moved))  # still a symlink
    assert os.readlink(str(moved)) == str(real)
    assert real.read_text() == "REAL"  # target untouched
    tx.undo()
    assert os.path.islink(str(link))


def test_symlink_to_dir_not_listed_or_followed(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inner.txt").write_text("i")
    link = tmp_path / "linkdir"
    os.symlink(str(sub), str(link))
    got = expand_paths([str(link)], recursive=True)
    # selecting a symlink-to-dir: taken as-is (an entry), never scanned
    assert got == [abspath(link)]


# ---------------------------------------------------------------- misc

def test_ordering_modes(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A")
    b.write_text("BB")
    paths = [abspath(b), abspath(a)]
    assert [p.name for p in order_paths(list(paths), "name")] == ["a.txt", "b.txt"]
    by_size = order_paths(list(paths), "size")
    assert by_size[0].read_text() == "A"
    rnd = order_paths(list(paths), "random")
    assert sorted(str(p) for p in rnd) == sorted(str(p) for p in paths)


def test_inverse_moves_shape():
    ms = [Move("a", "t"), Move("t", "b")]
    assert inverse_moves(ms) == [Move("b", "t"), Move("t", "a")]


# -------------------------------------------------- rename -> undo -> redo

def state(tmp_path):
    """Name -> content for top-level entries only (ignores the journal dir)."""
    return {
        p.name: p.read_text()
        for p in sorted(tmp_path.iterdir())
        if p.is_file() and ".renamer-" not in p.name
    }


def test_rename_undo_redo_sequence(tmp_path):
    """Original -> rename -> undo -> undo-undo(undo) must return the
    post-rename state, filenames AND contents."""
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    home = tmp_path / "home"
    renames = [
        Rename(abspath(tmp_path / "b.txt"), abspath(tmp_path / "a.txt")),
        Rename(abspath(tmp_path / "a.txt"), abspath(tmp_path / "b.txt")),
    ]
    orig = state(tmp_path)
    assert orig == {"a.txt": "A", "b.txt": "B"}
    tx1 = tx_of(home)
    execute(tx1, renames)  # swap
    after_rename = state(tmp_path)
    assert after_rename == {"a.txt": "B", "b.txt": "A"}
    tx2 = tx1.undo()  # undo -> back to original ordering
    assert state(tmp_path) == orig
    tx3 = tx2.undo()  # undo the undo -> redo
    assert state(tmp_path) == after_rename
    assert tx1.status == tx2.status == tx3.status == "completed"

