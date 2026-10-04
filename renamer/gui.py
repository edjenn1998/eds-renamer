"""Qt desktop frontend. All filesystem changes go through the core engine."""
from pathlib import Path
import sys
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QCheckBox, QComboBox, QSpinBox, QFormLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QSplitter, QAbstractItemView, QDialog, QListWidget, QListWidgetItem,
    QScrollArea,
)
from . import operations as ops
from .engine import expand_paths, order_paths, plan, validate, has_errors, execute, summary
from .session import DEFAULT_ROOT, create_transaction, load_transaction, list_session_ids, newest_session


def asset_path():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "assets" / "filehash.png"


class Worker(QThread):
    result = Signal(object)
    error = Signal(str)
    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn
    def run(self):
        try:
            self.result.emit(self.fn())
        except Exception as exc:
            self.error.emit(str(exc))


class Window(QMainWindow):
    def __init__(self, root=DEFAULT_ROOT):
        super().__init__()
        self.root = Path(root)
        self.paths = []
        self.renames = []
        self.preview_sources = []
        self.worker = None
        self.preview_revision = 0
        self.preview_pending = False
        self.cached_selection = None
        self.cached_sources = None
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(180)
        self.preview_timer.timeout.connect(self.preview)
        self.setWindowTitle("Ed's Renamer 1.0.3 — preview before you rename")
        self.setWindowIcon(QIcon(str(asset_path())))
        self.resize(1280, 820)
        self.setAcceptDrops(True)
        help_menu = self.menuBar().addMenu("Help")
        guide = QAction("How to use Ed's Renamer", self); guide.triggered.connect(self.guide); help_menu.addAction(guide)
        shortcut = QAction("Add to application menu", self); shortcut.triggered.connect(self.install_shortcut); help_menu.addAction(shortcut)
        about = QAction("About Ed's Renamer", self)
        about.triggered.connect(lambda: QMessageBox.information(self,"About Ed's Renamer","Ed's Renamer 1.0.3\nBulk file renaming with preview, undo and recovery.\nLinux x86-64 edition."))
        help_menu.addAction(about)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("Ed's Renamer")
        title.setStyleSheet("font-size: 28px; font-weight: 600; margin: 8px 0;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Choose files, adjust their names, then review the preview."))
        tools = QHBoxLayout()
        for text, fn in [("Add files…", self.add_files), ("Add folder…", self.add_folder),
                         ("Remove selected", self.remove_selected), ("Clear", self.clear),
                         ("History / recovery…", self.history)]:
            button = QPushButton(text); button.clicked.connect(fn); tools.addWidget(button)
        tools.addStretch(); layout.addLayout(tools)
        split = QSplitter(); layout.addWidget(split, 1)
        controls = QWidget(); controls.setMinimumWidth(440); form_layout = QVBoxLayout(controls)
        selection = QGroupBox("Selection"); sf = QFormLayout(selection)
        self.recursive = QCheckBox("Include subfolders")
        self.order = QComboBox(); self.order.addItems(["name", "mtime", "size", "random"])
        sf.addRow(self.recursive); sf.addRow("Numbering order", self.order)
        form_layout.addWidget(selection)
        rename_group = QGroupBox("Name changes")
        form = QFormLayout(rename_group)
        self.name = QLineEdit(); self.name.setPlaceholderText("File name")
        self.old = QLineEdit(); self.old.setPlaceholderText("Text to find")
        self.new = QLineEdit(); self.new.setPlaceholderText("Replacement text")
        self.regex = QCheckBox("Advanced pattern matching")
        self.ignore = QCheckBox("Ignore letter case (patterns)")
        self.prefix = QLineEdit(); self.prefix.setPlaceholderText("Text to add at beginning")
        self.suffix = QLineEdit(); self.suffix.setPlaceholderText("Text to add at end")
        self.cut = QSpinBox(); self.cut.setRange(0, 10000)
        self.keep = QSpinBox(); self.keep.setRange(0, 10000); self.keep.setSpecialValueText("No trim")
        self.case = QComboBox(); self.case.addItems(["Keep case", "lower", "upper", "title", "sentence"])
        self.number = QCheckBox("Enable numbering")
        self.number.setChecked(True)
        self.number.setStyleSheet("QCheckBox { background-color: rgba(218, 159, 48, 45); border: 1px solid #b78328; border-radius: 5px; padding: 8px; font-weight: bold; }")
        self.mode = QComboBox()
        for label,value in [("Only replace ###", "token"),("Number at beginning", "prefix"),("Number at end", "suffix")]:
            self.mode.addItem(label,value)
        self.mode.setCurrentIndex(0)
        self.start = QSpinBox(); self.start.setRange(-999999,999999); self.start.setValue(1)
        self.step = QSpinBox(); self.step.setRange(-999999,999999); self.step.setValue(1)
        self.pad = QSpinBox(); self.pad.setRange(1,12); self.pad.setValue(3)
        self.ext = QComboBox(); self.ext.addItems(["Keep extension", "lower", "upper", "Set extension", "Remove extension"])
        self.ext_text = QLineEdit(); self.ext_text.setPlaceholderText("e.g. cbz")
        def note(text):
            label = QLabel(text); label.setWordWrap(True)
            label.setStyleSheet("font-size: 12px; margin-bottom: 7px;")
            form.addRow(label)
        form.addRow("Find", self.old)
        form.addRow("Replace with", self.new)
        note("Leave Replace with blank to delete matching text. All matches are replaced.")
        form.addRow(self.regex); form.addRow(self.ignore)
        note("Pattern matching is optional: [0-9]+ matches one or more digits. Leave it off for ordinary text.")
        form.addRow("New file name", self.name)
        form.addRow(self.number)
        note("Leave blank to keep the current name. A new name is set before Find and replace. The extension stays unchanged. Use ### for a number: 001, 002, 003.")
        form.addRow("Remove from beginning", self.cut)
        form.addRow("Keep from beginning", self.keep)
        note("Count characters, including spaces and punctuation. Remove deletes the first N; Keep retains only the first N. The extension is not counted. 0 means no change.")
        form.addRow("Letter case", self.case)
        form.addRow("Add text at beginning", self.prefix)
        form.addRow("Add text at end", self.suffix)
        note("Include a space in the added text if you want a gap. Text at the end goes before the extension.")
        form.addRow("When there is no ###", self.mode)
        form.addRow("First number", self.start)
        form.addRow("Increase each number by", self.step)
        form.addRow("Number of digits", self.pad)
        note("With numbering enabled, ### becomes 001, 002, 003; ## becomes 01, 02, 03. The # location sets the number location and its length sets the digits. Without #, choose beginning/end and the number of digits above.")
        form.addRow("Extension", self.ext)
        form.addRow("New extension", self.ext_text)
        note("An extension is the file type at the end, such as .jpg or .cbr. Leave it unchanged for ordinary renaming.")
        form_layout.addWidget(rename_group)
        help_text = QLabel("Preview makes no changes. Apply renames only after reviewing the proposed names.")
        help_text.setWordWrap(True); form_layout.addWidget(help_text); form_layout.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(controls)
        split.addWidget(scroll)
        right = QWidget(); rl = QVBoxLayout(right)
        self.table = QTableWidget(0,4); self.table.setHorizontalHeaderLabels(["Original name","New name","Status","Folder"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        rl.addWidget(self.table)
        self.details = QLabel("Add files or a folder to begin."); self.details.setWordWrap(True); rl.addWidget(self.details)
        split.addWidget(right); split.setSizes([460,820])
        footer = QHBoxLayout()
        self.force = QCheckBox("Allow overwrite with backup")
        self.preview_button = QPushButton("Refresh preview")
        self.preview_button.clicked.connect(self.refresh_preview)
        self.undo_button = QPushButton("Undo latest")
        self.undo_button.clicked.connect(self.undo_latest)
        self.apply_button = QPushButton("Apply renames")
        self.apply_button.setEnabled(False); self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.force); footer.addStretch(); footer.addWidget(self.preview_button)
        footer.addWidget(self.undo_button); footer.addWidget(self.apply_button); layout.addLayout(footer)
        self.old.setToolTip("Find exact text in the file name, excluding its extension.")
        self.new.setToolTip("Leave this field empty to remove every match.")
        self.cut.setToolTip("Remove the first N characters. Spaces count as one character.")
        self.keep.setToolTip("Keep only the first N characters; discard the rest of the name. Spaces count. The extension is preserved.")
        self.pad.setToolTip("3 digits: 001, 002, 003. 2 digits: 01, 02, 03. Used when there is no # placeholder.")
        self.mode.setToolTip("A # placeholder always decides where the number goes. This choice applies only when the name has no #.")
        self.force.setToolTip("Existing destination files are kept in hidden backups so Undo can restore them.")
        self.regex.setToolTip("Advanced patterns can match changing text. Example: [0-9]+ finds digits; plain Find treats symbols literally.")
        for field in [self.name,self.old,self.new,self.prefix,self.suffix,self.ext_text]:
            field.textChanged.connect(self.invalidate)
        for field in [self.cut,self.keep,self.start,self.step,self.pad]:
            field.valueChanged.connect(self.invalidate)
        for field in [self.order,self.case,self.mode,self.ext]:
            field.currentIndexChanged.connect(self.invalidate)
        for field in [self.recursive,self.regex,self.ignore,self.number,self.force]:
            field.toggled.connect(self.invalidate)
        incomplete = [sid for sid in list_session_ids(self.root) if load_transaction(self.root,sid).status not in ("completed","rolled_back","planned")]
        if incomplete:
            self.details.setText("Interrupted session found. Open History / recovery before applying another batch.")

    def invalidate(self, *_):
        self.preview_revision += 1
        self.renames = []
        self.mode.setEnabled(not any("#" in field.text() for field in (self.name,self.prefix,self.suffix)))
        self.apply_button.setEnabled(False)
        if self.paths:
            self.preview_pending = True
            self.details.setText("Updating preview… No files have been changed.")
            self.preview_timer.start()
        else:
            self.preview_pending = False
            self.preview_timer.stop()
            self.table.setRowCount(0)
            self.details.setText("Add files or a folder to begin.")

    def clear(self):
        self.paths = []; self.preview_sources = []; self.invalidate()

    def add_paths(self, paths):
        self.paths = list(dict.fromkeys(self.paths + [str(Path(p).absolute()) for p in paths]))
        self.invalidate(); self.preview()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self,"Choose files")
        if paths: self.add_paths(paths)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self,"Choose folder")
        if folder: self.add_paths([folder])

    def remove_selected(self):
        selected = {self.preview_sources[i.row()] for i in self.table.selectionModel().selectedRows()}
        if selected:
            self.paths = [str(p) for p in self.preview_sources if p not in selected]
            self.invalidate(); self.preview()

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self,event):
        self.add_paths([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def build_ops(self):
        result=[]
        if self.name.text(): result.append(ops.stem_set_op(self.name.text()))
        if self.old.text():
            result.append(ops.regex_op(self.old.text(),self.new.text(),self.ignore.isChecked()) if self.regex.isChecked()
                          else ops.replace_op(self.old.text(),self.new.text()))
        if self.cut.value(): result.append(ops.cut_op("front",self.cut.value()))
        if self.keep.value(): result.append(ops.cut_op("end",self.keep.value()))
        if self.case.currentIndex(): result.append(ops.case_op(self.case.currentText()))
        prefix,suffix=self.prefix.text(),self.suffix.text()
        if prefix or suffix: result.append(lambda stem,ext,i,n:(prefix+stem+suffix,ext))
        automatic = ops.numbering_op("token",self.start.value(),self.step.value(),self.pad.value())
        explicit = ops.numbering_op(self.mode.currentData(),self.start.value(),self.step.value(),self.pad.value())
        enabled = self.number.isChecked()
        if enabled:
            result.append(explicit)
        if self.ext.currentText() in ("lower","upper"): result.append(ops.ext_case_op(self.ext.currentText()))
        if self.ext.currentText()=="Set extension": result.append(ops.ext_set_op(self.ext_text.text()))
        if self.ext.currentText()=="Remove extension":
            result.append(lambda stem,ext,i,n:(stem,""))
        return result

    def run_task(self,fn,done,preview=False,error=None):
        if self.worker and self.worker.isRunning():
            if preview: self.preview_pending = True
            return
        if not preview:
            self.preview_timer.stop()
            self.centralWidget().setEnabled(False)
            self.details.setText("Working…")
        worker=Worker(fn,self); self.worker=worker
        worker.result.connect(done)
        worker.error.connect(error or self.show_error)
        def finished():
            if not preview: self.centralWidget().setEnabled(True)
            if self.preview_pending and self.paths: self.preview_timer.start()
        worker.finished.connect(finished)
        worker.start()

    def refresh_preview(self):
        self.cached_selection = None
        self.invalidate()
        self.preview()

    def preview(self):
        self.preview_timer.stop()
        if self.worker and self.worker.isRunning():
            self.preview_pending = True
            return
        self.preview_pending = False
        revision=self.preview_revision
        try: pipeline=self.build_ops()
        except Exception as exc:
            self.apply_button.setEnabled(False)
            self.details.setText("Cannot preview: " + str(exc))
            return
        paths=list(self.paths); recursive=self.recursive.isChecked(); order=self.order.currentText(); force=self.force.isChecked()
        selection=(tuple(paths),recursive,order)
        cached=list(self.cached_sources) if selection==self.cached_selection and self.cached_sources is not None else None
        def compute():
            sources=cached if cached is not None else order_paths(expand_paths(paths,recursive),order)
            renames,issues=plan(sources,pipeline)
            return sources,renames,issues+validate(renames,force)
        def done(result):
            if revision!=self.preview_revision:
                self.preview_pending=bool(self.paths)
                return
            self.cached_selection=selection
            self.cached_sources=list(result[0])
            self.display_preview(result)
        def error(message):
            if revision==self.preview_revision:
                self.apply_button.setEnabled(False)
                self.details.setText("Cannot preview: " + message)
        self.run_task(compute,done,preview=True,error=error)

    def display_preview(self,result):
        sources,renames,issues=result; self.preview_sources=sources; self.renames=renames
        changes={r.src:r.dst for r in renames}; errors=has_errors(issues)
        self.table.setRowCount(len(sources))
        for row,path in enumerate(sources):
            dst=changes.get(path,path)
            relevant=[i for i in issues if str(path) in i.message or str(dst) in i.message]
            status="Blocked" if errors and path in changes else ("Backup overwrite" if relevant else ("Ready" if path in changes else "Unchanged"))
            for column,value in enumerate([path.name,dst.name,status,str(path.parent)]):
                item=QTableWidgetItem(value)
                if errors and path in changes: item.setForeground(QColor("#d64f4f"))
                elif relevant: item.setForeground(QColor("#bf8b21"))
                item.setToolTip(summary(relevant) or str(path)); self.table.setItem(row,column,item)
        self.details.setText(summary(issues) if issues else f"{len(sources)} files · {len(renames)} changes ready. No files changed by preview.")
        self.apply_button.setEnabled(bool(renames) and not errors)

    def apply(self):
        count=len(self.renames)
        if QMessageBox.question(self,"Apply renames",f"Rename {count} files using the reviewed preview?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        renames=list(self.renames); force=self.force.isChecked()
        def change():
            tx=create_transaction(self.root); execute(tx,renames,force); return tx
        def done(tx):
            mapping={r.src:r.dst for r in renames}
            self.paths=[str(mapping.get(p,p)) for p in self.preview_sources]
            self.invalidate(); self.details.setText(f"Renamed {count} files. Undo available. Session: {tx.id}")
        self.run_task(change,done)

    def undo_latest(self):
        try: sid=newest_session(self.root)
        except Exception as exc:self.show_error(str(exc));return
        self.undo_session(sid)

    def undo_session(self,sid):
        if QMessageBox.question(self,"Undo / redo",f"Reverse completed session {sid}?\nNewer or changed files will block this action.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.run_task(lambda:load_transaction(self.root,sid).undo(),lambda tx:self.after_history(f"Reversed session. Undo latest now redoes it. New session: {tx.id}"))

    def after_history(self,message):
        self.clear();self.details.setText(message)

    def history(self):
        dialog=QDialog(self);dialog.setWindowTitle("History and interrupted session recovery");dialog.resize(740,400)
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel("Undo a completed session, or restore files from an interrupted batch."))
        listing=QListWidget();layout.addWidget(listing)
        for sid in reversed(list_session_ids(self.root)):
            tx=load_transaction(self.root,sid);item=QListWidgetItem(f"{sid}    {tx.status}    {len(tx.moves)} moves")
            item.setData(Qt.ItemDataRole.UserRole,(sid,tx.status));listing.addItem(item)
        buttons=QHBoxLayout();undo=QPushButton("Undo / redo selected");recover=QPushButton("Recover selected");close=QPushButton("Close")
        for button in [undo,recover,close]:buttons.addWidget(button)
        layout.addLayout(buttons);close.clicked.connect(dialog.reject)
        def selected(recovery=False):
            item=listing.currentItem()
            if not item:return
            sid,status=item.data(Qt.ItemDataRole.UserRole)
            if recovery:
                if status in ("completed","rolled_back","planned"):self.show_error("This session does not need recovery.");return
                if QMessageBox.question(dialog,"Recover interrupted batch","Restore this batch to its original state?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
                dialog.accept()
                self.run_task(lambda:load_transaction(self.root,sid).recover(),lambda tx:self.after_history("Recovery completed; original names restored."))
            else:
                if status!="completed":self.show_error("Only completed sessions can be undone.");return
                dialog.accept();self.undo_session(sid)
        undo.clicked.connect(lambda:selected());recover.clicked.connect(lambda:selected(True));dialog.exec()

    def guide(self):
        QMessageBox.information(self,"How to use Ed's Renamer",
            "1. Add files or folders, or drag them into the window.\n"
            "2. Set the name changes you want. Leave other controls alone.\n"
            "3. The preview updates as you type. Nothing is changed.\n"
            "4. Review the list, then Apply renames.\n\n"
            "Find and replace: leaving Replace with empty deletes all matches.\n"
            "Characters: letters, spaces, punctuation and digits each count. The extension is excluded.\n"
            "Keep from beginning: retain the first N characters and remove the rest.\n"
            "Remove from beginning: remove the first N characters and keep the rest.\n"
            "Numbering: With numbering enabled, ### becomes 001, 002, 003; ## becomes 01, 02, 03.\n"
            "With no #, select Number at beginning or Number at end and choose digits.\n\n"
            "Undo latest reverses the newest completed batch; undo again to redo.\n"
            "History / recovery can restore an interrupted batch. Changed or occupied files block unsafe moves.\n"
            "Help > Add to application menu creates an optional shortcut and icon. Keep the downloaded executable in place.")

    def install_shortcut(self):
        try:
            from .desktop import install_shortcut
            install_shortcut(asset_path())
            QMessageBox.information(self,"Application menu","Ed's Renamer is now in your application menu. Keep this executable in its current location.")
        except Exception as exc:
            QMessageBox.warning(self,"Application menu",str(exc))

    def show_error(self,message):
        self.apply_button.setEnabled(False)
        self.details.setText(message)
        QMessageBox.warning(self,"Ed's Renamer",message)

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,"Ed's Renamer","Please wait for the current operation to finish.");event.ignore()
        else:
            self.preview_timer.stop()
            self.preview_pending = False
            event.accept()


def main():
    app=QApplication(sys.argv)
    app.setApplicationName("Ed's Renamer")
    app.setDesktopFileName("filehash")
    app.setWindowIcon(QIcon(str(asset_path())))
    if "--self-test" in sys.argv:
        from tempfile import TemporaryDirectory
        from .engine import Rename
        with TemporaryDirectory() as directory:
            base=Path(directory); source=base/"sample.txt"; source.write_text("sample")
            import time
            from PySide6.QtTest import QTest
            window=Window(base/"state"); window.paths=[str(source)]
            def wait_for(text):
                deadline=time.monotonic()+10
                while not (window.table.rowCount()==1 and window.table.item(0,1).text()==text):
                    app.processEvents();QTest.qWait(20)
                    if time.monotonic()>deadline: raise AssertionError("Bundled live preview failed")
                while window.worker and window.worker.isRunning():
                    app.processEvents();window.worker.wait(10)
                app.processEvents()
            window.preview();wait_for("sample.txt")
            window.old.setText("sample")
            assert window.table.rowCount()==1, "Preview disappeared while typing Find"
            assert window.old.isEnabled(), "Preview blocked editing"
            window.new.setText("changed")
            assert window.table.rowCount()==1, "Preview disappeared while typing Replace"
            wait_for("changed.txt")
            window.old.clear();window.new.clear();window.name.setText("test ###")
            window.number.setChecked(True);wait_for("test 001.txt")
            assert window.apply_button.isEnabled()
            tx=create_transaction(base/"state"); execute(tx,window.renames)
            undo=tx.undo(); assert source.read_text()=="sample"
            undo.undo(); assert (base/"test 001.txt").read_text()=="sample"
            window.close()
            print("Ed's Renamer 1.0.3: bundled live Find/Replace preview, numbering and rename/undo/redo passed")

        return 0
    window=Window();window.show()
    return app.exec()

if __name__=="__main__":sys.exit(main())
