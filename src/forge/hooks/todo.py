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
_REMEDY = "file an issue and link it from a comment that states the constraint"
# A list of work is a prose document; `todo.py` is code about todos.
_TRACKING_FILE = re.compile(r"(?:todos?|fixme)(?:\.(?:md|markdown|txt|org|rst|adoc))?", re.IGNORECASE)


def _comment_spans(text: str, *, nested_blocks: bool = False) -> Iterator[tuple[int, int]]:
    """`(start, end)` of each comment, skipping double-quoted strings.

    Block comments (`/* */`, `<!-- -->`) may span lines; an unterminated one
    runs to the end of the file, and `/* */` nests where the language says
    so (Rust). Line comments start at `#` or `//` anywhere in code, at `--`
    after whitespace or the line start (not a flag or a table rule), and at
    `;` or `%` only at the line start, where they cannot be an operator.
    Single quotes are not strings, since Rust uses them for lifetimes.
    """
    index, line_start = 0, True
    while index < len(text):
        char = text[index]
        if char == "\n":
            index, line_start = index + 1, True
            continue
        if char == '"':
            string = _STRING.match(text, index)
            index, line_start = (string.end() if string else index + 1), False
            continue
        if text.startswith("/*", index) or text.startswith("<!--", index):
            end = _block_end(text, index, nested=nested_blocks and text.startswith("/*", index))
            yield index, end
            index, line_start = end, False
            continue
        previous = text[index - 1] if index else "\n"
        if (
            char == "#"
            or text.startswith("//", index)
            or (text.startswith("--", index) and previous in " \t\n")
            or (char in ";%" and line_start)
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


def _python_comment_spans(text: str) -> Iterator[tuple[int, int]]:
    """Python comments exactly, from the tokenizer; strings and docstrings are not comments."""
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        yield from _comment_spans(text)
        return
    for token in tokens:
        if token.type == tokenize.COMMENT:
            yield starts[token.start[0] - 1] + token.start[1], starts[token.end[0] - 1] + token.end[1]


def _comment_markers(path: Path, text: str) -> Iterator[re.Match[str]]:
    """Each marker inside a comment, in file order."""
    if path.suffix in {".py", ".pyi"}:
        spans = _python_comment_spans(text)
    else:
        spans = _comment_spans(text, nested_blocks=path.suffix == ".rs")
    for start, end in spans:
        yield from _WORD.finditer(text, start, end)


def offences(path: Path) -> list[str]:
    """Describe each marker comment in the file, and the file itself if its name tracks work."""
    found = [f"{path}: work-tracking file; track the work in issues"] if _TRACKING_FILE.fullmatch(path.name) else []
    text = path.read_bytes().decode("utf-8", errors="replace")
    for marker in _comment_markers(path, text):
        line = text.count("\n", 0, marker.start()) + 1
        found.append(f"{path}:{line}: {marker.group(1)} comment; {_REMEDY}")
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
