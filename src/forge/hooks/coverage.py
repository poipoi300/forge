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
import re
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


def _env() -> dict[str, str]:
    # pre-commit activates the hook's own virtualenv; the project's tools run in the project's.
    return {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}


def _run(argv: Sequence[str], **env: str) -> int:
    return subprocess.run(argv, env={**_env(), **env}, check=False).returncode


def _coverage_settings() -> dict[str, list[str]]:
    """coverage.py's effective settings from `coverage debug config`; list values continue on indented lines."""
    report = subprocess.run(
        project_tool("coverage", "debug", "config"), env=_env(), capture_output=True, text=True, check=True
    ).stdout
    settings: dict[str, list[str]] = {}
    key = ""
    for line in report.splitlines():
        if entry := re.fullmatch(r"\s*(\w+): (.*)", line):
            key = entry.group(1)
            settings[key] = [entry.group(2).strip()]
        elif key and line.strip() and not line.startswith("--"):
            settings[key].append(line.strip())
    return {name: [value for value in values if value not in {"None", "-none-"}] for name, values in settings.items()}


def _require_portable_python_config() -> None:
    """Fail unless coverage.py records repository-relative paths and measures first-party directories."""
    settings = _coverage_settings()
    missing = []
    if settings.get("relative_files") != ["True"]:
        missing.append("[run] relative_files = true, so lanes from other checkouts and platforms merge")
    # Package names (source_pkgs, or a name in source) skip unimported modules of namespace packages.
    roots = settings.get("source", []) + settings.get("source_dirs", [])
    if not roots or settings.get("source_pkgs") or not all(Path(root).is_dir() for root in roots):
        missing.append("[run] source = [<first-party directories>], so a module no test imports still counts")
    if settings.get("include_namespace_packages") != ["True"]:
        missing.append("[report] include_namespace_packages = true, so directories without __init__.py count")
    if missing:
        raise SystemExit(f"forge-coverage-gate: set coverage.py's {'; '.join(missing)}")


def _check(argv: Sequence[str], **env: str) -> None:
    if status := _run(argv, **env):
        raise SystemExit(status)


def collect(languages: Iterable[str], out: Path) -> None:
    """Run each language's tests under coverage, writing this platform's reports into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    if "python" in languages:
        _require_portable_python_config()
        data = (out / PYTHON_DATA).resolve()
        # COVERAGE_FILE, unlike --data-file, also reaches the subprocesses coverage.py measures.
        _check(project_tool("coverage", "run", "-m", "pytest"), COVERAGE_FILE=str(data))
        # `parallel = true` writes suffixed shards; each lane publishes one data file.
        if shards := sorted(out.glob(f"{PYTHON_DATA}.*")):
            _check(project_tool("coverage", "combine", f"--data-file={data}", *(str(shard) for shard in shards)))
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


def _ensure_base(ref: str) -> None:
    # A commit, or the empty tree that an initial push compares against.
    if subprocess.run(["git", "cat-file", "-e", ref], capture_output=True).returncode:
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
    _ensure_base(compare)
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


def _require_pushing_head(parser: argparse.ArgumentParser) -> None:
    # The gate tests the working tree, so a pre-push for another ref would test the wrong code.
    pushed = os.environ.get("PRE_COMMIT_TO_REF")
    if not pushed:
        return
    head, target = (
        subprocess.check_output(["git", "rev-parse", f"{ref}^{{commit}}"], text=True).strip()
        for ref in ("HEAD", pushed)
    )
    if head != target:
        parser.error(f"the push sends {target}, not the checked-out HEAD {head}; push from a checkout of it")
    changed = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], text=True)
    if changed:
        parser.error(f"the working tree differs from the pushed commit; commit, stash or remove:\n{changed}")


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
            _require_pushing_head(parser)
            lanes = [work / "local"]
            collect(languages, lanes[0])
        return gate(languages, lanes, work, fail_under=args.fail_under, excludes=excludes)


if __name__ == "__main__":
    sys.exit(main())
