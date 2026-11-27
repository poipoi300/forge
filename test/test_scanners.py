"""Published scanners check the repository tree and propagate tool failures."""

import subprocess
from pathlib import Path

import pytest

from forge.hooks.scanners import main


@pytest.mark.parametrize("tool", ["gitleaks", "osv-scanner", "semgrep"])
def test_scanner_uses_the_repository_and_propagates_its_exit_code(tool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    monkeypatch.delenv("PRE_COMMIT_LOCAL_BRANCH", raising=False)

    def run(argv: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert argv[0] == tool and argv[-1] == "."
        if tool == "gitleaks":
            assert "--log-opts=--full-history -m HEAD" in argv
        if tool == "semgrep":
            assert Path(argv[argv.index("--config") + 1]).is_file()
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(subprocess, "run", run)
    assert main([tool]) == 1


def test_a_missing_scanner_names_the_required_tool(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    monkeypatch.delenv("PRE_COMMIT_LOCAL_BRANCH", raising=False)

    def run(argv: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as error:
        main(["gitleaks"])
    assert error.value.code == 2
    assert "install gitleaks on PATH" in capsys.readouterr().err


def test_pre_push_scans_refuse_another_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "other")

    def rev_parse(argv: list[str], *, text: bool) -> str:
        return argv[-1]

    monkeypatch.setattr(subprocess, "check_output", rev_parse)
    with pytest.raises(SystemExit) as error:
        main(["gitleaks"])
    assert error.value.code == 2
