import subprocess
import sys
from pathlib import Path

import pytest

HYGIENE = Path(__file__).resolve().parents[1] / "tools" / "repo_hygiene.py"


@pytest.mark.parametrize(
    ("first", "second", "collides"),
    [
        ("É.txt", "é.txt", True),
        ("cafe\u0301.txt", "café.txt", True),
        ("STRASSE.txt", "Straße.txt", True),
        ("alpha.txt", "beta.txt", False),
    ],
)
def test_tracked_filename_collisions(tmp_path: Path, first: str, second: str, collides: bool) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    blob = subprocess.check_output(["git", "hash-object", "-w", "--stdin"], cwd=tmp_path, input=b"").strip()
    # Stage both names even on filesystems that cannot store them side by side.
    entries = b"".join(b"100644 " + blob + b"\t" + name.encode() + b"\0" for name in (first, second))
    subprocess.run(["git", "update-index", "-z", "--index-info"], cwd=tmp_path, input=entries, check=True)

    result = subprocess.run(
        [sys.executable, HYGIENE, "check-case-conflict"], cwd=tmp_path, capture_output=True, encoding="utf-8"
    )
    assert result.returncode == int(collides), result.stderr
    assert result.stdout == (f"case-insensitive filename collision: {second} vs {first}\n" if collides else "")
