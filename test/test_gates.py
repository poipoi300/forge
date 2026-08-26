"""The gate registry must stay in sync with the actual hook/CI configs."""

from pathlib import Path

import yaml

from code_factory.gates import DETERMINISTIC_GATES, GateStage, gates_for_stage

REPO_ROOT = Path(__file__).resolve().parent.parent


def _hook_ids_in_precommit_config() -> set[str]:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    return {hook["id"] for repo in config["repos"] for hook in repo["hooks"]}


def test_registry_matches_precommit_config() -> None:
    registry_ids = {g.name for g in DETERMINISTIC_GATES}
    assert registry_ids == _hook_ids_in_precommit_config()


def test_push_stage_holds_only_slow_gates() -> None:
    assert {g.name for g in gates_for_stage(GateStage.PUSH)} == {"tests-and-diff-coverage"}


def test_ci_enforced_gates_appear_in_workflow() -> None:
    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # CI runs the tools directly rather than via pre-commit; map hook id -> the
    # command substring that proves the gate is present in the workflow.
    expected_evidence = {
        "ruff-format": "ruff format --check",
        "ruff-check": "ruff check",
        "mypy": "mypy .",
        "tests-and-diff-coverage": "coverage_gate.sh",
    }
    ci_gates = {g.name for g in DETERMINISTIC_GATES if g.ci_enforced}
    assert ci_gates == set(expected_evidence)
    for evidence in expected_evidence.values():
        assert evidence in workflow_text
