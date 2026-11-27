"""Run Forge's repository-wide security scanners at pre-push."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from forge.hooks.pushed_tree import require_pushing_head

SCANNERS = {
    "gitleaks": ("git", "--redact=100", "--log-opts=--full-history -m HEAD", "."),
    "osv-scanner": ("scan", "source", "--recursive", "--no-resolve", "--allow-no-lockfiles", "."),
    "semgrep": (
        "scan",
        "--config",
        str(Path(__file__).with_name("semgrep-rules.yaml")),
        "--error",
        "--strict",
        "--metrics=off",
        "--disable-version-check",
        "--no-rewrite-rule-ids",
        "--vim",
        ".",
    ),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scanner", choices=SCANNERS)
    scanner = parser.parse_args(argv).scanner
    require_pushing_head(parser)
    try:
        return subprocess.run([scanner, *SCANNERS[scanner]], check=False).returncode
    except FileNotFoundError:
        parser.error(f"install {scanner} on PATH to run this gate")


if __name__ == "__main__":
    sys.exit(main())
