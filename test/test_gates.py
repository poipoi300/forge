"""The gate registry must stay in sync with the actual hook/CI configs."""

import os
import subprocess
from pathlib import Path

import yaml

from forge.gates import DETERMINISTIC_GATES, GateStage, gates_for_stage

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNERS = {"gitleaks", "osv-scanner", "semgrep"}


def test_registry_matches_precommit_config() -> None:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hook_stages = {
        hook["id"]: hook.get("stages", config["default_stages"]) for repo in config["repos"] for hook in repo["hooks"]
    }
    assert hook_stages == {g.name: [g.stage.value] for g in DETERMINISTIC_GATES}


def test_push_stage_holds_only_slow_gates() -> None:
    assert {g.name for g in gates_for_stage(GateStage.PUSH)} == {"tests-and-diff-coverage", *SCANNERS}


def test_scanners_run_on_the_repository_even_without_changed_files() -> None:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    scanners = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"] if hook["id"] in SCANNERS}
    assert scanners.keys() == SCANNERS
    for hook in scanners.values():
        assert hook["always_run"] is True
        assert hook["pass_filenames"] is False


def test_first_push_ref_must_match_the_checked_out_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    git = [
        "git",
        "-c",
        f"core.hooksPath={tmp_path / 'hooks'}",
        "-c",
        "user.name=Forge",
        "-c",
        "user.email=forge@example.invalid",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run([*git, "commit", "--allow-empty", "-m", "Initial"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([*git, "branch", "branch-to-push"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([*git, "commit", "--allow-empty", "-m", "Next"], cwd=tmp_path, check=True, capture_output=True)

    env = {**os.environ, "PRE_COMMIT_TO_REF": "", "PRE_COMMIT_LOCAL_BRANCH": "refs/heads/branch-to-push"}
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "tools" / "coverage_gate.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Check out the commit you are pushing" in result.stderr


def test_ci_enforced_gates_appear_in_workflow() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = [step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"]]
    commit_steps = {
        "ruff-format": "ruff format --check",
        "ruff-check": "ruff check",
        "mypy": "mypy .",
    }
    assert {g.name for g in gates_for_stage(GateStage.COMMIT) if g.ci_enforced} == commit_steps.keys()
    for command in commit_steps.values():
        assert any(command in step for step in steps)
    assert "uv run --locked pre-commit run --hook-stage pre-push --all-files" in steps
    assert all(g.ci_enforced for g in gates_for_stage(GateStage.PUSH))
