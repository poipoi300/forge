"""Reject work-tracking markers: TODO-style comments and TODO files.

Known future work lives in an issue. A code comment states the constraint and
links the issue instead, so a marker is rejected whether or not it links one.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

MARKERS = ("TODO", "FIXME", "XXX", "HACK")
# Comment leaders across the languages forge projects use: `#`, `//` and `/*`
# anywhere on a line; `<!--`; and the leaders that only open a comment at the
# start of a line, where they cannot be an operator (` *`, `;`, `%`) or a
# flag or table rule (`--` needs whitespace or the line start before it).
_LEADER = r"(?:\#|//|/\*|<!--|^[ \t]*[*;%]|(?:^|[ \t])--)"
_MARKER = re.compile(rf"{_LEADER}[^\n]*?\b({'|'.join(MARKERS)})\b", re.MULTILINE)
_REMEDY = "file an issue and link it from a comment that states the constraint"
_TRACKING_FILE = re.compile(r"(?:todos?|fixme)(?:\.[^.]+)?", re.IGNORECASE)


def offences(path: Path) -> list[str]:
    """Describe each marker comment in the file, and the file itself if its name tracks work."""
    found = [f"{path}: work-tracking file; track the work in issues"] if _TRACKING_FILE.fullmatch(path.name) else []
    text = path.read_bytes().decode("utf-8", errors="replace")
    for match in _MARKER.finditer(text):
        line = text.count("\n", 0, match.start(1)) + 1
        found.append(f"{path}:{line}: {match.group(1)} comment; {_REMEDY}")
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
