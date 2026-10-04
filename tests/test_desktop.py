from pathlib import Path
import sys
import pytest
pytest.importorskip('PySide6')
from renamer.desktop import install_shortcut
from renamer.gui import asset_path


def test_optional_menu_shortcut_handles_spaces_and_icon(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:tmp_path))
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'executable',str(tmp_path/'My Apps'/'FileHash-x86_64'))
    entry=install_shortcut(asset_path())
    text=entry.read_text()
    assert "Name=Ed's Renamer\n" in text and 'Icon=filehash\n' in text
    assert f'Exec="{tmp_path}/My Apps/FileHash-x86_64"' in text
    assert (tmp_path/'.local/share/icons/hicolor/256x256/apps/filehash.png').is_file()
