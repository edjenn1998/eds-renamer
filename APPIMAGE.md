# Build and verify the AppImage

For downloading and running, see [README.md](README.md), including the no-FUSE fallback.

## Official environment

Ubuntu 22.04 x86_64, Python **3.12.15**, `requirements-build.txt` and its included
runtime/dev pins. The actual native dependency versions are recorded per build.
AppImage tooling, the static runtime and license texts are hash-verified against
`packaging/appimage/toolchain.json`.

```sh
sudo apt-get update
sudo apt-get install libegl1 libgl1 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 binutils desktop-file-utils libglib2.0-bin xvfb xauth
# Supply Python 3.12.15; CI uses actions/setup-python.
python3.12 -m venv .venv-build
. .venv-build/bin/activate
python -m pip install -r requirements-build.txt
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
ER_PYTHON="$PWD/.venv-build/bin/python" \
ER_BUILD_ROOT=/tmp/eds-renamer-build \
bash packaging/appimage/build-appimage.sh
```

Use a clean environment and unused build directory for a release. The scripts
use an extracted build tool and test extraction-mode launching, so building does
not require FUSE. The modern runtime is statically linked; users do not need the
old libfuse2 package. Continuous upstream URLs can change: a hash mismatch stops
the build until the toolchain is deliberately reviewed and repinned.

`build.sh` alone creates an inspectable native onedir bundle at
`$ER_BUILD_ROOT/dist/EdsRenamer/`, using `EdsRenamer.spec`. It does not silently
install dependencies. `launch.sh` uses the downloaded/built AppImage if executable,
otherwise a configured `ER_PYTHON` or local virtual environment.

## Verification

The build checks every ELF's glibc symbols and native dependencies, explicitly
bundles vendor-neutral GLVND dispatch libraries, collects current license texts,
and runs bundled preview/regex/rename/undo/redo tests. Final AppImages are tested
both offscreen and on X11 via Xvfb, plus CLI startup. GPU vendor drivers remain
native to the user's desktop.

Official builds reject a minimum glibc above **2.35**. `ER_MAX_GLIBC` can be changed
for a local native build on a newer system, but doing so does not make it work on
older distributions. Inspection failures are errors. ABI compatibility alone is
not a guarantee for every distribution, desktop or filesystem.

Outputs under `dist/`:

- `EdsRenamer-1.1.0-x86_64.AppImage`
- `SHA256SUMS`
- `abi-audit.json`
- `python-dependencies.txt`
- `native-packages.txt`

Notices and dependency inventories are also included under
`usr/share/eds-renamer/` inside the AppImage. The approved `assets/filehash.png`
icon is retained and scaled for AppImage metadata. The ABI report covers the
payload; the appended static runtime has no glibc requirement.

## Publishing

GitHub Actions produces an `EdsRenamer-Linux-x86_64` artifact after all checks pass.
Download it, verify SHA-256 checksums, test the downloaded application with clean
library paths, and publish the exact tested source commit as a versioned release.
Upload the five generated files and preserve older releases. This is a repeatable,
documented build process, not a claim of bit-identical output across OS updates.
