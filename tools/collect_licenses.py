"""Generate current license texts and exact build dependency inventories."""
import importlib.metadata
import json
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


def collect(destination, manifest):
    project = Path(__file__).resolve().parents[1]
    destination.mkdir(parents=True, exist_ok=True)
    licenses = destination / 'licenses'; licenses.mkdir(exist_ok=True)
    for name in ('LICENSE', 'NOTICE.md'):
        shutil.copyfile(project / name, destination / name)
    shutil.copyfile(Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt', licenses / 'Python-LICENSE.txt')
    shutil.copyfile(project / 'LICENSE', licenses / 'Qt-GPL-3.txt')
    qt = importlib.metadata.version('PySide6_Essentials')
    (licenses / 'Qt-NOTICE.txt').write_text(
        f'Qt/PySide6 {qt}, The Qt Company and contributors.\n'
        'Open-source LGPLv3/GPLv3 distribution. Ed\'s Renamer is GPL-3.0.\n'
        f'Qt source: https://download.qt.io/archive/qt/{".".join(qt.split(".")[:2])}/{qt}/submodules/\n'
        f'PySide source: https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v{qt}\n'
        'Application source and build instructions permit rebuilding with replacement libraries.\n')
    records, collected = [], set()
    for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        records.append(f"{dist.metadata['Name']}=={dist.version}")
        for member in dist.files or []:
            if '..' in member.parts or not any(p.lower().startswith(('license', 'copying', 'notice')) for p in member.parts):
                continue
            source = Path(dist.locate_file(member))
            if source.is_file():
                out = licenses / 'python-packages' / f"{dist.metadata['Name']}-{dist.version}" / member
                out.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, out)
                collected.add(dist.metadata['Name'].lower())
    if 'regex' not in collected:
        raise RuntimeError('Missing regex license text')
    (destination / 'python-dependencies.txt').write_text('\n'.join(records) + '\n')
    (destination / 'python-runtime.txt').write_text(sys.version + '\n')
    packages = set()
    for value in json.loads(Path(manifest).read_text()):
        path = Path(value)
        if not str(path).startswith(('/lib/', '/usr/lib/')):
            continue
        candidates = {str(path), str(path.resolve())}
        candidates.update(p.replace('/usr/lib/', '/lib/', 1) for p in list(candidates))
        for candidate in candidates:
            result = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True)
            if not result.returncode:
                packages.update(line.rsplit(': ', 1)[0] for line in result.stdout.splitlines())
                break
    for package in sorted(packages):
        name = package.split(':', 1)[0]; source = Path('/usr/share/doc') / name / 'copyright'
        if not source.is_file():
            raise RuntimeError(f'Missing copyright notice for {package}')
        out = licenses / 'system-packages' / name / 'copyright'
        out.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, out)
    inventory = subprocess.check_output(['dpkg-query', '-W', '-f=${Package}=${Version}\\n', *sorted(packages)], text=True) if packages else ''
    (destination / 'native-packages.txt').write_text(inventory)
    print(f'Collected notices for {len(records)} Python distributions and {len(packages)} native packages')


if __name__ == '__main__':
    collect(Path(sys.argv[1]), sys.argv[2])
