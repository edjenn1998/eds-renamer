# Ed's Renamer 1.1.0 review

Reviewed the original 1.0.3 code, tests, icon, launch/build scripts and release
metadata. All **100 original tests** passed before changes. The review addressed:

| Finding | Resolution |
| --- | --- |
| Apply captured current identities only at execution, so replaced files could be renamed after an older preview. | Capture reviewed source/destination fingerprints and carry them through validation, preflight and primitive moves. |
| Forced overwrite could back up a real directory, contrary to the file-only UI. | Reject directory/special-file destinations even with force; reject special-file sources. |
| Overlong UTF-8 filenames failed only after transaction setup. | Check the destination filesystem's byte-name limit in validation. |
| Raw/canonical parent aliases disagreed during overwrite detection and simulation. | Use consistent canonical parent keys while retaining symlink entries themselves. |
| Directory traversal could follow a queued directory replaced by a symlink. | Pin non-following directory descriptors; support cancellation and exclude the history root. |
| Validation rebuilt source sets repeatedly; conflict rendering could grow quadratically. | Build source keys once, index per-path issues and bound inline diagnostics. |
| Preview workers were retained by the window after completion. | Delete finished workers, wait for finished delivery before enabling Apply, and preserve selection across refreshes. |
| Cancellation/progress were absent, and close timing could interrupt UI bookkeeping. | Add cooperative checkpoints, rollback on apply/undo cancellation, resumable recovery pauses and deferred safe closing. |
| A malformed journal could prevent startup or produce uncaught CLI errors. | Validate journal schema/IDs; keep unreadable history visible while blocking new mutations; add a read-only journal viewer. |
| Session creation had an exists-check/replace race; failed saves could leave temporary files. | Exclusively install private journals with no-replace rename; clean failed write temps. |
| Expensive regular expressions could monopolize preview processing; CLI errors could show tracebacks. | Use timed, GIL-releasing matching and readable pattern/replacement errors. |
| Undo/redo were presented only as repeated Undo latest actions. | Record reversal relationships/actions and add Redo last undo without breaking older journals. |
| Optional shortcuts used the extracted payload path, which is temporary in an AppImage. | Point to APPIMAGE, respect XDG_DATA_HOME and test reserved-character paths with the real GIO parser. |
| No preview export, presets or natural numbering order. | Add CSV export, validated settings-only presets, Reset changes and natural sorting. |
| Missing ignore/CI files and host-dependent unpinned release tooling. | Add tracked AppImage sources, exact build pins, generated current notices, native audits and Ubuntu 22.04 CI. |
| README used remote screenshots and older raw-executable instructions. | Add a tracked sample screenshot and beginner-friendly AppImage permissions, launch and no-FUSE instructions. |

## Verification and remaining limits

**145 tests** cover the original behavior and new failure cases, with packaged
self-tests for Qt previews, regex, numbering and rename/undo/redo. Release builds
also test X11 and CLI startup. Tests use disposable files, not user data.

The engine remains Linux-specific and uses metadata fingerprints rather than
content hashes. Concurrent edits and a final check/syscall race remain documented
limits. Transactions are recoverable move sequences, not filesystem-wide atomic
batches. Durable full-journal rewrites after each move can be slow for very large
batches; a future append-only journal/model-backed table would require a separately
reviewed migration. Existing journals and backup files are preserved.
