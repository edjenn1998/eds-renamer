import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QMessageBox
from renamer.gui import Window

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

def finish(app,window):
    import time
    deadline=time.monotonic()+10
    while window.worker and window.worker.isRunning():
        app.processEvents()
        if time.monotonic()>deadline:raise AssertionError('Worker timed out')
        window.worker.wait(10)
    app.processEvents()


def test_gui_preview_apply_undo_redo(app,tmp_path,monkeypatch):
    a=tmp_path/'photo.jpg';a.write_bytes(b'image')
    window=Window(tmp_path/'state')
    window.paths=[str(a)];window.name.setText('holiday_###');window.number.setChecked(True)
    window.preview();finish(app,window)
    assert window.table.item(0,1).text()=='holiday_001.jpg'
    assert window.apply_button.isEnabled() and a.exists()
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    window.apply();finish(app,window)
    b=tmp_path/'holiday_001.jpg';assert b.read_bytes()==b'image' and not a.exists()
    window.undo_latest();finish(app,window);assert a.read_bytes()==b'image'
    window.undo_latest();finish(app,window);assert b.read_bytes()==b'image'
    window.close()


def test_gui_collision_blocks_apply(app,tmp_path):
    a=tmp_path/'a.txt';b=tmp_path/'b.txt';a.write_text('A');b.write_text('B')
    window=Window(tmp_path/'state');window.paths=[str(a),str(b)];window.name.setText('same')
    window.preview();finish(app,window)
    assert not window.apply_button.isEnabled()
    assert 'duplicate' in window.details.text().lower()
    assert a.read_text()=='A' and b.read_text()=='B'
    window.close()


def test_gui_blank_replace_deletes_text(app,tmp_path):
    a=tmp_path/'[website]photo.jpg';a.write_text('A')
    window=Window(tmp_path/'state');window.paths=[str(a)];window.old.setText('[website]')
    window.preview();finish(app,window)
    assert window.table.item(0,1).text()=='photo.jpg'
    assert window.windowTitle().startswith("Ed's Renamer") and not window.windowIcon().isNull()
    window.close()


def test_gui_keep_first_characters_and_number(app,tmp_path):
    paths=[]
    for text in ['MrRed (random).cbr','MrRed (other).cbr']:
        p=tmp_path/text;p.write_text('data');paths.append(str(p))
    window=Window(tmp_path/'state');window.paths=paths;window.keep.setValue(6)
    window.number.setChecked(True);window.mode.setCurrentIndex(2)
    window.preview();finish(app,window)
    assert [window.table.item(i,1).text() for i in range(2)]==['MrRed 001.cbr','MrRed 002.cbr']
    window.close()


def test_gui_remove_first_characters_and_add_text(app,tmp_path):
    a=tmp_path/'www.website-photo001.jpg';a.write_text('A')
    window=Window(tmp_path/'state');window.paths=[str(a)];window.cut.setValue(12);window.prefix.setText('Family Trip ')
    window.preview();finish(app,window)
    assert window.table.item(0,1).text()=='Family Trip photo001.jpg'
    window.close()


def test_number_location_comes_from_placeholder(app,tmp_path):
    window=Window(tmp_path/'state');window.name.setText('File###')
    assert not window.mode.isEnabled()
    window.name.setText('File');assert window.mode.isEnabled()
    assert window.mode.itemData(2)=='suffix'
    window.close()


def until(app,condition):
    import time
    from PySide6.QtTest import QTest
    deadline=time.monotonic()+10
    while not condition():
        app.processEvents();QTest.qWait(20)
        if time.monotonic()>deadline:raise AssertionError('Live preview timed out')
    app.processEvents()


def test_live_preview_keeps_rows_and_updates_while_typing(app,tmp_path):
    a=tmp_path/'a.txt';a.write_text('A');window=Window(tmp_path/'state')
    window.paths=[str(a)];window.preview();finish(app,window)
    window.name.setText('edited')
    assert window.table.rowCount()==1 and not window.apply_button.isEnabled()
    until(app,lambda:window.table.item(0,1).text()=='edited.txt' and window.apply_button.isEnabled())
    assert a.exists() and not (tmp_path/'edited.txt').exists()
    window.close()


def test_numbering_checkbox_enables_placeholders(app,tmp_path):
    paths=[]
    for name in ['a.png','b.png','c.png']:
        p=tmp_path/name;p.write_text('data');paths.append(str(p))
    window=Window(tmp_path/'state');window.paths=paths;window.name.setText('test ###')
    window.number.setChecked(True)
    until(app,lambda:window.table.rowCount()==3 and window.apply_button.isEnabled())
    assert [window.table.item(i,1).text() for i in range(3)]==['test 001.png','test 002.png','test 003.png']
    window.close()


def test_stale_preview_cannot_enable_apply(app,tmp_path,monkeypatch):
    import threading
    import renamer.gui as gui
    started=threading.Event();release=threading.Event();real=gui.plan
    def delayed(*args):
        started.set();release.wait(5);return real(*args)
    a=tmp_path/'a.txt';a.write_text('A');window=Window(tmp_path/'state');window.paths=[str(a)]
    monkeypatch.setattr(gui,'plan',delayed);window.name.setText('old');window.preview()
    assert started.wait(2)
    assert window.name.isEnabled()
    window.name.setText('latest');release.set()
    until(app,lambda:window.table.rowCount()==1 and window.table.item(0,1).text()=='latest.txt' and window.apply_button.isEnabled())
    window.close()


def test_invalid_pattern_keeps_rows_and_recovers_without_popup(app,tmp_path):
    a=tmp_path/'a.txt';a.write_text('A');window=Window(tmp_path/'state');window.paths=[str(a)]
    window.preview();finish(app,window);window.regex.setChecked(True);window.old.setText('[')
    until(app,lambda:window.details.text().startswith('Cannot preview:'))
    assert window.table.rowCount()==1 and not window.apply_button.isEnabled()
    window.old.setText('a');window.new.setText('b')
    until(app,lambda:window.table.item(0,1).text()=='b.txt' and window.apply_button.isEnabled())
    window.close()


def test_existing_hash_in_comic_name_is_preserved_without_template(app,tmp_path):
    a=tmp_path/'Spawn #001.cbz';a.write_text('A');window=Window(tmp_path/'state');window.paths=[str(a)];window.number.setChecked(False)
    window.preview();finish(app,window)
    assert window.table.item(0,1).text()=='Spawn #001.cbz'
    assert not window.renames
    window.close()
