#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "$0")" && pwd)
python_bin=${ER_PYTHON:-python3.12}
build_root=${ER_BUILD_ROOT:-/tmp/eds-renamer-build}
export ER_BUILD_ROOT="$build_root"
"$python_bin" -m pip check
"$python_bin" -m PyInstaller --noconfirm --clean \
  --workpath "$build_root/work" --distpath "$build_root/dist" "$project_dir/EdsRenamer.spec"
"$python_bin" "$project_dir/tools/audit_bundle.py" "$build_root/dist/EdsRenamer" \
  --max-glibc "${ER_MAX_GLIBC:-2.35}" > "$build_root/abi-audit.json"
"$python_bin" "$project_dir/tools/collect_licenses.py" \
  "$build_root/dist/EdsRenamer/share" "$build_root/native-sources.json"
QT_QPA_PLATFORM=offscreen "$build_root/dist/EdsRenamer/EdsRenamer" --self-test
