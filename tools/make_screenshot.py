"""Generate a README screenshot from disposable sample filenames."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from renamer.gui import Window

app = QApplication([])
with tempfile.TemporaryDirectory(prefix='eds-renamer-demo-') as directory:
    root = Path(directory)
    files = []
    for name in ('IMG_1.jpg', 'IMG_2.jpg', 'IMG_3.jpg', 'IMG_10.jpg', 'IMG_11.jpg', 'IMG_12.jpg'):
        path = root / name; path.write_text('Disposable screenshot fixture'); files.append(str(path))
    window = Window(root / 'state', persist=False)
    window.show(); window.paths = files
    window.order.setCurrentText('natural'); window.name.setText('Holiday ###')
    deadline = time.monotonic() + 10
    while window.worker or window.preview_timer.isActive():
        app.processEvents(); time.sleep(.01)
        if time.monotonic() > deadline: raise RuntimeError('Preview timed out')
    app.processEvents()
    assert window.table.rowCount() == 6 and window.apply_button.isEnabled()
    assert window.grab().save(sys.argv[1])
    window.close()
