# Third-party notices

Ed's Renamer is distributed under **GPL-3.0**; see LICENSE. Third-party components
retain their own licenses. Current releases generate notices from the actual
installed Python distributions and bundled native packages; these and exact build
inventories are under `usr/share/eds-renamer/` inside the AppImage.

- Qt/PySide6: open-source LGPLv3/GPLv3 distribution. The generated Qt notice names
  the actual version and provides version-specific Qt and PySide source links.
- Python: Python Software Foundation license; https://www.python.org/downloads/source/
- regex: its included licenses; https://github.com/mrabarnett/mrab-regex
- PyInstaller: GPL with distribution exception; https://pyinstaller.org/
- AppImage runtime: MIT, with musl, libfuse, squashfuse, zstd and zlib components;
  https://github.com/AppImage/type2-runtime. Hash-verified runtime/component license
  texts are included; corresponding source/build instructions are in its BUILD.md.

The existing approved blue `###` icon is retained. Source and pinned build tooling
permit rebuilding the application with replacement library versions. Native GPU
drivers remain supplied by the user's desktop.
