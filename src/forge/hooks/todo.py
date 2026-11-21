"""Reject work-tracking markers: TODO-style comments and TODO files.

Known future work lives in an issue. A code comment states the constraint and
links the issue instead, so a marker is rejected whether or not it links one.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
from collections.abc import Iterator, Sequence
from pathlib import Path

MARKERS = ("TODO", "FIXME", "XXX", "HACK")
_WORD = re.compile(rf"\b({'|'.join(MARKERS)})\b")
# A double-quoted string, with backslash escapes, ending at its closing quote or the line end.
_STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"?')
# Rust literals: strings and raw strings span lines; a char literal holds one (escaped) char.
_RUST_LITERAL = re.compile(
    r'b?r(#*)"(?s:.*?)"\1'
    r'|b?"(?:[^"\\]|\\.)*"'
    r"|b?'(?:\\(?:x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]{1,6}\}|.)|[^\\'\n])'",
    re.DOTALL,
)
_REMEDY = "file an issue and link it from a comment that states the constraint"
# A list of work is a prose document; `todo.py` is code about todos.
_TRACKING_FILE = re.compile(r"(?:todos?|fixme)(?:\.(?:md|markdown|txt|org|rst|adoc))?", re.IGNORECASE)


def _comment_spans(text: str, *, rust: bool = False) -> Iterator[tuple[int, int]]:
    """`(start, end)` of each comment, skipping double-quoted strings.

    Block comments (`/* */`, `<!-- -->`) may span lines; an unterminated one
    runs to the end of the file. Line comments start at `#` or `//` anywhere
    in code, at `--` after whitespace or the line start (not a flag or a
    table rule), and at `;` or `%` only at the line start, where they cannot
    be an operator. Single quotes are not strings. Rust files lex Rust's own
    literals (multiline and raw strings, char literals), take only `//` and
    `/* */` comments, and nest block comments.
    """
    index, line_start = 0, True
    while index < len(text):
        char = text[index]
        if char == "\n":
            index, line_start = index + 1, True
            continue
        literal = _RUST_LITERAL.match(text, index) if rust and (not index or not _is_word(text[index - 1])) else None
        if literal:
            index, line_start = literal.end(), False
            continue
        if char == '"' and not rust:
            string = _STRING.match(text, index)
            index, line_start = (string.end() if string else index + 1), False
            continue
        if text.startswith("/*", index) or (text.startswith("<!--", index) and not rust):
            end = _block_end(text, index, nested=rust)
            yield index, end
            index, line_start = end, False
            continue
        previous = text[index - 1] if index else "\n"
        if text.startswith("//", index) or (
            not rust
            and (char == "#" or (text.startswith("--", index) and previous in " \t\n") or (char in ";%" and line_start))
        ):
            end = text.find("\n", index)
            end = len(text) if end == -1 else end
            yield index, end
            index = end
            continue
        line_start = line_start and char in " \t"
        index += 1


def _block_end(text: str, start: int, *, nested: bool) -> int:
    opener, closer = ("/*", "*/") if text.startswith("/*", start) else ("<!--", "-->")
    depth, index = 1, start + len(opener)
    while depth:
        close = text.find(closer, index)
        if close == -1:
            return len(text)
        inner = text.find(opener, index) if nested else -1
        if inner != -1 and inner < close:
            depth, index = depth + 1, inner + len(opener)
        else:
            depth, index = depth - 1, close + len(closer)
    return index


def _is_word(char: str) -> bool:
    return char.isalnum() or char == "_"


def _python_markers(raw: bytes) -> Iterator[tuple[int, str]] | None:
    """`(line, marker)` for each marker in a Python comment, or None when the file does not tokenize."""
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(raw).readline))
    except (tokenize.TokenError, SyntaxError):
        return None
    return (
        (token.start[0], marker.group(1))
        for token in tokens
        if token.type == tokenize.COMMENT
        for marker in _WORD.finditer(token.string)
    )


def _markers(path: Path, raw: bytes) -> Iterator[tuple[int, str]]:
    """`(line, marker)` for each marker inside a comment, in file order."""
    if path.suffix in {".py", ".pyi"} and (python := _python_markers(raw)) is not None:
        yield from python
        return
    text = raw.decode("utf-8", errors="replace")
    for start, end in _comment_spans(text, rust=path.suffix == ".rs"):
        for marker in _WORD.finditer(text, start, end):
            yield text.count("\n", 0, marker.start()) + 1, marker.group(1)


def offences(path: Path) -> list[str]:
    """Describe each marker comment in the file, and the file itself if its name tracks work."""
    found = [f"{path}: work-tracking file; track the work in issues"] if _TRACKING_FILE.fullmatch(path.name) else []
    for line, marker in _markers(path, path.read_bytes()):
        found.append(f"{path}:{line}: {marker} comment; {_REMEDY}")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Print every offence in the given files and return 1 if there was any."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    found = [offence for path in parser.parse_args(argv).paths for offence in offences(path)]
    for offence in found:
        print(offence)
    return int(bool(found))


if __name__ == "__main__":
    sys.exit(main())
