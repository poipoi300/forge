"""CLI run behavior with a real local harness."""

import json
import sys
from pathlib import Path

import pytest

from forge import cli


@pytest.fixture
def runner_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "_repo_root", lambda: tmp_path)
    command = [
        sys.executable,
        "-c",
        "import sys; print(sys.argv[1]); sys.exit(3 if sys.argv[1].startswith('fail') else 0)",
        "{prompt}",
    ]
    (tmp_path / "forge.toml").write_text(
        f'[runner]\ndefault_harness = "fake"\n[harness.fake]\ncommand = {json.dumps(command)}\n',
        encoding="utf-8",
    )
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name, content in (("app", "start"), ("app_follow-up_1", "fail"), ("app_follow-up_2", "skip")):
        (prompts / f"{name}.md").write_text(content, encoding="utf-8")
    return tmp_path


def test_cli_reports_each_repeat_after_a_failure(runner_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "app", "--repeat", "2"]) == 1
    out = capsys.readouterr().out
    manifests = sorted(runner_repo.glob("runs/app/*/meta/run.json"))
    assert len(manifests) == 2
    for path in manifests:
        assert str(path) in out
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert [step["exit_reason"] for step in manifest["steps"]] == ["ok", "crash", None]
    assert out.count("skipped (prior_step_failed)") == 2


def test_reused_custom_name_keeps_each_original_prompt(runner_repo: Path) -> None:
    for prompt in ("first {prompt_path}", "second {telemetry_path}"):
        assert cli.main(["run", "--prompt", prompt, "--name", "custom"]) == 0
    steps = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in runner_repo.glob("runs/custom/*/meta/step-00-initial.json")
    ]
    assert len(steps) == 2
    assert {Path(step["prompt_file"]).read_text().strip() for step in steps} == {
        "first {prompt_path}",
        "second {telemetry_path}",
    }
    assert {step["command"][-1].strip() for step in steps} == {
        "first {prompt_path}",
        "second {telemetry_path}",
    }


def test_invalid_repeat_is_rejected(runner_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="2"):
        cli.main(["run", "app", "--repeat", "0"])
    assert "--repeat must be a positive integer" in capsys.readouterr().err


def test_custom_name_must_stay_inside_run_root(runner_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "--prompt", "start", "--name", "../outside"]) == 2
    assert "invalid project name" in capsys.readouterr().err
    assert not (runner_repo / "runs").exists()
