"""Host preflight through the CLI, using executables on a fixture PATH."""

import json
import os
from pathlib import Path

import pytest

from forge import cli, doctor
from forge.config import load_config
from forge.gates import DETERMINISTIC_GATES


def _executable(bin_dir: Path, name: str, script: str) -> Path:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + script, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def bin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "bin"
    directory.mkdir()
    monkeypatch.setenv("PATH", str(directory))
    monkeypatch.setattr(doctor.os, "defpath", str(directory))
    monkeypatch.setattr(doctor.platform, "freedesktop_os_release", lambda: {"ID": "arch"})
    monkeypatch.setattr(cli, "_repo_root", lambda: tmp_path)
    return directory


def _write_config(root: Path, requirements: str = "") -> Path:
    path = root / "forge.toml"
    path.write_text(
        '[runner]\ndefault_harness = "pi"\n[harness.pi]\ncommand = ["pi", "--print"]\n' + requirements,
        encoding="utf-8",
    )
    return path


@pytest.mark.skipif(os.name != "posix", reason="the Arch test uses shell executables")
def test_doctor_reports_selected_path_package_version_and_missing_harness(
    bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = bin_dir.parent
    _write_config(
        root,
        """
        [requirements]
        required = ["uv"]
        optional = ["bun"]
        [requirements.gate.python]
        required = ["uv", "git"]
        [requirements.harness.pi]
        cli = "pi"
        """,
    )
    uv = _executable(bin_dir, "uv", 'test "$1" = --version && printf "uv 1.2.3\n"')
    git = _executable(bin_dir, "git", 'test "$1" = --version && printf "git version 2.3.4\n"')
    _executable(
        bin_dir,
        "pacman",
        'test "$1/$2" = -Qqo/-- || exit 2\n'
        f'if test "$3" = "{git}"; then printf "git-package\n"; exit 0; fi\n'
        'printf "error: No package owns %s\n" "$3" >&2\nexit 1\n',
    )
    # Doctor can run even when prompt discovery would fail.
    prompts = root / "prompts"
    prompts.mkdir()
    (prompts / "orphan_follow-up_1.md").touch()

    assert cli.main(["doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert [row["name"] for row in report["tools"]] == ["bun", "git", "pi", "uv"]
    tools = {row["name"]: row for row in report["tools"]}
    assert tools["uv"] == {
        "name": "uv",
        "status": "unmanaged",
        "path": str(uv),
        "version": "uv 1.2.3",
        "package": None,
        "ownership_unknown": False,
        "required": True,
        "required_by": ["gate.python", "host"],
        "optional_for": [],
    }
    assert tools["git"]["status"] == "present"
    assert tools["git"]["package"] == "git-package"
    assert tools["bun"]["status"] == "missing"
    assert tools["pi"]["required"] is False
    assert report["harnesses"]["pi"] == {"cli": "pi", "status": "unavailable", "missing": ["pi"]}

    assert cli.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "uv: unmanaged (required)" in output
    assert "git: present (required)" in output
    assert "bun: missing (optional)" in output
    assert "harness pi: unavailable (missing pi)" in output


@pytest.mark.skipif(os.name != "posix", reason="the test uses shell executables")
def test_project_manifest_probes_versions_only_when_explicitly_trusted(
    bin_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = bin_dir.parent
    _write_config(root, '[requirements]\nrequired = ["uv"]\n')
    project = root / "project"
    project.mkdir()
    (project / "forge.project.toml").write_text(
        """
        schema = 1
        [project]
        id = "demo"
        [requirements]
        required = ["uv", "custom"]
        [requirements.gate.verify]
        required = ["uninstalled"]
        [requirements.harness.pi]
        cli = "pi"
        optional = ["plugin"]
        """,
        encoding="utf-8",
    )
    _executable(bin_dir, "uv", 'printf "uv 1.2.3\n" >&2')
    _executable(bin_dir, "pacman", 'printf "must-not-run\n"')
    _executable(bin_dir, "custom", f'printf ran > "{root / "ran"}"\nprintf "custom 1.2.3\n"')
    _executable(bin_dir, "pi", "exit 2")
    monkeypatch.setattr(doctor.platform, "freedesktop_os_release", lambda: {"ID": "fedora"})
    monkeypatch.chdir(project)

    assert cli.main(["doctor", "--manifest", str(project), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    tools = {row["name"]: row for row in report["tools"]}
    assert tools["uv"]["version"] is None
    assert tools["uv"]["package"] is None
    assert tools["pi"]["version"] is None
    assert tools["custom"]["status"] == "present"
    assert tools["custom"]["version"] is None
    assert not (root / "ran").exists()
    assert tools["uninstalled"]["status"] == "missing"
    assert report["harnesses"]["pi"]["status"] == "available"

    assert cli.main(["doctor", "--manifest", str(project), "--trust-manifest", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    tools = {row["name"]: row for row in report["tools"]}
    assert tools["uv"]["version"] == "uv 1.2.3"
    assert tools["custom"]["version"] == "custom 1.2.3"
    assert (root / "ran").exists()


@pytest.mark.skipif(os.name != "posix", reason="the Arch test uses shell executables")
def test_project_owned_tools_are_listed_without_executing_them(
    bin_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = bin_dir.parent
    _write_config(root, '[requirements]\nrequired = ["git"]\n')
    project = root / "project"
    project_bin = project / "bin"
    project_bin.mkdir(parents=True)
    manifest = project / "config" / "forge.project.toml"
    manifest.parent.mkdir()
    manifest.write_text('[requirements]\nrequired = ["git"]\n', encoding="utf-8")
    for name in ("git", "pacman"):
        _executable(project_bin, name, f'printf ran > "{project / f"{name}-ran"}"')
    _executable(bin_dir, "pacman", 'printf "error: No package owns %s\n" "$3" >&2\nexit 1')
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", str(project_bin))

    assert cli.main(["doctor", "--manifest", str(manifest.relative_to(project)), "--json"]) == 0
    git = json.loads(capsys.readouterr().out)["tools"][0]
    assert git["status"] == "unmanaged"
    assert git["version"] is None
    assert not (project / "git-ran").exists()
    assert not (project / "pacman-ran").exists()


def test_doctor_escapes_manifest_control_characters_in_text_and_errors(
    bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = bin_dir.parent
    _write_config(root)
    manifest = root / "forge.project.toml"
    manifest.write_text('[requirements.harness."bad\\u001B[2J"]\ncli = "pi"\n', encoding="utf-8")
    assert cli.main(["doctor", "--manifest", str(manifest)]) == 0
    assert r"harness bad\x1b[2J: unavailable" in capsys.readouterr().out

    manifest.write_text('[requirements]\n"bad\\u001B[2J" = true\n', encoding="utf-8")
    assert cli.main(["doctor", "--manifest", str(manifest)]) == 2
    assert r"requirements has unknown keys: bad\x1b[2J" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="the Arch test uses shell executables")
def test_doctor_distinguishes_a_failed_package_query_from_an_unmanaged_tool(
    bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_config(bin_dir.parent, '[requirements]\nrequired = ["git"]\n')
    _executable(bin_dir, "git", "exit 0")
    _executable(bin_dir, "pacman", 'printf "error: unable to open database\n" >&2\nexit 1')

    assert cli.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "git: present (required)" in output
    assert "package ownership unknown" in output


@pytest.mark.parametrize(
    ("declaration", "message"),
    [
        ("requirements = []", "requirements must be a table"),
        ('[requirements]\nrequired = "git"', "requirements.required must be a list"),
        ('[requirements]\nrequired = ["./git"]', "requirements.required must name a PATH executable"),
        ("[requirements]\nextra = 1", "requirements has unknown keys"),
        ("[requirements.gate]\ntest = false", "requirements.gate.test must be a table"),
        ("[requirements.harness.pi]", "requirements.harness.pi.cli must name a PATH executable"),
    ],
)
def test_malformed_project_requirements_report_a_config_error(
    bin_dir: Path, declaration: str, message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = bin_dir.parent
    _write_config(root)
    path = root / "forge.project.toml"
    path.write_text(declaration + "\n", encoding="utf-8")
    assert cli.main(["doctor", "--manifest", str(path), "--json"]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert message in output.err


def test_project_manifest_without_requirements_is_healthy(bin_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = bin_dir.parent
    _write_config(root)
    manifest = root / "forge.project.toml"
    manifest.write_text("schema = 1\n", encoding="utf-8")
    assert cli.main(["doctor", "--manifest", str(manifest)]) == 0
    assert capsys.readouterr().out == "No host-tool requirements declared.\n"


def test_repo_declares_host_tools_per_gate_and_harness() -> None:
    config = load_config(Path(__file__).resolve().parent.parent)
    assert {"uv", "git", "gh"} <= set(config.requirements.host.required)
    assert {"bun", "cargo", "bwrap"} <= set(config.requirements.host.optional)
    assert {gate.name for gate in DETERMINISTIC_GATES} <= config.requirements.gates.keys()
    assert config.requirements.harnesses.keys() == config.harnesses.keys()
    for scanner in ("gitleaks", "osv-scanner", "semgrep"):
        assert scanner in config.requirements.gates[scanner].required
