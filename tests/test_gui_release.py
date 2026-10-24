import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from renamer.gui import Window, Worker
from renamer.session import inspect_sessions
from renamer import engine


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(app, window):
    deadline = time.monotonic() + 10
    while window.worker or window.preview_timer.isActive():
        app.processEvents(); QTest.qWait(10)
        if time.monotonic() > deadline:
            raise AssertionError("GUI worker did not finish")
    app.processEvents()


@pytest.fixture
def window(app, tmp_path):
    source = tmp_path / "photo.txt"
    source.write_text("contents")
    w = Window(tmp_path / "state")
    w.paths = [str(source)]
    w.name.setText("new")
    wait(app, w)
    yield w
    if w.worker:
        w.worker.cancel.set()
    wait(app, w)
    w.close()


def test_apply_refuses_source_changed_after_review(app, window, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: errors.append(a[-1]))
    source = tmp_path / "photo.txt"
    source.write_text("changed since review")
    window.apply(); wait(app, window)
    assert source.read_text() == "changed since review"
    assert not (tmp_path / "new.txt").exists()
    assert errors and "reviewed preview" in errors[0]
    assert not window.apply_button.isEnabled()


def test_confirmation_cannot_apply_a_different_preview(app, window, tmp_path, monkeypatch):
    def question(*args, **kw):
        window.name.setText("different")
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", question)
    window.apply(); wait(app, window)
    assert (tmp_path / "photo.txt").exists()
    assert not (tmp_path / "different.txt").exists()
    assert not inspect_sessions(window.root)


def test_cancel_button_rolls_back_current_transaction(app, window, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real = engine._rename
    def slow(frm, to):
        entered.set(); release.wait(3); real(frm, to)
    monkeypatch.setattr(engine, "_rename", slow)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.apply()
    assert entered.wait(2)
    assert window.cancel_button.isEnabled()
    window.cancel_button.click()
    release.set(); wait(app, window)
    assert (tmp_path / "photo.txt").read_text() == "contents"
    assert not (tmp_path / "new.txt").exists()
    assert inspect_sessions(window.root)[-1][1] == "rolled_back"


def test_corrupt_history_does_not_prevent_startup(app, tmp_path):
    root = tmp_path / "state"
    (root / "sessions").mkdir(parents=True)
    (root / "sessions/broken.json").write_text("{broken")
    w = Window(root)
    assert "History" in w.details.text()
    source = tmp_path / "a.txt"; source.write_text("data")
    w.paths = [str(source)]; w.name.setText("b"); wait(app, w)
    assert not w.apply_button.isEnabled()
    assert "unreadable" in w.details.text()
    w.close()


def test_preview_export_does_not_change_files(app, window, tmp_path, monkeypatch):
    target = tmp_path / "preview.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window.export_preview()
    text = target.read_text(encoding="utf-8-sig")
    assert "photo.txt,new.txt,Ready" in text
    assert (tmp_path / "photo.txt").exists() and not window.root.exists()


def test_presets_roundtrip_and_never_enable_overwrite(app, window, tmp_path, monkeypatch):
    target = tmp_path / "preset.json"
    window.prefix.setText("Trip "); window.order.setCurrentText("natural")
    window.force.setChecked(True)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window.save_preset()
    saved = json.loads(target.read_text())
    assert "force" not in saved["options"] and "paths" not in saved["options"]
    window.reset_options()
    assert window.name.text() == "" and window.number.isChecked()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    window.load_preset(); wait(app, window)
    assert window.prefix.text() == "Trip " and window.order.currentText() == "natural"
    assert not window.force.isChecked()


def test_invalid_preset_is_rejected_without_partial_updates(window):
    values = window.option_values()
    invalid = dict(values, prefix="should not apply", pad=999999)
    with pytest.raises(ValueError):
        window.set_options(invalid)
    assert window.option_values() == values
    with pytest.raises(ValueError):
        window.set_options([])


def test_selection_survives_live_preview_reordering(app, window, tmp_path):
    second = tmp_path / "second.txt"; second.write_text("other")
    window.name.setText(""); window.add_paths([str(second)]); wait(app, window)
    window.table.selectionModel().select(window.table.model().index(1, 0),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    window.prefix.setText("Prefix "); wait(app, window)
    selected = [window.preview_sources[i.row()] for i in window.table.selectionModel().selectedRows()]
    assert selected == [second]


def test_finished_preview_workers_are_released(app, window):
    for index in range(15):
        window.name.setText(f"file-{index}"); window.preview(); wait(app, window)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(window.findChildren(Worker)) <= 1


def test_dedicated_redo_button_tracks_a_completed_undo(app, window, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.apply(); wait(app, window)
    assert not window.redo_button.isEnabled()
    window.undo_latest(); wait(app, window)
    assert (tmp_path / "photo.txt").exists() and window.redo_button.isEnabled()
    window.redo_button.click(); wait(app, window)
    assert (tmp_path / "new.txt").exists() and not window.redo_button.isEnabled()


def test_numbering_natural_order_preserves_the_reviewed_mapping(app, tmp_path):
    paths = []
    for name in ("page10.txt", "page2.txt", "page1.txt"):
        path = tmp_path / name; path.write_text(name); paths.append(str(path))
    w = Window(tmp_path / "state")
    w.paths = paths; w.order.setCurrentText("natural"); w.name.setText("Page ###")
    wait(app, w)
    assert [(w.table.item(i, 0).text(), w.table.item(i, 1).text()) for i in range(3)] == [
        ("page1.txt", "Page 001.txt"), ("page2.txt", "Page 002.txt"), ("page10.txt", "Page 003.txt")]
    w.close()
