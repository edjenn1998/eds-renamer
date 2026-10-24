#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "$0")/../.." && pwd)
python_bin=${ER_PYTHON:-python3.12}
build_root=${ER_BUILD_ROOT:-/tmp/eds-renamer-build}
export ER_PYTHON="$python_bin" ER_BUILD_ROOT="$build_root"
version=$("$python_bin" -c 'import sys; sys.path.insert(0,sys.argv[1]); from renamer.version import VERSION; print(VERSION)' "$project_dir")
if [[ $(uname -m) != x86_64 ]]; then
  printf '%s\n' 'This AppImage build targets x86_64 only.' >&2
  exit 1
fi
"$python_bin" -c 'import sys; assert sys.version_info[:2] == (3,12), "Official AppImages use Python 3.12"'
bash "$project_dir/build.sh"
"$python_bin" "$project_dir/tools/fetch_appimage_tools.py" "$build_root/tools"
(cd "$build_root/tools" && ./appimagetool --appimage-extract)
app_dir=$(mktemp -d "$build_root/EdsRenamer.AppDir.XXXXXX")
trap 'rm -rf -- "$app_dir"' EXIT
mkdir -p "$app_dir/usr/lib/eds-renamer" "$app_dir/usr/share/eds-renamer" "$project_dir/dist"
cp -a "$build_root/dist/EdsRenamer/." "$app_dir/usr/lib/eds-renamer/"
mv "$app_dir/usr/lib/eds-renamer/share/"* "$app_dir/usr/share/eds-renamer/"
rmdir "$app_dir/usr/lib/eds-renamer/share"
cp "$project_dir/packaging/appimage/AppRun" "$app_dir/AppRun"; chmod +x "$app_dir/AppRun"
cp "$project_dir/packaging/appimage/filehash.desktop" "$app_dir/"
"$python_bin" -c 'from PySide6.QtGui import QImage; import sys; image=QImage(sys.argv[1]); assert not image.isNull(); assert image.scaled(256,256).save(sys.argv[2])' "$project_dir/assets/filehash.png" "$app_dir/filehash.png"
ln -s filehash.png "$app_dir/.DirIcon"
cp "$build_root/abi-audit.json" "$project_dir/dist/abi-audit.json"
cp "$build_root/abi-audit.json" "$project_dir/packaging/appimage/toolchain.json" "$app_dir/usr/share/eds-renamer/"
mkdir -p "$app_dir/usr/share/eds-renamer/licenses/appimage-runtime"
cp "$build_root/tools/"*-license "$app_dir/usr/share/eds-renamer/licenses/appimage-runtime/"
QT_QPA_PLATFORM=offscreen "$app_dir/AppRun" --self-test
output="$project_dir/dist/EdsRenamer-$version-x86_64.AppImage"
ARCH=x86_64 "$build_root/tools/squashfs-root/AppRun" --no-appstream \
  --runtime-file "$build_root/tools/runtime" "$app_dir" "$output"
chmod +x "$output"
QT_QPA_PLATFORM=offscreen "$output" --appimage-extract-and-run --self-test
QT_QPA_PLATFORM=xcb xvfb-run -a "$output" --appimage-extract-and-run --self-test
"$output" --appimage-extract-and-run --cli --version
cp "$app_dir/usr/share/eds-renamer/python-dependencies.txt" "$app_dir/usr/share/eds-renamer/native-packages.txt" "$project_dir/dist/"
(cd "$project_dir/dist" && sha256sum "$(basename "$output")" abi-audit.json python-dependencies.txt native-packages.txt > SHA256SUMS)
