"""Optional desktop shortcut for the single-file distribution."""
from pathlib import Path
import os
import sys


def install_shortcut(icon):
    if not getattr(sys, 'frozen', False):
        raise ValueError('Run the packaged app to install its application-menu shortcut.')
    executable = Path(os.environ.get('APPIMAGE', sys.executable)).absolute()
    if any(c in str(executable) for c in ('\n', '\r', '\x00')):
        raise ValueError('Move the app to a path without newline/control characters before installing a shortcut.')
    data_home = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    icon_dir = data_home / 'icons/hicolor/256x256/apps'
    icon_dir.mkdir(parents=True, exist_ok=True)
    from PySide6.QtGui import QImage
    image = QImage(str(icon))
    if image.isNull() or not image.scaled(256,256).save(str(icon_dir/'filehash.png')):
        raise OSError('Could not save the application icon')
    def escaped(text):
        quoted = text.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
        return quoted.replace('\\', '\\\\').replace('%', '%%')
    folder=data_home/'applications';folder.mkdir(parents=True,exist_ok=True)
    entry=folder/'filehash.desktop'
    # Keep the executable position constant: GIO checks it before expanding %%.
    # The fixed shell command only execs its quoted argv, never interpolated code.
    command = '/bin/sh -c "' + escaped('exec "$@"') + '" eds-renamer "' + escaped(str(executable)) + '"'
    entry.write_text('[Desktop Entry]\nType=Application\nName=Ed\'s Renamer\nComment=Preview and bulk rename files\nExec='+command+'\nIcon=filehash\nTerminal=false\nCategories=Utility;Qt;\nStartupWMClass=filehash\n',encoding='utf-8')
    return entry
