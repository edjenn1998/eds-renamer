from pathlib import Path

from renamer.cli import main
from renamer.session import list_session_ids


def test_dry_run_makes_no_changes_then_apply_then_undo(tmp_path):
    (tmp_path / "IMG_001.jpg").write_text("A")
    (tmp_path / "IMG_002.jpg").write_text("B")
    home = str(tmp_path / "home")

    rc = main(
        [
            "--home",
            home,
            "rename",
            str(tmp_path / "IMG_001.jpg"),
            str(tmp_path / "IMG_002.jpg"),
            "--regex",
            "^IMG_",
            "photo-",
        ]
    )
    assert rc == 0  # dry run
    assert (tmp_path / "IMG_001.jpg").exists()  # untouched
    assert not Path(home).exists()  # dry run created no journal either

    rc = main(
        [
            "--home",
            home,
            "rename",
            str(tmp_path / "IMG_001.jpg"),
            str(tmp_path / "IMG_002.jpg"),
            "--regex",
            "^IMG_",
            "photo-",
            "--apply",
        ]
    )
    assert rc == 0
    assert (tmp_path / "photo-001.jpg").read_text() == "A"
    assert (tmp_path / "photo-002.jpg").read_text() == "B"

    rc = main(["--home", home, "undo", "-y"])
    assert rc == 0
    assert (tmp_path / "IMG_001.jpg").read_text() == "A"
    assert (tmp_path / "IMG_002.jpg").read_text() == "B"


def test_cli_validation_error_blocks_apply(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    rc = main(
        [
            "--home",
            str(tmp_path / "home"),
            "rename",
            str(tmp_path / "a.txt"),
            "--name",
            "b",
            "--apply",
        ]
    )
    assert rc == 2
    assert (tmp_path / "a.txt").exists()


def test_cli_force_safe_overwrite_and_undo(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    rc = main(
        [
            "--home",
            str(tmp_path / "home"),
            "rename",
            str(tmp_path / "a.txt"),
            "--name",
            "b",
            "--apply",
            "--force",
        ]
    )
    assert rc == 0
    assert (tmp_path / "b.txt").read_text() == "A"
    rc = main(["--home", str(tmp_path / "home"), "undo", "-y"])
    assert rc == 0
    assert (tmp_path / "a.txt").read_text() == "A"
    assert (tmp_path / "b.txt").read_text() == "B"


def test_cli_dry_run_does_not_create_journal(tmp_path):
    (tmp_path / "a.txt").write_text("A")
    home = tmp_path / "home"
    rc = main(
        ["--home", str(home), "rename", str(tmp_path / "a.txt"), "--case", "upper"]
    )
    assert rc == 0
    assert not home.exists()


def test_cli_cli_level_redo_sequence(tmp_path):
    home = str(tmp_path / "home")
    (tmp_path / "a.txt").write_text("A")
    main(
        [
            "--home",
            home,
            "rename",
            str(tmp_path / "a.txt"),
            "--name",
            "z",
            "--apply",
        ]
    )
    assert (tmp_path / "z.txt").read_text() == "A"
    main(["--home", home, "undo", "-y"])
    assert (tmp_path / "a.txt").read_text() == "A"
    # undo again = redo
    sessions = _ids(home)
    main(["--home", home, "undo", "-y", "--session", sessions[-1]])
    assert (tmp_path / "z.txt").read_text() == "A"


def test_cli_numbering_start_via_cli(tmp_path):
    for n in "abc":
        (tmp_path / f"{n}.mp3").write_text(n.upper())
    rc = main(
        [
            "--home",
            str(tmp_path / "home"),
            "rename",
            str(tmp_path / "a.mp3"),
            str(tmp_path / "b.mp3"),
            str(tmp_path / "c.mp3"),
            "--name",
            "clip_#",
            "--number",
            "--start",
            "7",
            "--apply",
        ]
    )
    assert rc == 0
    assert sorted(p.name for p in tmp_path.glob("*") if p.is_file()) == [
        "clip_7.mp3",
        "clip_8.mp3",
        "clip_9.mp3",
    ]


def test_cli_cut_front(tmp_path):
    (tmp_path / "IMG_9.jpg").write_text("x")
    rc = main(
        [
            "--home",
            str(tmp_path / "h"),
            "rename",
            str(tmp_path / "IMG_9.jpg"),
            "--cut",
            "front",
            "4",
            "--apply",
        ]
    )
    assert rc == 0
    assert (tmp_path / "9.jpg").exists()


def test_cli_sessions_command(tmp_path):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--home", str(tmp_path / "home"), "sessions"])
    assert "no saved sessions" in buf.getvalue()


def _ids(home):
    return list_session_ids(Path(home))
