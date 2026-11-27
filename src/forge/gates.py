"""Gate registry: the deterministic checks a project repo is expected to carry.

This is the seed of the non-trivial part of forge — a machine-readable
description of which gates exist, so later stages (repo generation, trajectory
measurement) can reason about them instead of grepping config files.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class GateStage(Enum):
    """When a gate runs in the local hook chain."""

    COMMIT = "pre-commit"
    PUSH = "pre-push"


@dataclass(frozen=True)
class Gate:
    """One deterministic quality gate.

    Attributes:
        name: Hook id as it appears in .pre-commit-config.yaml.
        stage: Whether it blocks commits or pushes. CI re-runs every gate,
            since hooks are bypassable.
    """

    name: str
    stage: GateStage


DETERMINISTIC_GATES: tuple[Gate, ...] = (
    Gate("trailing-whitespace", GateStage.COMMIT),
    Gate("end-of-file-fixer", GateStage.COMMIT),
    Gate("check-merge-conflict", GateStage.COMMIT),
    Gate("check-case-conflict", GateStage.COMMIT),
    Gate("check-added-large-files", GateStage.COMMIT),
    Gate("check-yaml", GateStage.COMMIT),
    Gate("check-toml", GateStage.COMMIT),
    Gate("check-json", GateStage.COMMIT),
    Gate("debug-statements", GateStage.COMMIT),
    Gate("detect-private-key", GateStage.COMMIT),
    Gate("no-todo", GateStage.COMMIT),
    Gate("gitleaks", GateStage.PUSH),
    Gate("osv-scanner", GateStage.PUSH),
    Gate("semgrep", GateStage.PUSH),
    Gate("tests-and-diff-coverage", GateStage.PUSH),
    Gate("ruff-format", GateStage.COMMIT),
    Gate("ruff-check", GateStage.COMMIT),
    Gate("mypy", GateStage.COMMIT),
)


def gates_for_stage(stage: GateStage) -> tuple[Gate, ...]:
    """Return the gates that run at the given hook stage."""
    return tuple(g for g in DETERMINISTIC_GATES if g.stage is stage)
