#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$project_dir/release/EdsRenamer-1.0.3-x86_64" ]]; then
    exec "$project_dir/release/EdsRenamer-1.0.3-x86_64" "$@"
fi
if [[ ! -x "$project_dir/.venv/bin/python" ]]; then
    python3 -m venv "$project_dir/.venv"
fi
if ! "$project_dir/.venv/bin/python" -c 'import PySide6' >/dev/null 2>&1; then
    "$project_dir/.venv/bin/python" -m pip install -r "$project_dir/requirements.txt"
fi
exec "$project_dir/.venv/bin/python" "$project_dir/renamer_gui.py" "$@"
