"""Pure string operations on (stem, suffix) pairs.

An operation is a function ``(stem, suffix, index, total) -> (stem, suffix)``.
Operations never touch the filesystem or argparse; ``index`` is the file's
position in the ordering (used for numbering) and ``total`` is the number of
files in the batch. The suffix (extension) is only ever changed by the
explicit extension operations.
"""
from __future__ import annotations

import re
from typing import Callable, Tuple

Op = Callable[[str, str, int, int], Tuple[str, str]]

NUMBER_RE = re.compile(r"#+")


def split_name(name: str) -> Tuple[str, str]:
    """Split ``image.jpg`` into ``('image', '.jpg')``.

    Leading dots of hidden files are part of the stem, so ``.gitignore``
    has no suffix, while ``.config.json`` -> ``('.config', '.json')``.
    """
    lead = len(name) - len(name.lstrip("."))
    i = name.rfind(".")
    if i <= 0 or i < lead or name.count(".") == lead:
        return name, ""
    return name[:i], name[i:]


def normalize_ext(ext: str) -> str:
    return "." + ext.lstrip(".") if ext else ""


def format_counter(value: int, width: int) -> str:
    text = str(value)
    if value >= 0 and width > 1 and len(text) < width:
        text = "0" * (width - len(text)) + text
    return text


def replace_op(old: str, new: str) -> Op:
    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return stem.replace(old, new), suffix

    return op


def regex_op(pattern: str, repl: str, ignore_case: bool = False) -> Op:
    rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)

    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return rx.sub(repl, stem), suffix

    return op


def cut_op(mode: str, n: int) -> Op:
    if n < 0:
        raise ValueError("cut position must be >= 0")
    if mode not in ("front", "end"):
        raise ValueError(f"unknown cut mode: {mode!r}")

    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return (stem[n:] if mode == "front" else stem[:n]), suffix

    return op


def case_op(kind: str) -> Op:
    if kind == "lower":
        fn = lambda s: s.lower()
    elif kind == "upper":
        fn = lambda s: s.upper()
    elif kind == "title":
        fn = lambda s: s.title()
    elif kind == "sentence":
        fn = lambda s: s[:1].upper() + s[1:]
    else:
        raise ValueError(f"unknown case mode: {kind!r}")

    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return fn(stem), suffix

    return op


def stem_set_op(name: str) -> Op:
    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return name, suffix

    return op


def numbering_op(
    mode: str = "token", start: int = 1, step: int = 1, pad: int = 1
) -> Op:
    """Numbering operation.

    If the (already edited) stem contains a ``#`` run, the first run is
    replaced by the counter and the run length is the zero-padding width
    (``###`` -> ``004``). Otherwise ``mode`` decides the fallback:
    ``prefix`` prepends and ``suffix`` appends the counter, padded to
    ``pad`` digits. The suffix is never touched.
    """
    if mode not in ("token", "prefix", "suffix"):
        raise ValueError(f"unknown number mode: {mode!r}")

    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        value = start + step * index
        run = NUMBER_RE.search(stem)
        if run:
            new = (
                stem[: run.start()]
                + format_counter(value, len(run.group(0)))
                + stem[run.end() :]
            )
            return new, suffix
        if mode == "token":
            return stem, suffix
        counter = format_counter(value, pad)
        return (counter + stem if mode == "prefix" else stem + counter), suffix

    return op


def ext_set_op(ext: str) -> Op:
    value = normalize_ext(ext)

    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return stem, value

    return op


def ext_add_op(ext: str) -> Op:
    value = normalize_ext(ext)

    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return stem, suffix or value

    return op


def ext_strip_op() -> Op:
    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return stem, ""

    return op


def ext_case_op(kind: str) -> Op:
    if kind == "lower":
        fn = str.lower
    elif kind == "upper":
        fn = str.upper
    else:
        raise ValueError(f"unknown ext case mode: {kind!r}")

    def op(stem: str, suffix: str, index: int, total: int) -> Tuple[str, str]:
        return stem, fn(suffix)

    return op
