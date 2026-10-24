#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "$0")" && pwd)
appimage="$project_dir/dist/EdsRenamer-1.1.0-x86_64.AppImage"
if [[ -x "$appimage" ]]; then
  exec "$appimage" "$@"
fi
python_bin=${ER_PYTHON:-$project_dir/.venv/bin/python}
if [[ ! -x "$python_bin" ]]; then
  python_bin=python3.12
fi
if ! command -v "$python_bin" >/dev/null 2>&1; then
  printf '%s\n' 'Use the AppImage, or create a Python 3.12 virtual environment as explained in README.md.' >&2
  exit 1
fi
exec "$python_bin" "$project_dir/renamer_gui.py" "$@"
