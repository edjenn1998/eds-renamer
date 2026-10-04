#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
python3 -m PyInstaller --noconfirm --onefile --name EdsRenamer-1.0.3-x86_64 \
  --add-data assets/filehash.png:assets --distpath release \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQml \
  --exclude-module PySide6.QtQuick renamer_gui.py
