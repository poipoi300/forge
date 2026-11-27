"""Each hygiene check rejects bad input and accepts clean input, as the published hooks call it."""

import subprocess
from pathlib import Path

import pytest

from forge.hooks import hygiene


@pytest.mark.parametrize(
    ("check", "bad", "good"),
    [
        ("trailing-whitespace", "line \n", "line\n"),
        ("end-of-file-fixer", "line\n\n", "line\n"),
        ("check-merge-conflict", "<" * 7 + " branch\n", "merged\n"),
        ("check-added-large-files", "x" * 1025, "x"),
        ("check-yaml", "a: [\n", "a: []\n"),
        ("check-toml", "[a\n", "[a]\n"),
        ("check-json", "{\n", "{}\n"),
        ("debug-statements", "break" + "point()\n", "pass\n"),
        ("detect-private-key", "-----BEGIN " + "PRIVATE KEY-----\n", "public\n"),
    ],
)
def test_check_rejects_bad_input_and_accepts_clean_input(tmp_path: Path, check: str, bad: str, good: str) -> None:
    path, other = tmp_path / "sample", tmp_path / "other"
    other.write_text(good)
    # pre-commit appends file names after the entry's own options.
    argv = [check, "--max-kb=1", str(other), str(path)]
    path.write_text(bad)
    assert hygiene.main(argv) == 1
    if check in {"trailing-whitespace", "end-of-file-fixer"}:
        assert path.read_text() == good
    path.write_text(good)
    assert hygiene.main(argv) == 0


@pytest.mark.parametrize("names", [("Readme", "README"), ("É.txt", "é.txt"), ("É", "é"), ("SS", "ß")])
def test_case_collision_is_checked_against_the_git_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: tuple[str, str]
) -> None:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    # Populate the index directly so the fixture also works on case-insensitive disks.
    blob = subprocess.check_output(["git", "hash-object", "-w", "--stdin"], input=b"").decode().strip()
    for name, result in zip(names, (0, 1), strict=True):
        subprocess.run(
            ["git", "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}"],
            check=True,
        )
        assert hygiene.main(["check-case-conflict"]) == result
