"""Reject work-tracking markers: TODO-style comments and TODO files.

Known future work lives in an issue. A code comment states the constraint and
links the issue instead, so a marker is rejected whether or not it links one.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

MARKERS = ("TODO", "FIXME", "XXX", "HACK")
_WORD = re.compile(rf"\b({'|'.join(MARKERS)})\b")
_STRING_END = re.compile(r'(?<!\\)"|\n')
_REMEDY = "file an issue and link it from a comment that states the constraint"
# A list of work is a prose document; `todo.py` is code about todos.
_TRACKING_FILE = re.compile(r"(?:todos?|fixme)(?:\.(?:md|markdown|txt|org|rst|adoc))?", re.IGNORECASE)


def _comment_spans(text: str) -> Iterator[tuple[int, int]]:
    """`(start, end)` of each comment, skipping double-quoted strings.

    Block comments (`/* */`, `<!-- -->`) may span lines; an unterminated one
    runs to the end of the file. Line comments start at `#` or `//` anywhere
    in code, at `--` after whitespace or the line start (not a flag or a
    table rule), and at `;` or `%` only at the line start, where they cannot
    be an operator. A double-quoted string ends at its closing quote or at
    the end of the line; single quotes are not strings, since Rust uses them
    for lifetimes.
    """
    index, line_start = 0, True
    while index < len(text):
        char = text[index]
        if char == "\n":
            index, line_start = index + 1, True
            continue
        if char == '"':
            closing = _STRING_END.search(text, index + 1)
            index = closing.end() if closing and closing.group() == '"' else (closing.start() if closing else len(text))
            line_start = False
            continue
        for opener, closer in (("/*", "*/"), ("<!--", "-->")):
            if text.startswith(opener, index):
                end = text.find(closer, index + len(opener))
                end = len(text) if end == -1 else end + len(closer)
                yield index, end
                index, line_start = end, False
                break
        else:
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


def _comment_markers(text: str) -> Iterator[re.Match[str]]:
    """Each marker inside a comment, in file order."""
    for start, end in _comment_spans(text):
        yield from _WORD.finditer(text, start, end)


def offences(path: Path) -> list[str]:
    """Describe each marker comment in the file, and the file itself if its name tracks work."""
    found = [f"{path}: work-tracking file; track the work in issues"] if _TRACKING_FILE.fullmatch(path.name) else []
    text = path.read_bytes().decode("utf-8", errors="replace")
    for marker in _comment_markers(text):
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
