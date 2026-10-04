"""Optional desktop shortcut for the single-file distribution."""
from pathlib import Path
import shutil
import sys


def install_shortcut(icon):
    if not getattr(sys, 'frozen', False):
        raise ValueError('Run the single-file app to install its application-menu shortcut.')
    executable = Path(sys.executable).absolute()
    icon_dir = Path.home() / '.local/share/icons/hicolor/256x256/apps'
    icon_dir.mkdir(parents=True, exist_ok=True)
    from PySide6.QtGui import QImage
    image = QImage(str(icon))
    if image.isNull() or not image.scaled(256,256).save(str(icon_dir/'filehash.png')):
        raise OSError('Could not save the application icon')
    def escaped(text):
        return text.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%','%%')
    folder=Path.home()/'.local/share/applications';folder.mkdir(parents=True,exist_ok=True)
    entry=folder/'filehash.desktop'
    entry.write_text('[Desktop Entry]\nType=Application\nName=Ed\'s Renamer\nComment=Preview and bulk rename files\nExec="'+escaped(str(executable))+'"\nIcon=filehash\nTerminal=false\nCategories=Utility;Qt;\nStartupWMClass=filehash\n',encoding='utf-8')
    return entry
