"""Bulk file renaming library.

Pure, file-system-agnostic operations plus a validated, transactional
engine and a journal-backed session store. The CLI in ``renamer.cli`` is a
thin adapter; a future GUI should use this package directly:
``expand_paths``/``order_paths`` -> ``plan`` -> ``validate`` -> ``execute``
-> ``Transaction``/``undo``.
"""
from .operations import (
    case_op,
    cut_op,
    ext_add_op,
    ext_case_op,
    ext_set_op,
    ext_strip_op,
    numbering_op,
    regex_op,
    replace_op,
    split_name,
    stem_set_op,
)
from .engine import (
    Move,
    Rename,
    ValidationIssue,
    execute,
    expand_paths,
    has_errors,
    order_paths,
    plan,
    summary,
    validate,
)
from .session import (
    DEFAULT_ROOT,
    Transaction,
    create_transaction,
    list_session_ids,
    load_transaction,
    newest_session,
    new_session_id,
)

__all__ = [
    "case_op",
    "cut_op",
    "ext_add_op",
    "ext_case_op",
    "ext_set_op",
    "ext_strip_op",
    "numbering_op",
    "regex_op",
    "replace_op",
    "split_name",
    "stem_set_op",
    "Move",
    "Rename",
    "ValidationIssue",
    "Transaction",
    "execute",
    "expand_paths",
    "has_errors",
    "order_paths",
    "plan",
    "summary",
    "validate",
    "create_transaction",
    "list_session_ids",
    "load_transaction",
    "newest_session",
    "new_session_id",
    "DEFAULT_ROOT",
]
