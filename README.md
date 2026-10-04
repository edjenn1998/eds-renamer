# Ed's Renamer

A Linux desktop app for bulk renaming music, photos, comics, and other files.
Adjust the names, review a preview, then apply the changes. The blue document
icon with three # symbols represents the numbering feature.

## Download and open

Download the single **EdsRenamer-1.0.3-x86_64** executable. No archive extraction,
Python installation, or launcher script is required.

1. Put the file somewhere permanent.
2. If necessary, right-click it, open Properties > Permissions, and enable
   **Is executable / Allow executing file as program**.
3. Double-click it to open Ed's Renamer.

Linux downloads do not always preserve the executable permission. A computer
policy or filesystem mounted with `noexec` can also prevent launching it.
The alternative terminal command is `chmod +x EdsRenamer-1.0.3-x86_64`, then
`./EdsRenamer-1.0.3-x86_64`.

Targets **x86-64 Linux with glibc 2.39 or newer**, such as Ubuntu 24.04+ and
current Arch/CachyOS. It bundles Python and Qt, but requires a working desktop
and the usual Qt system libraries. This release is not a Windows/macOS binary.

The approved icon appears in the app and taskbar. For a launcher with the custom
icon, choose **Help > Add to application menu**. Keep the executable in place
after adding the shortcut. File managers may still show a generic icon for a
raw Linux executable; that behavior is controlled by the desktop environment.

The default numbering mode replaces # placeholders only; it does not add numbers to ordinary names without them. Select beginning/end explicitly if desired.

## Using the app

- **Find / Replace with:** replace matching text. Leave Replace with empty to
  delete the matching text. This operates on the name without its extension.
- **New file name:** leave blank to keep the current name. A supplied name
  replaces the original before Find and replace.
- **Remove from beginning:** remove the first N characters; keep the rest.
- **Keep from beginning:** retain the first N characters; remove the rest.
  Letters, spaces, punctuation and digits each count; the extension is excluded.
  Zero means no change. Remove runs before Keep when both are set.
- **Add text at beginning / end:** add text around the retained name. Include
  any space you want between that text and the existing name.
- **Enable numbering (on by default, highlighted below New file name):** `###` becomes `001`, `002`, `003`; `##` becomes `01`,
  `02`, `03`. The placeholder location decides where numbers appear and its
  length decides the digit count. Only the first # sequence is replaced. Existing names containing a literal # stay unchanged when numbering is off.
- **When there is no ###:** choose beginning or end and the desired digit count.
  Enable the numbering checkbox to use either # placeholders or beginning/end numbering.
- **Extension:** keep it unchanged unless deliberately changing the suffix,
  such as `.jpg` or `.cbr`. Renaming an extension does not convert a file.
- **Advanced pattern matching:** optional regular expressions; for example,
  `[0-9]+` matches one or more digits. Ordinary Find treats punctuation literally.

Choose files/folders or drag them into the window. The preview updates automatically as you type, with a short pause to avoid interrupting your typing. Existing rows remain visible while updating. **Refresh preview** also rescans selected folders. Preview writes nothing. Errors block **Apply renames**.
Apply requires confirmation. The window remains responsive during operations.
**Help > How to use Ed's Renamer** contains a built-in guide.

**Undo latest** reverses the newest completed transaction; undoing that action
redoes it. **History / recovery** provides explicit session selection and
restores interrupted batches to their original state.

## Safety and limitations

The engine enforces validation for GUI, CLI and direct API callers. Duplicate
sources/destinations, aliased duplicate paths, missing sources or parents,
invalid names, real directory renames and journal-storage renames are blocked.

Linux `renameat2(RENAME_NOREPLACE)` refuses existing destinations at the syscall
boundary, including entries appearing after validation. Unsupported platforms
or filesystems fail rather than falling back to an overwriting rename.
Swaps/cycles use hidden temporary names. Opt-in overwrite moves existing files
to hidden journaled backups rather than destroying them. Managed `.renamer-*`
entries are excluded from scans and reserved from explicit renaming.

A complete move plan and identities are durably saved before the first move.
Each syscall has a pending record. Caught errors trigger rollback. Recovery can
reconcile a crash before/after a move or during rollback. Ambiguous states,
occupied originals, or changed files cause a safe stop; resolve the conflict
before retrying. Incomplete sessions block further apply/undo. Only completed
sessions are undoable. Legacy journals remain readable but automatic undo is
refused without recorded identities.

This is a recoverable sequence of moves, not a filesystem-wide atomic batch.
Files may be visible under temporary names while it runs. Identities use device,
inode, mode, size and nanosecond modification time, not content hashes. Avoid
editing the same batch during operations. A lock serializes users of the same
state root; different roots do not share a lock. Cross-filesystem moves are
refused. Some case-insensitive aliases are caught at execution and rolled back.
Network durability depends on the server. Normal backups remain necessary.

For compatibility, existing rename history remains in `~/.renamer/sessions/`.
The internal Python package name remains `renamer`; Ed's Renamer is the public app
name. No old journals or earlier app downloads are deleted.

## Source and development

The source archive is separate from the one-file end-user download. Python
3.10+ is required. From the extracted source directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python renamer_gui.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
```

On Debian/Ubuntu, venv creation may require `python3-venv`.

Build the single-file app:

```bash
source .venv/bin/activate
./build.sh
```

The output is `release/EdsRenamer-1.0.3-x86_64`. PyInstaller bundles Python, Qt, the icon
and all application modules. The executable includes `--self-test`, which checks
GUI preview and rename/undo/redo using disposable files. The build inherits its
host's Linux compatibility requirements; build on an older supported distro
when broader compatibility is needed.

100 tests pass, including the user's counted-character examples, blank replacement
deletion, collision blocking, undo/redo, interruptions during apply/rollback,
overwrite backup restoration and GUI icon/numbering controls.

CLI examples:

```bash
python3 rename.py rename photos/ --name 'File###' --number  # preview
python3 rename.py rename photos/ --name 'File###' --number --apply
python3 rename.py sessions
python3 rename.py undo -y
python3 rename.py recover --session SESSION_ID
```

Place `--home STATE_DIR` before the subcommand to override state storage.
See CHANGELOG.md for implementation details.
