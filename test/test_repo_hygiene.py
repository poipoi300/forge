import os
import subprocess
import sys
from pathlib import Path

import pytest

HYGIENE = Path(__file__).resolve().parents[1] / "tools" / "repo_hygiene.py"


def stage_paths(tmp_path: Path, *names: bytes) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    blob = subprocess.check_output(["git", "hash-object", "-w", "--stdin"], cwd=tmp_path, input=b"").strip()
    # Stage both names even on filesystems that cannot store them side by side.
    entries = b"".join(b"100644 " + blob + b"\t" + name + b"\0" for name in names)
    subprocess.run(["git", "update-index", "-z", "--index-info"], cwd=tmp_path, input=entries, check=True)
    indexed = subprocess.check_output(["git", "ls-files", "-z"], cwd=tmp_path)
    assert indexed.split(b"\0") == [*sorted(names), b""]


@pytest.mark.parametrize(
    ("first", "second", "collides"),
    [
        ("É.txt", "é.txt", True),
        ("cafe\u0301.txt", "café.txt", True),
        ("STRASSE.txt", "Straße.txt", True),
        ("ΐ.txt", "\u0399\u0308\u0301.txt", True),
        ("alpha.txt", "beta.txt", False),
    ],
)
def test_tracked_filename_collisions(tmp_path: Path, first: str, second: str, collides: bool) -> None:
    stage_paths(tmp_path, first.encode(), second.encode())

    result = subprocess.run(
        [sys.executable, HYGIENE, "check-case-conflict"],
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == int(collides), result.stderr
    assert result.stdout == (f"case-insensitive filename collision: {second} vs {first}\n" if collides else "")


@pytest.mark.parametrize("errors", ["strict", "replace"])
@pytest.mark.parametrize(
    ("encoding", "raw", "rendered"),
    [
        ("cp1252", "éΩ\n\x1b\\xff".encode() + b"\xff", r"é\u03a9\n\x1b\\xff\udcff"),
        ("cp932", "\u301c\uff5e".encode(), "\\u301c\uff5e"),
        ("shift_jis", "¥\\xa5".encode(), r"\xa5\\xa5"),
    ],
)
def test_display_preserves_path_on_one_line(encoding: str, raw: bytes, rendered: str, errors: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from repo_hygiene import _display_path; "
                "print(_display_path(sys.stdin.buffer.read().decode('utf-8', 'surrogateescape')))"
            ),
        ],
        cwd=HYGIENE.parent,
        input=raw,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONIOENCODING": f"{encoding}:{errors}"},
    )
    assert result.stdout.decode(encoding).splitlines() == [rendered]
