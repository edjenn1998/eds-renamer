# Implemented architecture

Pure filename operations -> plan -> side-effect-free validation -> guarded
execution -> durable version-2 journal -> guarded undo/redo or recovery.

The CLI and Qt GUI call the same core. execute enforces validation independently
of callers. The full move plan and identities are written before moving any file;
each move has a pending record written first. Linux no-overwrite syscalls protect
against destination races. Recovery reconciles pending moves and rolls back the
applied prefix, including interrupted rollback. Conflicts stop recovery safely.

GUI: selection -> operation controls -> live reviewed preview -> confirm -> apply.
Option changes invalidate preview. Scanning and mutations use a worker thread.
History lists sessions and distinguishes undoable completion from interrupted
sessions needing recovery. Undo of the latest undo performs redo.

Version 1.1.0 binds previews to source/destination fingerprints, adds validated
settings presets, CSV export, natural ordering, a redo button, progress and
cooperative cancellation. Malformed history remains inspectable but blocks new
mutations. AppImage builds and native audits are tracked and checked by CI.

Limitations and operating instructions are maintained in README.md and AUDIT.md.
Future work could investigate model-backed large-library views, append-only
journal storage with a reviewed migration, and additional no-overwrite backends.
