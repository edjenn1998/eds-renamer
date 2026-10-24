"""Qt desktop frontend. All filesystem changes go through the core engine."""
from pathlib import Path
import sys
import csv
import io
import json
import threading
from collections import defaultdict
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QItemSelectionModel
from PySide6.QtGui import QColor, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QCheckBox, QComboBox, QSpinBox, QFormLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QSplitter, QAbstractItemView, QDialog, QListWidget, QListWidgetItem,
    QScrollArea, QProgressBar, QDialogButtonBox, QPlainTextEdit,
)
from . import operations as ops
from .engine import expand_paths, order_paths, plan, validate, has_errors, execute, summary, snapshot
from .session import DEFAULT_ROOT, Transaction, create_transaction, load_transaction, inspect_sessions, newest_session, check_pending
from .engine import ValidationIssue
from .version import VERSION


def asset_path():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "assets" / "filehash.png"


class Worker(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, str)
    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn
        self.cancel = threading.Event()
        self.succeeded = False
    def run(self):
        try:
            result = self.fn(self.cancel, self.progress.emit)
            self.succeeded = True
            self.result.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class Window(QMainWindow):
    def __init__(self, root=DEFAULT_ROOT, persist=None):
        super().__init__()
        self.root = Path(root)
        self.paths = []
        self.renames = []
        self.preview_sources = []
        self.worker = None
        self.worker_is_preview = False
        self.expected_state = None
        self.preview_valid = False
        self.close_requested = False
        self.settings = QSettings("edjenn1998", "EdsRenamer")
        self.persist = Path(root) == DEFAULT_ROOT if persist is None else persist
        self.preview_revision = 0
        self.preview_pending = False
        self.cached_selection = None
        self.cached_sources = None
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(180)
        self.preview_timer.timeout.connect(self.preview)
        self.setWindowTitle(f"Ed's Renamer {VERSION} — preview before you rename")
        self.setWindowIcon(QIcon(str(asset_path())))
        self.resize(1280, 820)
        self.setMinimumSize(980, 680)
        self.setAcceptDrops(True)
        help_menu = self.menuBar().addMenu("Help")
        guide = QAction("How to use Ed's Renamer", self); guide.triggered.connect(self.guide); help_menu.addAction(guide)
        shortcut = QAction("Add to application menu", self); shortcut.triggered.connect(self.install_shortcut); help_menu.addAction(shortcut)
        about = QAction("About Ed's Renamer", self)
        about.triggered.connect(lambda: QMessageBox.information(self,"About Ed's Renamer",f"Ed's Renamer {VERSION}\nBulk file renaming with preview, undo and recovery.\nLinux x86-64 edition."))
        help_menu.addAction(about)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("Ed's Renamer")
        title.setStyleSheet("font-size: 28px; font-weight: 600; margin: 8px 0;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Choose files, adjust their names, then review the preview."))
        tools = QHBoxLayout()
        self.tool_buttons = []
        for text, fn in [("Add files…", self.add_files), ("Add folder…", self.add_folder),
                         ("Remove selected", self.remove_selected), ("Clear", self.clear),
                         ("History / recovery…", self.history)]:
            button = QPushButton(text); button.clicked.connect(fn); tools.addWidget(button)
            self.tool_buttons.append(button)
        for text, fn in [("Reset changes", self.reset_options), ("Save preset…", self.save_preset),
                         ("Load preset…", self.load_preset)]:
            button = QPushButton(text); button.clicked.connect(fn); tools.addWidget(button)
            self.tool_buttons.append(button)
        tools.addStretch(); layout.addLayout(tools)
        split = QSplitter(); layout.addWidget(split, 1)
        self.split = split
        controls = QWidget(); controls.setMinimumWidth(440); form_layout = QVBoxLayout(controls)
        selection = QGroupBox("Selection"); sf = QFormLayout(selection)
        self.recursive = QCheckBox("Include subfolders")
        self.order = QComboBox(); self.order.addItems(["name", "natural", "mtime", "size", "random"])
        self.order.setToolTip("Natural sorts page2 before page10. Name preserves alphabetical ordering.")
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
        for field in [self.name, self.old, self.new, self.prefix, self.suffix, self.ext_text]:
            field.setMaxLength(4096)
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
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        split.addWidget(right); split.setSizes([460,820])
        footer = QHBoxLayout()
        self.force = QCheckBox("Allow overwrite with backup")
        self.preview_button = QPushButton("Refresh preview")
        self.preview_button.clicked.connect(self.refresh_preview)
        self.undo_button = QPushButton("Undo latest")
        self.undo_button.clicked.connect(self.undo_latest)
        self.redo_button = QPushButton("Redo last undo")
        self.redo_button.clicked.connect(self.redo_latest)
        self.export_button = QPushButton("Export preview…")
        self.export_button.clicked.connect(self.export_preview)
        self.export_button.setEnabled(False)
        self.apply_button = QPushButton("Apply renames")
        self.apply_button.setEnabled(False); self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.force); footer.addStretch(); footer.addWidget(self.preview_button)
        footer.addWidget(self.export_button); footer.addWidget(self.undo_button)
        footer.addWidget(self.redo_button); footer.addWidget(self.apply_button); layout.addLayout(footer)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.cancel_button = QPushButton("Cancel"); self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_current)
        progress_row.addWidget(self.progress, 1); progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)
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
        records = inspect_sessions(self.root)
        incomplete = [sid for sid, status, _, _, _ in records if status not in ("completed","rolled_back","planned")]
        if incomplete:
            self.details.setText("History needs attention: open History / recovery to inspect interrupted or unreadable sessions.")
        self.update_history_buttons()
        if self.persist:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)

    def option_widgets(self):
        return {name: getattr(self, name) for name in (
            "name", "old", "new", "prefix", "suffix", "ext_text", "recursive", "regex",
            "ignore", "number", "cut", "keep", "start", "step", "pad", "order", "case", "mode", "ext")}

    def option_values(self):
        values = {}
        for name, widget in self.option_widgets().items():
            if isinstance(widget, QLineEdit): values[name] = widget.text()
            elif isinstance(widget, QCheckBox): values[name] = widget.isChecked()
            elif isinstance(widget, QSpinBox): values[name] = widget.value()
            else: values[name] = widget.currentIndex()
        return values

    def set_options(self, values):
        widgets = self.option_widgets()
        if not isinstance(values, dict) or set(values) != set(widgets):
            raise ValueError("Preset has missing or unsupported settings")
        for name, value in values.items():
            widget = widgets[name]
            if isinstance(widget, QLineEdit):
                valid = isinstance(value, str) and len(value) <= widget.maxLength()
            elif isinstance(widget, QCheckBox):
                valid = type(value) is bool
            elif isinstance(widget, QSpinBox):
                valid = type(value) is int and widget.minimum() <= value <= widget.maximum()
            else:
                valid = type(value) is int and 0 <= value < widget.count()
            if not valid:
                raise ValueError(f"Invalid preset setting: {name}")
        for name, widget in widgets.items():
            widget.blockSignals(True)
            try:
                value = values[name]
                if isinstance(widget, QLineEdit): widget.setText(value)
                elif isinstance(widget, QCheckBox): widget.setChecked(value)
                elif isinstance(widget, QSpinBox): widget.setValue(value)
                else: widget.setCurrentIndex(value)
            finally:
                widget.blockSignals(False)
        self.force.setChecked(False)
        self.invalidate()

    def reset_options(self):
        values = {name: "" for name in ("name", "old", "new", "prefix", "suffix", "ext_text")}
        values.update({name: False for name in ("recursive", "regex", "ignore")})
        values.update(number=True, cut=0, keep=0, start=1, step=1, pad=3, order=0, case=0, mode=0, ext=0)
        self.set_options(values)

    def save_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save rename preset", "rename-preset.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps({"version": 1, "options": self.option_values()}, indent=2) + "\n", encoding="utf-8")
                self.details.setText(f"Preset saved: {path}")
            except OSError as exc:
                self.show_error(str(exc))

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load rename preset", "", "JSON (*.json)")
        if path:
            try:
                if Path(path).stat().st_size > 128 * 1024:
                    raise ValueError("Preset exceeds 128 KiB")
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("version") != 1:
                    raise ValueError("Unsupported preset format")
                self.set_options(data["options"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.show_error(f"Cannot load preset: {exc}")

    def preview_csv(self):
        out = io.StringIO(newline="")
        writer = csv.writer(out)
        writer.writerow(["Original name", "New name", "Status", "Folder", "Details"])
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text() for col in range(4)]
            values.append(self.table.item(row, 2).toolTip())
            writer.writerow(["'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
        return out.getvalue()

    def export_preview(self):
        if not self.export_button.isEnabled():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export reviewed preview", "rename-preview.csv", "CSV (*.csv)")
        if path:
            try:
                Path(path).write_text(self.preview_csv(), encoding="utf-8-sig", newline="")
                self.details.setText(f"Preview exported: {path}. No files renamed.")
            except OSError as exc:
                self.show_error(str(exc))

    def invalidate(self, *_):
        self.preview_revision += 1
        self.renames = []
        self.expected_state = None
        self.preview_valid = False
        self.export_button.setEnabled(False)
        if self.worker and self.worker_is_preview:
            self.worker.cancel.set()
        self.mode.setEnabled(not self.number.isChecked() or not any("#" in field.text() for field in (self.name,self.prefix,self.suffix)))
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
        if self.worker and not self.worker_is_preview:
            return
        self.paths = list(dict.fromkeys(self.paths + [str(Path(p).absolute()) for p in paths]))
        self.invalidate(); self.preview()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self,"Choose files")
        if paths: self.add_paths(paths)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self,"Choose folder")
        if folder: self.add_paths([folder])

    def remove_selected(self):
        if self.worker and not self.worker_is_preview:
            return
        selected = {self.preview_sources[i.row()] for i in self.table.selectionModel().selectedRows()}
        if selected:
            self.paths = [str(p) for p in self.preview_sources if p not in selected]
            self.invalidate(); self.preview()

    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and not (self.worker and not self.worker_is_preview): event.acceptProposedAction()

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
        if self.worker:
            if preview: self.preview_pending = True
            return
        if not preview:
            self.preview_timer.stop()
            self.set_editing(False)
            self.details.setText("Working…")
        worker=Worker(fn,self); self.worker=worker
        self.undo_button.setEnabled(False); self.redo_button.setEnabled(False)
        self.tool_buttons[4].setEnabled(False)
        self.worker_is_preview = preview
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        worker.result.connect(done)
        worker.error.connect(error or self.show_error)
        worker.progress.connect(self.update_progress)
        def finished():
            if self.worker is not worker:
                return
            self.worker = None
            worker.deleteLater()
            self.cancel_button.setEnabled(False)
            self.progress.setRange(0, 100); self.progress.setValue(100)
            self.progress.setFormat("Preview ready" if preview and worker.succeeded else "Finished" if worker.succeeded else "Stopped")
            if not preview:
                self.set_editing(True)
            self.tool_buttons[4].setEnabled(True)
            self.update_history_buttons()
            self.apply_button.setEnabled(bool(self.renames) and self.preview_valid and not self.preview_pending)
            if self.close_requested:
                QTimer.singleShot(0, self.close)
                return
            if self.preview_pending and self.paths: self.preview_timer.start()
        worker.finished.connect(finished)
        worker.start()

    def set_editing(self, enabled):
        for widget in self.tool_buttons + [self.split, self.force, self.preview_button,
                                          self.undo_button, self.redo_button, self.apply_button, self.export_button]:
            widget.setEnabled(enabled)
        if enabled:
            self.apply_button.setEnabled(bool(self.renames) and self.preview_valid)
            self.export_button.setEnabled(self.preview_valid)

    def cancel_current(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel_button.setEnabled(False)
            self.details.setText("Stopping preview…" if self.worker_is_preview else
                                 "Cancelling at the next safe checkpoint; rollback may take a moment…")

    def update_progress(self, current, total, message):
        if total:
            self.progress.setRange(0, total); self.progress.setValue(current)
        else:
            self.progress.setRange(0, 0)
        self.progress.setFormat(message + (f" {current}/{total}" if total else f" {current}"))

    def refresh_preview(self):
        self.cached_selection = None
        self.invalidate()
        self.preview()

    def preview(self):
        self.preview_timer.stop()
        if self.worker:
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
        def compute(cancel, progress):
            sources=cached if cached is not None else order_paths(expand_paths(paths,recursive,cancel,progress,[self.root]),order)
            renames,issues=plan(sources,pipeline,cancel,progress)
            expected = snapshot(renames)
            issues += validate(renames,force,cancel)
            try:
                check_pending(self.root)
            except (OSError, ValueError, RuntimeError) as exc:
                issues.append(ValidationIssue("error", str(exc)))
            if snapshot(renames) != expected:
                raise ValueError("Files changed while previewing; refresh preview.")
            return sources,renames,issues,expected
        def done(result):
            if revision!=self.preview_revision:
                self.preview_pending=bool(self.paths)
                return
            self.cached_selection=selection
            self.cached_sources=list(result[0])
            self.expected_state = result[3]
            self.display_preview(result[:3])
        def error(message):
            if revision==self.preview_revision:
                self.apply_button.setEnabled(False)
                self.details.setText("Cannot preview: " + message)
        self.run_task(compute,done,preview=True,error=error)

    def display_preview(self,result):
        selected = {self.preview_sources[index.row()] for index in self.table.selectionModel().selectedRows()
                    if index.row() < len(self.preview_sources)}
        sources,renames,issues=result; self.preview_sources=sources; self.renames=renames
        changes={r.src:r.dst for r in renames}; errors=has_errors(issues)
        indexed = defaultdict(list)
        general = []
        for issue in issues:
            if issue.paths:
                for path in issue.paths:
                    if len(indexed[path]) < 8:
                        indexed[path].append(issue)
            else:
                if len(general) < 8:
                    general.append(issue)
        self.preview_valid = not errors
        self.export_button.setEnabled(True)
        self.table.setRowCount(len(sources))
        self.table.clearSelection()
        for row,path in enumerate(sources):
            dst=changes.get(path,path)
            relevant = list(dict.fromkeys(indexed[str(path)] + indexed[str(dst)] + general))
            status="Blocked" if errors and path in changes else ("Backup overwrite" if relevant else ("Ready" if path in changes else "Unchanged"))
            for column,value in enumerate([path.name,dst.name,status,str(path.parent)]):
                item=QTableWidgetItem(value)
                if errors and path in changes: item.setForeground(QColor("#d64f4f"))
                elif relevant: item.setForeground(QColor("#bf8b21"))
                item.setToolTip(summary(relevant) or str(path)); self.table.setItem(row,column,item)
            if path in selected:
                self.table.selectionModel().select(self.table.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        text = summary(issues[:20])
        if len(issues) > 20:
            text += f"\n… {len(issues) - 20} more issues. Export the preview to review all files."
        self.details.setText(text if issues else f"{len(sources)} files · {len(renames)} changes ready. No files changed by preview.")
        self.apply_button.setEnabled(bool(renames) and not errors and self.worker is None)

    def apply(self):
        if self.worker or not self.preview_valid or not self.renames or self.preview_pending:
            return
        count=len(self.renames)
        revision = self.preview_revision
        renames=list(self.renames); force=self.force.isChecked(); expected=self.expected_state
        if QMessageBox.question(self,"Apply renames",f"Rename {count} files using the reviewed preview?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        if revision != self.preview_revision or self.worker:
            self.details.setText("Preview changed; review it again before applying.")
            return
        def change(cancel, progress):
            tx=create_transaction(self.root); execute(tx,renames,force,expected,cancel,progress); return tx
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
        if self.worker:
            return
        if QMessageBox.question(self,"Undo / redo",f"Reverse completed session {sid}?\nNewer or changed files will block this action.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        self.run_task(lambda c,p:load_transaction(self.root,sid).undo(c,p),lambda tx:self.after_history(f"Reversed session. Undo latest now redoes it. New session: {tx.id}"))

    def update_history_buttons(self):
        records = inspect_sessions(self.root)
        completed = [r for r in records if r[1] == "completed"]
        self.undo_button.setEnabled(bool(completed))
        self.redo_button.setEnabled(bool(completed and completed[-1][3] == "undo"))

    def redo_latest(self):
        records = [r for r in inspect_sessions(self.root) if r[1] == "completed"]
        if records and records[-1][3] == "undo":
            self.undo_session(records[-1][0])

    def after_history(self,message):
        self.clear();self.details.setText(message)

    def history(self):
        dialog=QDialog(self);dialog.setWindowTitle("History and interrupted session recovery");dialog.resize(740,400)
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel("Undo a completed session, or restore files from an interrupted batch."))
        location = QLabel(f"Journals: {self.root / 'sessions'}")
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(location)
        listing=QListWidget();layout.addWidget(listing)
        for sid, status, count, action, error in reversed(inspect_sessions(self.root)):
            item=QListWidgetItem(f"{sid}    {status}    {action}    {count} moves")
            item.setToolTip(error or sid)
            item.setData(Qt.ItemDataRole.UserRole,(sid,status));listing.addItem(item)
        buttons=QHBoxLayout();undo=QPushButton("Undo / redo selected");recover=QPushButton("Recover selected");close=QPushButton("Close")
        view = QPushButton("View journal…")
        for button in [undo,recover,view,close]:buttons.addWidget(button)
        layout.addLayout(buttons);close.clicked.connect(dialog.reject)
        def selected(recovery=False):
            item=listing.currentItem()
            if not item:return
            sid,status=item.data(Qt.ItemDataRole.UserRole)
            if recovery:
                if status == "unreadable":
                    self.show_error(item.toolTip());return
                if status in ("completed","rolled_back","planned"):self.show_error("This session does not need recovery.");return
                if QMessageBox.question(dialog,"Recover interrupted batch","Restore this batch to its original state?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
                dialog.accept()
                self.run_task(lambda c,p:load_transaction(self.root,sid).recover(c,p),lambda tx:self.after_history("Recovery completed; original names restored."))
            else:
                if status!="completed":self.show_error("Only completed sessions can be undone.");return
                dialog.accept();self.undo_session(sid)
        def show_journal():
            item = listing.currentItem()
            if not item:
                return
            sid, _ = item.data(Qt.ItemDataRole.UserRole)
            try:
                path = Transaction(sid, self.root).path()
                if path.stat().st_size > 8 * 1024**2:
                    raise ValueError(f"Journal is too large for this viewer; inspect {path} externally")
                content = path.read_text(encoding="utf-8", errors="replace")
                viewer = QDialog(dialog); viewer.setWindowTitle(f"Journal {sid} (read-only)"); viewer.resize(800, 520)
                vl = QVBoxLayout(viewer); text = QPlainTextEdit(content); text.setReadOnly(True); vl.addWidget(text)
                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
                buttons.rejected.connect(viewer.reject); vl.addWidget(buttons); viewer.exec()
            except (OSError, ValueError) as exc:
                self.show_error(str(exc))
        undo.clicked.connect(lambda:selected());recover.clicked.connect(lambda:selected(True))
        view.clicked.connect(show_journal); dialog.exec()

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
        self.expected_state = None
        self.preview_valid = False
        if self.worker and self.worker.cancel.is_set():
            self.cached_selection = None
            return
        QMessageBox.warning(self,"Ed's Renamer",message)

    def closeEvent(self,event):
        if self.worker:
            self.close_requested = True
            self.preview_timer.stop(); self.preview_pending = False
            if self.worker_is_preview:
                self.worker.cancel.set()
            self.details.setText("Closing after the current operation reaches a safe stopping point…")
            event.ignore()
        else:
            self.preview_timer.stop()
            self.preview_pending = False
            if self.persist:
                self.settings.setValue("geometry", self.saveGeometry())
            event.accept()


def main():
    if "--version" in sys.argv:
        print(f"Ed's Renamer {VERSION}")
        return 0
    app=QApplication(sys.argv)
    app.setApplicationName("Ed's Renamer")
    app.setDesktopFileName("filehash")
    app.setWindowIcon(QIcon(str(asset_path())))
    if "--self-test" in sys.argv:
        from tempfile import TemporaryDirectory
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
                while window.worker:
                    app.processEvents()
                    if window.worker: window.worker.wait(10)
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
            pattern = ops.regex_op(r"(test) (\d+)", r"\1-\2")
            assert pattern("test 001", ".txt", 0, 1) == ("test-001", ".txt")
            print(f"Ed's Renamer {VERSION}: bundled live Find/Replace preview, numbering and rename/undo/redo passed")

        return 0
    window=Window();window.show()
    return app.exec()

if __name__=="__main__":sys.exit(main())
