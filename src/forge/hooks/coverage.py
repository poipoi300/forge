"""Run the tests under coverage, merge every platform's reports, and gate changed lines.

The hook's command is the same everywhere; the environment chooses the mode:

- By default it collects this platform's coverage, then gates it.
- `FORGE_COVERAGE_COLLECT=<dir>` only collects into `<dir>`. Each CI lane does
  this on its own platform.
- `FORGE_COVERAGE_REPORTS=<dir>` runs no tests. It merges the lanes' reports,
  one subdirectory per lane, and gates the merge, so a line counts as covered
  when any platform runs it.

`DIFF_COVER_COMPARE_BRANCH` names the base (default `origin/main`), fetched
from `origin` when it is missing locally. `FORGE_DIFF_RANGE_NOTATION` is `...`
(changes since the merge base, the default) or `..` (the two tips, for a push
that may have replaced history).
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import TextIO

FAIL_UNDER = 90
PYTHON_DATA = "python.coverage"
RUST_DIR = "rust"


def project_tool(*argv: str) -> list[str]:
    """The command running a tool from the project's own locked environment."""
    return ["uv", "run", "--locked", *argv]


def _run(argv: Sequence[str]) -> int:
    # pre-commit activates the hook's own virtualenv; the project's tools run in the project's.
    env = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    return subprocess.run(argv, env=env, check=False).returncode


def _check(argv: Sequence[str]) -> None:
    if status := _run(argv):
        raise SystemExit(status)


def collect(languages: Iterable[str], out: Path) -> None:
    """Run each language's tests under coverage, writing this platform's reports into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    if "python" in languages:
        _check(project_tool("coverage", "run", f"--data-file={out / PYTHON_DATA}", "-m", "pytest"))
    if "rust" in languages:
        rust = out / RUST_DIR
        rust.mkdir(exist_ok=True)
        manifest = subprocess.check_output(
            ["cargo", "locate-project", "--workspace", "--message-format", "plain"], text=True
        )
        (rust / "manifest.txt").write_text(manifest, encoding="utf-8")
        _check(
            [
                "cargo",
                "llvm-cov",
                "nextest",
                "--workspace",
                "--locked",
                "--lcov",
                "--output-path",
                str(rust / "lcov.info"),
            ]
        )


def merge_lcov(reports: Iterable[Path], output: TextIO) -> None:
    """Join native LCOV traces under repository-relative source names.

    Each report directory holds `lcov.info` and `manifest.txt`, the workspace
    manifest path on the platform that wrote the trace. diff-cover sums the
    hits of records that share a source name, so a line covered on any
    platform counts, and a line only one platform compiles stays measured.
    """
    for report in reports:
        manifest = (report / "manifest.txt").read_text(encoding="utf-8").rstrip("\r\n")
        flavour: type[PurePath] = PureWindowsPath if PureWindowsPath(manifest).drive else PurePosixPath
        root = flavour(manifest).parent
        with (report / "lcov.info").open(encoding="utf-8") as trace:
            for raw in trace:
                line = raw.removesuffix("\n")
                if line.startswith("SF:"):
                    source = flavour(line[3:])
                    if source.is_relative_to(root):
                        source = source.relative_to(root)
                    line = f"SF:{source.as_posix()}"
                print(line, file=output)


def _python_report(lanes: Sequence[Path], work: Path) -> Path:
    data, xml = work / PYTHON_DATA, work / "python.xml"
    _check(
        project_tool(
            "coverage", "combine", "--keep", f"--data-file={data}", *(str(lane / PYTHON_DATA) for lane in lanes)
        )
    )
    _check(project_tool("coverage", "xml", f"--data-file={data}", "-o", str(xml)))
    return xml


def _rust_report(lanes: Sequence[Path], work: Path) -> Path:
    merged = work / "rust.info"
    with merged.open("w", encoding="utf-8") as output:
        merge_lcov((lane / RUST_DIR for lane in lanes), output)
    return merged


def _ensure_commit(ref: str) -> None:
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], capture_output=True).returncode:
        _check(["git", "fetch", "--quiet", "origin", ref.removeprefix("origin/")])


def _excluded(globs: Iterable[str]) -> list[str]:
    # diff-cover matches exclusions with fnmatch against a file's basename and its
    # absolute path, and fnmatch's `*` crosses `/`. Expanding the globs here into
    # escaped absolute paths keeps each exemption to exactly the files it names.
    return sorted({glob.escape((Path.cwd() / path).as_posix()) for pattern in globs for path in Path().glob(pattern)})


def gate(
    languages: Iterable[str],
    lanes: Sequence[Path],
    work: Path,
    *,
    fail_under: int,
    excludes: Sequence[str],
) -> int:
    """Merge the lanes' reports per language and hold each to `fail_under` on changed lines."""
    compare = os.environ.get("DIFF_COVER_COMPARE_BRANCH", "origin/main")
    notation = os.environ.get("FORGE_DIFF_RANGE_NOTATION", "...")
    _ensure_commit(compare)
    builders = {"python": _python_report, "rust": _rust_report}
    failed = 0
    for language in languages:
        report = builders[language](lanes, work)
        argv = [
            "diff-cover",
            str(report),
            f"--compare-branch={compare}",
            f"--diff-range-notation={notation}",
            f"--fail-under={fail_under}",
        ]
        if excludes:
            argv += ["--exclude", *excludes]
        failed |= int(bool(_run(project_tool(*argv))))
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    """Collect, gate, or both, as the environment selects."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", action="store_true", help="run pytest under coverage.py")
    parser.add_argument("--rust", action="store_true", help="run cargo nextest under cargo-llvm-cov")
    parser.add_argument("--fail-under", type=int, default=FAIL_UNDER, help="changed-line coverage percent (>= 90)")
    parser.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="exempt the paths a glob matches (`*` stays in one directory)",
    )
    args = parser.parse_args(argv)
    languages = [language for language in ("python", "rust") if getattr(args, language)]
    if not languages:
        parser.error("choose at least one language: --python, --rust")
    if args.fail_under < FAIL_UNDER:
        parser.error(f"--fail-under {args.fail_under} is below forge's floor of {FAIL_UNDER}")
    if os.environ.get("FORGE_DIFF_RANGE_NOTATION", "...") not in {"..", "..."}:
        parser.error("FORGE_DIFF_RANGE_NOTATION must be '..' or '...'")
    collect_dir, reports_dir = os.environ.get("FORGE_COVERAGE_COLLECT"), os.environ.get("FORGE_COVERAGE_REPORTS")
    if collect_dir and reports_dir:
        parser.error("set FORGE_COVERAGE_COLLECT or FORGE_COVERAGE_REPORTS, not both")
    excludes = _excluded(args.exclude_glob)

    if collect_dir:
        collect(languages, Path(collect_dir))
        return 0
    with tempfile.TemporaryDirectory(prefix="forge-coverage-") as scratch:
        work = Path(scratch)
        if reports_dir:
            lanes = sorted(path for path in Path(reports_dir).iterdir() if path.is_dir())
            if not lanes:
                parser.error(f"no lane reports under {reports_dir}")
        else:
            lanes = [work / "local"]
            collect(languages, lanes[0])
        return gate(languages, lanes, work, fail_under=args.fail_under, excludes=excludes)


if __name__ == "__main__":
    sys.exit(main())
