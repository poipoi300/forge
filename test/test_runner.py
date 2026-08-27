"""Step isolation and manifests, exercised with a real subprocess harness.

The fake "agent" is python -c writing a marker file, so these tests cover the
actual subprocess path (cwd, argv substitution, exit codes) without any LLM.
"""

import json
import sys
from pathlib import Path

import pytest

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
    assert (meta / "step-00-initial.stdout.txt").exists()
    assert len(results) == 2


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
