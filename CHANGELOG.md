# Desktop edition changes

- engine.py: enforce validation in execute; detect aliased duplicate paths;
  protect journal storage; prohibit direct directory renaming; implement Linux
  no-overwrite moves; write complete move plans and pending moves; preflight
  undo; recover interrupted forward and rollback moves; keep temporary names
  short enough for long source filenames; sync directory updates.
- session.py: version-2 durable journals with identities, plans and pending moves;
  guarded undo/recovery; only completed transactions selected for undo; root
  locking; validate session IDs; randomize IDs across processes; retain legacy
  journal readability while refusing unsafe legacy undo.
- cli.py: recovery command; status in history; handle general filesystem errors.
- operations.py: fix extension removal, which previously kept the full filename.
- gui.py and renamer_gui.py: Qt frontend, background operations, selection,
  drag/drop, filename preview, blocking errors, backed-up overwrite opt-in,
  confirmations, undo/redo, and history/recovery.
- launch.sh/install-desktop.sh: bundled executable launcher, Python fallback,
  and optional application-menu entry.
- tests: add adversarial backend and GUI integration coverage. Update two older
  tests to match intentionally safer session selection and actual suffix removal.

No changes to the original uploaded archives. This is a separate desktop edition.

# Ed's Renamer 1.0.0

- Adopted Ed's Renamer as the public name and embedded the approved blue ### document icon.
- Replaced programmer-facing labels with plain language, added generic field
  placeholders, persistent explanatory notes and hover help.
- Made blank-replacement deletion explicit and moved Find and replace to the
  top of the controls. The existing operation order remains unchanged.
- Explained character counting, preserved extensions, numbering placement,
  placeholder digit counts and fallback numbering. Disabled fallback location
  when editable fields include a # placeholder.
- Added a built-in usage guide and optional application-menu integration.
- Delivered a single standalone Linux executable and a separate source archive.
- Added four GUI regression tests for deletion, character-count workflows,
  branding/icon and numbering placement; 95 tests now pass (including optional menu integration).

# Ed's Renamer 1.0.1

- Keep preview rows visible during edits; update previews automatically after a
  short typing pause. Preview computation leaves editing controls enabled.
- Cache file selection during edits and reject obsolete worker results so stale
  previews cannot enable Apply. Refresh preview explicitly rescans folders.
- Replace # placeholders automatically without requiring the numbering checkbox.
  The checkbox now enables adding numbers when no placeholder exists.
- Invalid patterns report inline without repeated popup dialogs while typing.
- Preserve existing literal # characters in comic filenames when no numbering
  template is requested. Five additional GUI regression tests; 100 tests pass.

# Ed's Renamer 1.0.2

- Keep live preview visible while editing, including Find and Replace fields.
- Retain the explicit Enable numbering checkbox.
- Show 1.0.2 in the window title and use a distinct downloadable filename.
- Expand the executable's own self-test to verify that rows remain visible while
  typing and live Find/Replace results update, plus numbering and undo/redo.

# Ed's Renamer 1.0.3

- Rename the app and application-menu entry to Ed's Renamer.
- Enable numbering by default and move its checkbox directly beneath New file name.
- Highlight the numbering control with a subtle amber background and bold label.
- Default to placeholder-only numbering so ordinary names without # are not
  numbered unless beginning/end numbering is deliberately selected.
- Preserve the live preview and transaction safety behavior.
