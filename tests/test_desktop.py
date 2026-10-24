from pathlib import Path
import sys
import pytest
pytest.importorskip('PySide6')
from renamer.desktop import install_shortcut
from renamer.gui import asset_path


def test_optional_menu_shortcut_handles_spaces_and_icon(tmp_path,monkeypatch):
    monkeypatch.delenv('APPIMAGE', raising=False)
    monkeypatch.delenv('XDG_DATA_HOME', raising=False)
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'executable',str(tmp_path/'My Apps'/'FileHash-x86_64'))
    entry=install_shortcut(asset_path())
    text=entry.read_text()
    assert "Name=Ed's Renamer\n" in text and 'Icon=filehash\n' in text
    assert f'"{tmp_path}/My Apps/FileHash-x86_64"' in text
    assert (tmp_path/'.local/share/icons/hicolor/256x256/apps/filehash.png').is_file()


def test_appimage_shortcut_uses_download_not_temporary_payload(tmp_path,monkeypatch):
    image = tmp_path / 'My Apps/EdsRenamer.AppImage'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', '/tmp/.mount-test/usr/bin/EdsRenamer')
    monkeypatch.setenv('APPIMAGE', str(image))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    entry = install_shortcut(asset_path())
    assert str(image) in entry.read_text()
    assert '.mount-test' not in entry.read_text()
    assert entry.parent == tmp_path / 'data/applications'


def test_shortcut_rejects_newline_path(tmp_path,monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('APPIMAGE', str(tmp_path / 'bad\nname.AppImage'))
    with pytest.raises(ValueError):
        install_shortcut(asset_path())


def test_desktop_exec_roundtrips_reserved_characters(tmp_path,monkeypatch):
    import shutil
    import subprocess
    import time
    if not shutil.which('gio'):
        pytest.skip('gio is required to exercise the real desktop-entry parser')
    result = tmp_path / 'launched'
    executable = tmp_path / 'My App $cash `tick` % percent "quote" back\\slash'
    executable.write_text('#!/usr/bin/python3\nfrom pathlib import Path\nPath(' + repr(str(result)) + ').write_text("ok")\n')
    executable.chmod(0o755)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setenv('APPIMAGE', str(executable))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    entry = install_shortcut(asset_path())
    subprocess.run(['gio', 'launch', str(entry)], check=True, capture_output=True, timeout=10)
    deadline = time.monotonic() + 5
    while not result.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert result.read_text() == 'ok'
