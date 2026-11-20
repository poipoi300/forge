"""The gate registry, the published hooks, forge's own hooks and the CI workflows agree."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from forge.gates import DETERMINISTIC_GATES, GateStage, gates_for_stage

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISHED = yaml.safe_load((REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
CONFIG = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
# Keys that decide when and how a hook runs; pre-commit's defaults fill the gaps.
HOOK_DEFAULTS: dict[str, Any] = {
    "types": ["file"],
    "types_or": [],
    "exclude": "^$",
    "files": "",
    "pass_filenames": True,
    "always_run": False,
    "require_serial": False,
}


def load_workflow(name: str) -> dict[str, Any]:
    # BaseLoader keeps GitHub's "on" key and expressions as strings.
    text = (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    workflow: dict[str, Any] = yaml.load(text, Loader=yaml.BaseLoader)
    return workflow


def config_hooks() -> dict[str, dict[str, Any]]:
    return {hook["id"]: hook for repo in CONFIG["repos"] for hook in repo["hooks"]}


def stages(hook: dict[str, Any]) -> list[str]:
    return list(hook.get("stages", CONFIG["default_stages"]))


def test_registry_matches_precommit_config() -> None:
    hooks = config_hooks()
    assert [gate.name for gate in DETERMINISTIC_GATES] == list(hooks)
    for gate in DETERMINISTIC_GATES:
        assert stages(hooks[gate.name]) == [gate.stage.value]


def test_push_stage_holds_only_slow_gates() -> None:
    assert {g.name for g in gates_for_stage(GateStage.PUSH)} == {"tests-and-diff-coverage"}


def test_forge_runs_exactly_the_published_hooks_in_its_first_block() -> None:
    own = [hook["id"] for hook in CONFIG["repos"][0]["hooks"]]
    assert own == [hook["id"] for hook in PUBLISHED]
    assert len(set(own)) == len(own)


@pytest.mark.parametrize("published", PUBLISHED, ids=lambda hook: hook["id"])
def test_forge_runs_each_published_hook_from_its_own_checkout(published: dict[str, Any]) -> None:
    own = config_hooks()[published["id"]]
    assert published["language"] == "python"
    assert own["language"] == "system"
    assert own["entry"] == f"uv run --locked {published['entry']}"
    for key, default in HOOK_DEFAULTS.items():
        assert own.get(key, default) == published.get(key, default), key
    assert stages(own) == published.get("stages", ["pre-commit"])


def test_every_published_entry_point_is_a_console_script() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for hook in PUBLISHED:
        assert f'\n{hook["entry"].split()[0]} = "forge.hooks.' in pyproject


def test_ci_calls_the_published_workflow_on_this_checkout() -> None:
    ci = load_workflow("ci.yml")
    assert set(ci["on"]) == {"push", "pull_request"}
    assert ci["permissions"] == {"contents": "read"}
    (job,) = ci["jobs"].values()
    assert job["uses"] == "./.github/workflows/gates.yml"


def steps_by_run(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step["run"]: step for step in job["steps"] if "run" in step}


def test_published_workflow_runs_both_stages_on_every_lane_as_blocking_steps() -> None:
    gates = load_workflow("gates.yml")
    assert set(gates["on"]) == {"workflow_call"}
    assert gates["permissions"] == {"contents": "read"}
    lane = gates["jobs"]["lane"]
    assert lane["strategy"]["matrix"]["os"] == "${{ fromJSON(inputs.os) }}"
    assert lane["strategy"]["fail-fast"] == "false"
    runs = steps_by_run(lane)
    commit = runs["uv run --locked pre-commit run --hook-stage pre-commit --all-files"]
    push = runs["uv run --locked pre-commit run --hook-stage pre-push --all-files"]
    collect = runs["uv run --locked pre-commit run tests-and-diff-coverage --hook-stage pre-push --all-files"]
    # The push stage skips only the coverage hook, and only because the next gate step runs it.
    assert push["env"] == {"SKIP": "tests-and-diff-coverage"}
    assert set(collect["env"]) == {"FORGE_COVERAGE_COLLECT"}
    order = list(runs)
    assert order.index(commit["run"]) < order.index(push["run"]) < order.index(collect["run"])
    for job in gates["jobs"].values():
        for scope in (job, *job["steps"]):
            assert "continue-on-error" not in scope
            assert "|| true" not in scope.get("run", "")
            if "pre-commit run" in scope.get("run", ""):
                assert "if" not in scope


def test_published_workflow_gates_the_merge_of_every_lane() -> None:
    gates = load_workflow("gates.yml")
    lane, merge = gates["jobs"]["lane"], gates["jobs"]["coverage"]
    assert merge["needs"] == "lane"
    assert "if" not in merge
    (upload,) = (s for s in lane["steps"] if s.get("uses", "").startswith("actions/upload-artifact@"))
    (download,) = (s for s in merge["steps"] if s.get("uses", "").startswith("actions/download-artifact@"))
    collect = steps_by_run(lane)[
        "uv run --locked pre-commit run tests-and-diff-coverage --hook-stage pre-push --all-files"
    ]
    final = steps_by_run(merge)[
        "uv run --locked pre-commit run tests-and-diff-coverage --hook-stage pre-push --all-files"
    ]
    # One lane directory per artifact, merged on download into one directory per lane.
    assert collect["env"]["FORGE_COVERAGE_COLLECT"] == upload["with"]["path"] + "/lane-${{ strategy.job-index }}"
    assert upload["with"]["name"] == "forge-coverage-${{ strategy.job-index }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert download["with"] == {
        "pattern": "forge-coverage-*",
        "merge-multiple": "true",
        "path": final["env"]["FORGE_COVERAGE_REPORTS"],
    }


def test_the_forge_token_is_scoped_to_fetching_the_pinned_hooks() -> None:
    gates = load_workflow("gates.yml")
    for job in gates["jobs"].values():
        steps = job["steps"]
        holders = [step for step in steps if "secrets." in str(step)]
        assert [step["name"] for step in holders] == ["Fetch the pinned hooks"]
        assert "git config --global" not in holders[0]["run"]
        fetch = steps.index(holders[0])
        assert all("pre-commit run" not in step.get("run", "") for step in steps[:fetch])


def test_callers_cannot_set_the_variables_that_steer_the_gates() -> None:
    export = next(
        s
        for s in load_workflow("gates.yml")["jobs"]["lane"]["steps"]
        if s.get("name") == "Export the project's environment"
    )
    assert "SKIP|FORGE_[A-Za-z0-9_]*|DIFF_COVER_[A-Za-z0-9_]*" in export["run"]
    assert export["run"].index("exit 1") < export["run"].index('>> "$GITHUB_ENV"')


def test_the_merge_job_installs_what_the_project_install_needs() -> None:
    jobs = load_workflow("gates.yml")["jobs"]
    names = [step.get("name") for step in jobs["coverage"]["steps"]]
    assert {"Install apt packages", "Install the pinned Rust toolchain"} <= set(names)
    assert names.index("Install the pinned Rust toolchain") < names.index("Install the project's gate tools")


def test_published_workflow_pins_actions_and_runners() -> None:
    for name in ("gates.yml", "ci.yml"):
        workflow = load_workflow(name)
        for job in workflow["jobs"].values():
            assert "latest" not in str(job.get("runs-on", ""))
            for step in job.get("steps", []):
                action = step.get("uses")
                if action:
                    revision = action.partition("@")[2]
                    assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision), action
                if action and action.startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] == "false"
                    assert step["with"]["fetch-depth"] == "0"
