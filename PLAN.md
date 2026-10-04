# Implemented architecture

Pure filename operations -> plan -> side-effect-free validation -> guarded
execution -> durable version-2 journal -> guarded undo/redo or recovery.

The CLI and Qt GUI call the same core. execute enforces validation independently
of callers. The full move plan and identities are written before moving any file;
each move has a pending record written first. Linux no-overwrite syscalls protect
against destination races. Recovery reconciles pending moves and rolls back the
applied prefix, including interrupted rollback. Conflicts stop recovery safely.

GUI: selection -> operation controls -> explicit preview -> confirm -> apply.
Option changes invalidate preview. Scanning and mutations use a worker thread.
History lists sessions and distinguishes undoable completion from interrupted
sessions needing recovery. Undo of the latest undo performs redo.

Limitations and operating instructions are maintained in README.md. Future work
could add serializable multi-operation presets, a dedicated redo button, progress
counts, large-library pagination, and platform-specific no-overwrite backends.
