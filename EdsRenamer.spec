"""Inspectible native bundle shared by build.sh and the AppImage build."""
import ctypes.util
import json
import os
import subprocess
from pathlib import Path

project = Path(SPECPATH)
build_root = Path(os.environ.get('ER_BUILD_ROOT', '/tmp/eds-renamer-build'))
cache = subprocess.check_output(['ldconfig', '-p'], text=True).splitlines()


def resolve_library(name, soname):
    library = ctypes.util.find_library(name) or soname
    for line in cache:
        if line.strip().startswith(library + ' '):
            return line.split('=>', 1)[1].strip()
    for directory in os.environ.get('LD_LIBRARY_PATH', '').split(':'):
        if directory and (Path(directory) / soname).is_file():
            return str(Path(directory) / soname)
    raise RuntimeError(f'Install the system {name} shared library before building')


# Include GLVND dispatch shims explicitly; PyInstaller otherwise expects them
# on the host. GPU-specific vendor drivers remain provided by the desktop.
native = [resolve_library(name, soname) for name, soname in (
    ('EGL', 'libEGL.so.1'), ('GL', 'libGL.so.1'), ('GLX', 'libGLX.so.0'),
    ('GLdispatch', 'libGLdispatch.so.0'))]
a = Analysis(
    [str(project / 'renamer_gui.py')], pathex=[str(project)],
    binaries=[(path, '.') for path in native],
    datas=[(str(project / 'assets/filehash.png'), 'assets'), (str(project / 'LICENSE'), '.')],
    excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick'],
    noarchive=False,
)
build_root.mkdir(parents=True, exist_ok=True)
(build_root / 'native-sources.json').write_text(json.dumps([item[1] for item in a.binaries], indent=2))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='EdsRenamer',
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='EdsRenamer')
