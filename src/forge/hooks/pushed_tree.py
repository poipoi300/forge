"""Require checkout-based push gates to inspect the tree being pushed."""

import argparse
import os
import subprocess


def require_pushing_head(parser: argparse.ArgumentParser) -> None:
    # The gate tests the working tree, so a pre-push for another ref would test the wrong code.
    # pre-commit omits PRE_COMMIT_TO_REF when the push includes a root commit.
    pushed = os.environ.get("PRE_COMMIT_TO_REF") or os.environ.get("PRE_COMMIT_LOCAL_BRANCH")
    if not pushed:
        return
    head, target = (
        subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], text=True
        ).strip()
        for ref in ("HEAD", pushed)
    )
    if head != target:
        parser.error(f"the push sends {target}, not the checked-out HEAD {head}; push from a checkout of it")
    changed = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], text=True)
    if changed:
        parser.error(f"the working tree differs from the pushed commit; commit, stash or remove:\n{changed}")
