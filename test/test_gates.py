"""The gate registry, the published hooks, forge's own hooks and the CI workflows agree."""

import os
import subprocess
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
    assert collect["env"]["FORGE_COVERAGE_COLLECT"] == upload["with"]["path"] + "/lane-${{ matrix.os }}"
    assert upload["with"]["name"] == "forge-coverage-${{ matrix.os }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert download["with"] == {
        "pattern": "forge-coverage-*",
        "merge-multiple": "true",
        "path": final["env"]["FORGE_COVERAGE_REPORTS"],
    }


def test_the_forge_token_only_reaches_a_git_only_step_before_any_project_code() -> None:
    gates = load_workflow("gates.yml")
    for job in gates["jobs"].values():
        steps = job["steps"]
        holders = [step for step in steps if "secrets." in str(step)]
        assert [step["name"] for step in holders] == ["Mirror forge for pre-commit"]
        script = holders[0]["run"]
        assert script.count("${FORGE_TOKEN}") == 1
        assert "git -c credential.helper= clone --mirror --quiet https://github.com/poipoi300/forge forge.git" in script
        # Nothing but git, grep and shell builtins runs where the token is.
        commands = {
            line.split()[0] for line in script.splitlines() if line.strip() and not line.strip().startswith("#")
        }
        assert commands <= {
            "if",
            "exit",
            "fi",
            "clone=(git",
            "GIT_CONFIG_COUNT=1",
            'GIT_CONFIG_KEY_0="url.https://x-access-token:${FORGE_TOKEN}@github.com/poipoi300/forge.insteadOf"',
            "GIT_CONFIG_VALUE_0=https://github.com/poipoi300/forge",
            '"${clone[@]}"',
            "elif",
            "echo",
            "git",
            "path=$(git",
            "case",
            "/*)",
            "*)",
            "esac",
            "while",
            "forge)",
            "keep)",
            "done",
        }, commands
        # Before it: the line-ending setting, checkout, setup-uv and the route step,
        # which runs uv without the checkout's configuration; the caller's env comes after.
        before = [
            step.get("name") or step.get("uses", "").partition("@")[0] for step in steps[: steps.index(holders[0])]
        ]
        assert before == [
            "Keep line endings as committed",
            "actions/checkout",
            "astral-sh/setup-uv",
            "Route forge to a local mirror",
        ]
        routes = steps[steps.index(holders[0]) - 1]
        assert routes["working-directory"] == "${{ runner.temp }}"
        assert "uv run --no-config --no-project --isolated --with pyyaml==6.0.3 python -I -" in routes["run"]
        names = [step.get("name") for step in steps]
        assert names.index("Mirror forge for pre-commit") < names.index("Export the project's environment")


def step_script(job: str, name: str) -> str:
    step = next(s for s in load_workflow("gates.yml")["jobs"][job]["steps"] if s.get("name") == name)
    script: str = step["run"]
    return script


def run_step(tmp_path: Path, script: str, env: dict[str, str]) -> tuple[int, dict[str, str], str]:
    github_env = tmp_path / "github_env"
    github_env.write_text("")
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        env={**os.environ, **env, "GITHUB_ENV": str(github_env)},
        capture_output=True,
        text=True,
    )
    exported = dict(line.split("=", 1) for line in github_env.read_text().splitlines())
    return result.returncode, exported, result.stdout


@pytest.mark.parametrize(
    ("project_env", "exported"),
    [
        ("CARGO_INCREMENTAL=0\nRUSTFLAGS=-D warnings\n", {"CARGO_INCREMENTAL": "0", "RUSTFLAGS": "-D warnings"}),
        ("SKIP=no-todo\n", None),
        ("skip=no-todo\n", None),
        ("Forge_Coverage_Collect=/tmp/x\n", None),
        ("DIFF_COVER_COMPARE_BRANCH=HEAD\n", None),
        ("NOTES<<EOF\nSKIP=no-todo\nEOF\n", None),
    ],
)
def test_callers_cannot_set_the_variables_that_steer_the_gates(
    tmp_path: Path, project_env: str, exported: dict[str, str] | None
) -> None:
    status, written, _ = run_step(
        tmp_path, step_script("lane", "Export the project's environment"), {"PROJECT_ENV": project_env}
    )
    if exported is None:
        assert status == 1 and written == {}
    else:
        assert status == 0 and written == exported


def test_the_merge_refuses_a_runner_listed_twice(tmp_path: Path) -> None:
    script = step_script("coverage", "Check every lane sent its reports")
    (tmp_path / "lane-ubuntu-24.04").mkdir()
    assert run_step(tmp_path, script, {"OS": '["ubuntu-24.04", "ubuntu-24.04"]', "REPORTS": str(tmp_path)})[0] == 1


def test_the_merge_refuses_a_missing_lane(tmp_path: Path) -> None:
    script = step_script("coverage", "Check every lane sent its reports")
    (tmp_path / "lane-ubuntu-24.04").mkdir()
    env = {"OS": '["ubuntu-24.04", "windows-2025"]', "REPORTS": str(tmp_path)}
    assert run_step(tmp_path, script, env)[0] == 1
    (tmp_path / "lane-windows-2025").mkdir()
    assert run_step(tmp_path, script, env)[0] == 0


def test_the_mirror_takes_only_forge_urls_and_leaves_siblings(tmp_path: Path) -> None:
    routes = step_script("lane", "Route forge to a local mirror")
    script = step_script("lane", "Mirror forge for pre-commit")
    real_git = subprocess.check_output(["bash", "-c", "command -v git"], text=True).strip()
    shim = tmp_path / "bin" / "git"
    shim.parent.mkdir()
    # A clone becomes an empty bare repository; everything else is real git.
    shim.write_text(
        f'#!/bin/bash\nif [[ " $* " == *" clone "* ]]; then exec {real_git} init -q --bare "${{@: -1}}"; fi\n'
        f'exec {real_git} "$@"\n'
    )
    shim.chmod(0o755)
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n"
        "  - repo: https://github.com/poipoi300/forge.git\n    rev: x\n    hooks: []\n"
        "  - \"repo\": 'https://github.com/poipoi300/forge'\n    rev: x\n    hooks: []\n"
        "  - {repo: https://github.com/poipoi300/forge.git-extension, rev: x, hooks: []}\n"
        "  - {repo: https://github.com/poipoi300/forge-extension, rev: x, hooks: []}\n"
        "  - repo: https://github.com/pre-commit/pre-commit-hooks\n    rev: x\n    hooks: []\n"
        "  - repo: local\n    hooks: []\n"
    )
    env = {
        "PATH": f"{shim.parent}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "FORGE_TOKEN": "",
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / ".pre-commit-config.yaml").rename(workspace / ".pre-commit-config.yaml")
    env["GITHUB_WORKSPACE"] = str(workspace)
    # A checkout's uv configuration must not reach the parser.
    (workspace / "uv.toml").write_text("no-index = true\n")
    for step in (routes, script):
        status, _, output = run_step(tmp_path, step, env)
        assert status == 0, output

    def rewritten(url: str) -> str:
        probe = tmp_path / "probe"
        subprocess.run(["git", "init", "-q", str(probe)], check=True)
        subprocess.run(["git", "-C", str(probe), "remote", "add", "x", url], check=True)
        result = subprocess.check_output(
            ["git", "-C", str(probe), "remote", "get-url", "x"], text=True, env={**os.environ, **env}
        ).strip()
        subprocess.run(["rm", "-rf", str(probe)], check=True)
        return result

    mirror = (tmp_path / "forge.git").resolve().as_posix()
    assert rewritten("https://github.com/poipoi300/forge.git") == f"file://{mirror}"
    assert rewritten("https://github.com/poipoi300/forge") == f"file://{mirror}"
    for sibling in ("https://github.com/poipoi300/forge-extension", "https://github.com/poipoi300/forge.git-extension"):
        assert rewritten(sibling) == sibling
    # Repositories forge's URLs do not prefix get no rule, so a runner's own routing still applies.
    rules = subprocess.check_output(
        ["git", "config", "--global", "--get-regexp", r"^url\."], text=True, env={**os.environ, **env}
    )
    assert "pre-commit-hooks" not in rules


@pytest.fixture
def pushed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", "-c", "user.email=t@e.org", "-c", "user.name=T", *args], cwd=repo, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo, check=True)
    return repo


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"EVENT": "pull_request", "PR_BASE": "HEAD"}, ("HEAD", "...")),
        ({"EVENT": "push", "REF": "refs/heads/main", "BEFORE": "HEAD"}, ("HEAD", "..")),
        ({"EVENT": "push", "REF": "refs/heads/main", "BEFORE": "0" * 40}, ("EMPTY_TREE", "..")),
        ({"EVENT": "push", "REF": "refs/heads/topic", "BEFORE": "HEAD"}, ("origin/main", "...")),
    ],
)
def test_the_coverage_base_follows_the_event(
    pushed_repo: Path, event: dict[str, str], expected: tuple[str, str]
) -> None:
    script = step_script("coverage", "Choose the coverage base")
    env = {"PR_BASE": "", "BEFORE": "", "REF": "", "DEFAULT_BRANCH": "main", **event}
    status, written, _ = run_step(pushed_repo, script, env)
    empty_tree = subprocess.check_output(["git", "hash-object", "-t", "tree", "/dev/null"], text=True).strip()
    base, notation = expected
    assert status == 0
    assert written == {
        "DIFF_COVER_COMPARE_BRANCH": base.replace("EMPTY_TREE", empty_tree),
        "FORGE_DIFF_RANGE_NOTATION": notation,
    }


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
