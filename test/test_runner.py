"""Step isolation and manifests, exercised with a real subprocess harness.

The fake "agent" is python -c writing a marker file, so these tests cover the
actual subprocess path (cwd, argv substitution, exit codes) without any LLM.
"""

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from forge import cli
from forge.config import ForgeConfig, HarnessConfig
from forge.prompts import ProjectPrompts, PromptStep
from forge.runner import run_project


def _config(tmp_path: Path, command: list[str], timeout_s: float = 60) -> ForgeConfig:
    harness = HarnessConfig(name="fake", command=tuple(command))
    return ForgeConfig(
        default_harness="fake",
        workspace_root=tmp_path / "runs",
        step_timeout_s=timeout_s,
        harnesses={"fake": harness},
    )


def _two_step_project(tmp_path: Path) -> ProjectPrompts:
    initial = tmp_path / "app.md"
    initial.write_text("build it\n", encoding="utf-8")
    follow_up = tmp_path / "app_follow-up_1.md"
    follow_up.write_text("extend it\n", encoding="utf-8")
    return ProjectPrompts(
        project="app",
        steps=(PromptStep(0, "initial", initial), PromptStep(1, "follow-up-1", follow_up)),
    )


# Appends the prompt text to out.txt in cwd — visible proof of both the cwd
# and the {prompt} substitution.
_APPEND_AGENT = [
    sys.executable,
    "-c",
    (
        "import pathlib,sys; p=pathlib.Path('out.txt'); "
        "p.write_text(p.read_text() + sys.argv[1] if p.exists() else sys.argv[1])"
    ),
    "{prompt}",
]


def test_steps_are_isolated_and_copied_forward(tmp_path: Path) -> None:
    config = _config(tmp_path, _APPEND_AGENT)
    results = run_project(config, _two_step_project(tmp_path)).steps

    assert [r.ok for r in results] == [True, True]
    assert results[0].workspace and results[1].workspace
    step0 = Path(results[0].workspace) / "out.txt"
    step1 = Path(results[1].workspace) / "out.txt"
    # Step 0's artifact is untouched by step 1; step 1 built on a copy.
    assert step0.read_text() == "build it\n"
    assert step1.read_text() == "build it\nextend it\n"


def test_manifest_and_logs_written(tmp_path: Path) -> None:
    config = _config(tmp_path, _APPEND_AGENT)
    run = run_project(config, _two_step_project(tmp_path))

    meta = run.manifest_path.parent
    manifest = json.loads((meta / "step-00-initial.json").read_text(encoding="utf-8"))
    assert manifest["exit_code"] == 0
    assert manifest["harness"] == "fake"
    assert manifest["starting_head"] is None
    assert manifest["stdout_log"] == "step-00-initial.stdout.txt"
    assert (meta / manifest["stdout_log"]).read_bytes() == b""
    assert (meta / manifest["stderr_log"]).read_bytes() == b""
    assert len(run.steps) == 2


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", *args],
        text=True,
    ).strip()


@pytest.fixture
def pinned_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, str]:
    monkeypatch.setattr(cli, "_repo_root", lambda: tmp_path)
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    _two_step_project(prompts)
    repo = tmp_path / "fixture repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "commit", "--quiet", "--no-gpg-sign", "--allow-empty", "-m", "Start")
    fixture_file = repo / "fixture.txt"
    fixture_file.write_text("original\n", encoding="utf-8")
    _git(repo, "add", "fixture.txt")
    _git(repo, "commit", "--quiet", "--no-gpg-sign", "-m", "Baseline")
    pinned = _git(repo, "rev-parse", "HEAD")
    fixture_file.write_text("newer\n", encoding="utf-8")
    _git(repo, "commit", "--quiet", "--no-gpg-sign", "-am", "Later change")
    return repo, pinned, _git(repo, "rev-parse", "HEAD")


def _write_pinned_config(root: Path, repo: Path, commit: str, command: list[str]) -> None:
    (root / "forge.toml").write_text(
        '[runner]\ndefault_harness = "fake"\n[harness.fake]\n'
        f"command = {json.dumps(command)}\n[seed.app]\n"
        f'repository = {json.dumps(repo.name)}\ncommit = "{commit}"\n',
        encoding="utf-8",
    )


def test_pinned_fixture_records_starting_head_before_harness_changes_it(
    tmp_path: Path, pinned_project: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, pinned, later = pinned_project
    command = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; import subprocess; "
            "assert Path('fixture.txt').read_text() == 'original\\n'; "
            "subprocess.run(['git', '-c', 'user.name=Agent', '-c', 'user.email=agent@example.test', "
            "'commit', '--quiet', '--no-gpg-sign', '--allow-empty', '-m', 'Agent change'], check=True)"
        ),
    ]
    _write_pinned_config(tmp_path, repo, pinned, command)

    with monkeypatch.context() as git_env:
        git_env.setenv("GIT_DIR", str(repo / ".git"))
        git_env.setenv("GIT_WORK_TREE", str(repo))
        assert cli.main(["run", "app", "--through-step", "0"]) == 0

    project = tmp_path / "runs" / "app"
    (run,) = project.iterdir()
    workspace = run / "step-00-initial"
    manifest = json.loads((run / "meta" / "step-00-initial.json").read_text(encoding="utf-8"))
    assert manifest["starting_head"] == pinned
    assert json.loads((run / "meta" / "run.json").read_text())["steps"][0]["starting_head"] == pinned
    assert _git(workspace, "rev-parse", "HEAD^") == pinned
    assert _git(workspace, "rev-parse", "HEAD^^") == _git(repo, "rev-parse", f"{pinned}^")
    assert _git(workspace, "remote") == ""
    assert not (workspace / ".git" / "FETCH_HEAD").exists()
    assert subprocess.run(["git", "cat-file", "-e", later], cwd=workspace, check=False).returncode != 0
    assert _git(repo, "rev-parse", "HEAD") == later


def test_unavailable_pin_fails_before_harness_and_can_be_retried(
    tmp_path: Path, pinned_project: tuple[Path, str, str]
) -> None:
    repo, pinned, _ = pinned_project
    missing = "1" * len(pinned)
    _write_pinned_config(tmp_path, repo, missing, _APPEND_AGENT)

    assert cli.main(["run", "app"]) == 1
    project = tmp_path / "runs" / "app"
    (failed,) = project.iterdir()
    assert not list(failed.glob("step-*"))
    meta = failed / "meta"
    manifest = json.loads((meta / "run.json").read_text())
    assert manifest["exit_reason"] == "harness_error"
    assert manifest["steps"][0]["starting_head"] is None
    assert manifest["steps"][0]["attempted"]
    assert manifest["steps"][0]["workspace"] is None
    assert manifest["steps"][1]["skip_reason"] == "prior_step_failed"
    assert missing in (meta / manifest["steps"][0]["stderr_log"]).read_text()

    _write_pinned_config(tmp_path, repo, pinned, _APPEND_AGENT)
    assert cli.main(["run", "app"]) == 0
    (retried,) = (run for run in project.iterdir() if run != failed)
    follow_up = retried / "step-01-follow-up-1"
    assert (follow_up / "fixture.txt").read_text(encoding="utf-8") == "original\n"
    assert (follow_up / "out.txt").read_text(encoding="utf-8") == "build it\nextend it\n"
    assert not (follow_up / ".git").exists()


def test_mixed_outcomes_preserve_attempted_cost_and_skipped_steps(tmp_path: Path) -> None:
    project = _two_step_project(tmp_path)
    third = tmp_path / "app_follow-up_2.md"
    third.write_text("finish it\n", encoding="utf-8")
    project = ProjectPrompts(project.project, (*project.steps, PromptStep(2, "follow-up-2", third)))
    config = _config(
        tmp_path,
        [
            sys.executable,
            "-c",
            (
                "import json, pathlib, sys\n"
                "failed = sys.argv[2].startswith('extend')\n"
                "usage = {'tokens': 20, 'cost_usd': 0.50, 'quota_percent': 0} if not failed "
                "else {'cost_usd': 1.0, 'exit_reason': 'gate_fail'}\n"
                "pathlib.Path(sys.argv[1]).write_text(json.dumps(usage))\n"
                "print(sys.argv[2].strip())\n"
                "sys.exit(3 if failed else 0)"
            ),
            "{telemetry_path}",
            "{prompt}",
        ],
    )
    run = run_project(config, project)

    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert manifest["exit_reason"] == "gate_fail"
    assert manifest["attempted_steps"] == 2
    assert manifest["skipped_steps"] == 1
    assert manifest["duration_s"] >= 0
    assert manifest["cost_usd_per_attempted_task"] == 0.75
    assert manifest["coverage"] == {"tokens": 1, "cost_usd": 2, "quota_percent": 1}
    initial, failed, skipped = manifest["steps"]
    assert initial["exit_reason"] == "ok"
    assert initial["telemetry"] == {
        "tokens": 20,
        "cost_usd": 0.5,
        "quota_percent": 0,
        "coverage": {"tokens": True, "cost_usd": True, "quota_percent": True},
    }
    assert failed["attempted"]
    assert failed["exit_reason"] == "gate_fail"
    assert failed["exit_code"] == 3
    assert failed["telemetry"]["tokens"] is None
    assert not failed["telemetry"]["coverage"]["tokens"]
    assert (run.manifest_path.parent / failed["stdout_log"]).read_text().strip() == "extend it"
    assert not skipped["attempted"]
    assert skipped["skip_reason"] == "prior_step_failed"
    for field in ("exit_reason", "workspace", "started_at", "duration_s", "stdout_log", "stderr_log"):
        assert skipped[field] is None
    assert not (run.manifest_path.parent.parent / "step-02-follow-up-2").exists()
    assert json.loads((run.manifest_path.parent / "step-02-follow-up-2.json").read_text(encoding="utf-8")) == skipped


def test_timeout_is_recorded_not_raised(tmp_path: Path) -> None:
    config = _config(tmp_path, [sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.5)
    run = run_project(config, _two_step_project(tmp_path))

    assert run.exit_reason == "timeout"
    assert run.steps[0].timed_out
    assert run.steps[1].skip_reason == "prior_step_failed"


def test_repeats_have_distinct_ids_and_preserve_all_runs(tmp_path: Path) -> None:
    config = _config(tmp_path, _APPEND_AGENT)
    project = _two_step_project(tmp_path)
    legacy = config.workspace_root / "app" / "step-00-initial"
    legacy.mkdir(parents=True)
    (legacy / "out.txt").write_text("legacy", encoding="utf-8")
    first = run_project(config, project)
    second = run_project(config, project)

    assert first.run_id != second.run_id
    for run in (first, second):
        assert uuid.UUID(run.run_id).version == 4
        assert run.manifest_path == config.workspace_root / "app" / run.run_id / "meta" / "run.json"
        manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema_version"] == 1
        assert manifest["run_id"] == run.run_id
        assert manifest["exit_reason"] == "ok"
        assert manifest["attempted_steps"] == 2
        assert manifest["skipped_steps"] == 0
        assert manifest["cost_usd_per_attempted_task"] is None
        for step in manifest["steps"]:
            assert step["run_id"] == run.run_id
            assert Path(step["workspace"]).parent == run.manifest_path.parent.parent
        assert (Path(manifest["steps"][0]["workspace"]) / "out.txt").read_text() == "build it\n"
    assert (legacy / "out.txt").read_text() == "legacy"


def test_missing_harness_binary_recorded_not_raised(tmp_path: Path) -> None:
    config = _config(tmp_path, ["definitely-not-a-real-binary-xyz", "{prompt}"])
    run = run_project(config, _two_step_project(tmp_path))

    assert run.exit_reason == "harness_error"
    assert run.steps[0].exit_code is None
    assert not run.steps[0].ok
    meta = run.manifest_path.parent
    assert b"not found" in (meta / "step-00-initial.stderr.txt").read_bytes()


def test_through_step_limits_sequence(tmp_path: Path) -> None:
    config = _config(tmp_path, _APPEND_AGENT)
    run = run_project(config, _two_step_project(tmp_path), through_step=0)
    assert run.exit_reason == "ok"
    assert run.steps[0].ok
    assert run.steps[1].skip_reason == "through_step"


@pytest.mark.parametrize("telemetry", ["", "42", "{broken", '{"tokens": true, "cost_usd": NaN, "quota_percent": 101}'])
def test_invalid_telemetry_stays_unknown_without_hiding_crashes(tmp_path: Path, telemetry: str) -> None:
    config = _config(
        tmp_path,
        [
            sys.executable,
            "-c",
            "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2]); sys.exit(3)",
            "{telemetry_path}",
            telemetry,
        ],
    )
    run = run_project(config, _two_step_project(tmp_path))
    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert manifest["exit_reason"] == "crash"
    assert manifest["cost_usd_per_attempted_task"] is None
    assert manifest["steps"][0]["telemetry"] == {
        "tokens": None,
        "cost_usd": None,
        "quota_percent": None,
        "coverage": {"tokens": False, "cost_usd": False, "quota_percent": False},
    }
