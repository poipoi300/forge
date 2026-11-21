"""Step isolation and manifests, exercised with a real subprocess harness.

The fake "agent" is python -c writing a marker file, so these tests cover the
actual subprocess path (cwd, argv substitution, exit codes) without any LLM.
"""

import json
import subprocess
import sys
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
    results = run_project(config, _two_step_project(tmp_path))

    assert [r.ok for r in results] == [True, True]
    step0 = Path(results[0].workspace) / "out.txt"
    step1 = Path(results[1].workspace) / "out.txt"
    # Step 0's artifact is untouched by step 1; step 1 built on a copy.
    assert step0.read_text() == "build it\n"
    assert step1.read_text() == "build it\nextend it\n"


def test_manifest_and_logs_written(tmp_path: Path) -> None:
    config = _config(tmp_path, _APPEND_AGENT)
    results = run_project(config, _two_step_project(tmp_path))

    meta = config.workspace_root / "app" / "meta"
    manifest = json.loads((meta / "step-00-initial.json").read_text(encoding="utf-8"))
    assert manifest["exit_code"] == 0
    assert manifest["harness"] == "fake"
    assert manifest["starting_head"] is None
    assert (meta / "step-00-initial.stdout.txt").exists()
    assert len(results) == 2


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
    workspace = project / "step-00-initial"
    manifest = json.loads((project / "meta" / "step-00-initial.json").read_text(encoding="utf-8"))
    assert manifest["starting_head"] == pinned
    assert _git(workspace, "rev-parse", "HEAD^") == pinned
    assert _git(workspace, "rev-parse", "HEAD^^") == _git(repo, "rev-parse", f"{pinned}^")
    assert _git(workspace, "remote") == ""
    assert not (workspace / ".git" / "FETCH_HEAD").exists()
    assert subprocess.run(["git", "cat-file", "-e", later], cwd=workspace, check=False).returncode != 0
    assert _git(repo, "rev-parse", "HEAD") == later


def test_unavailable_pin_fails_before_harness_and_can_be_retried(
    tmp_path: Path, pinned_project: tuple[Path, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, pinned, _ = pinned_project
    missing = "1" * len(pinned)
    _write_pinned_config(tmp_path, repo, missing, _APPEND_AGENT)

    assert cli.main(["run", "app"]) == 1
    assert missing in capsys.readouterr().err
    assert not list((tmp_path / "runs" / "app").glob("step-*"))

    _write_pinned_config(tmp_path, repo, pinned, _APPEND_AGENT)
    assert cli.main(["run", "app"]) == 0
    follow_up = tmp_path / "runs" / "app" / "step-01-follow-up-1"
    assert (follow_up / "fixture.txt").read_text(encoding="utf-8") == "original\n"
    assert (follow_up / "out.txt").read_text(encoding="utf-8") == "build it\nextend it\n"
    assert not (follow_up / ".git").exists()


def test_failed_step_stops_the_sequence(tmp_path: Path) -> None:
    config = _config(tmp_path, [sys.executable, "-c", "import sys; sys.exit(3)"])
    results = run_project(config, _two_step_project(tmp_path))

    assert len(results) == 1
    assert results[0].exit_code == 3
    assert not results[0].ok


def test_timeout_is_recorded_not_raised(tmp_path: Path) -> None:
    config = _config(tmp_path, [sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.5)
    results = run_project(config, _two_step_project(tmp_path))

    assert len(results) == 1
    assert results[0].timed_out
    assert not results[0].ok


def test_existing_run_refuses_overwrite(tmp_path: Path) -> None:
    config = _config(tmp_path, _APPEND_AGENT)
    project = _two_step_project(tmp_path)
    run_project(config, project)
    with pytest.raises(FileExistsError, match="previous run"):
        run_project(config, project)


def test_missing_harness_binary_recorded_not_raised(tmp_path: Path) -> None:
    config = _config(tmp_path, ["definitely-not-a-real-binary-xyz", "{prompt}"])
    results = run_project(config, _two_step_project(tmp_path))

    assert len(results) == 1
    assert results[0].exit_code is None
    assert not results[0].ok
    meta = config.workspace_root / "app" / "meta"
    assert b"not found" in (meta / "step-00-initial.stderr.txt").read_bytes()


def test_through_step_limits_sequence(tmp_path: Path) -> None:
    config = _config(tmp_path, _APPEND_AGENT)
    results = run_project(config, _two_step_project(tmp_path), through_step=0)
    assert [r.step_name for r in results] == ["initial"]
