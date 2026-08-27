"""forge.toml loading: valid configs parse, broken ones fail with clear errors."""

from pathlib import Path

import pytest

from forge.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_config(tmp_path: Path, body: str) -> Path:
    (tmp_path / "forge.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_repo_config_is_valid() -> None:
    config = load_config(REPO_ROOT)
    assert config.harness().name == config.default_harness
    assert config.workspace_root == REPO_ROOT / "runs"


def test_missing_file_raises() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("nonexistent-dir"))


def test_default_harness_must_be_defined(tmp_path: Path) -> None:
    root = _write_config(
        tmp_path,
        '[runner]\ndefault_harness = "ghost"\n[harness.real]\ncommand = ["echo", "{prompt}"]\n',
    )
    with pytest.raises(ConfigError, match="default_harness"):
        load_config(root)


def test_harness_command_must_be_string_list(tmp_path: Path) -> None:
    root = _write_config(
        tmp_path,
        '[runner]\ndefault_harness = "bad"\n[harness.bad]\ncommand = "echo {prompt}"\n',
    )
    with pytest.raises(ConfigError, match="command"):
        load_config(root)


def test_unknown_harness_lookup_names_available(tmp_path: Path) -> None:
    root = _write_config(
        tmp_path,
        '[runner]\ndefault_harness = "a"\n[harness.a]\ncommand = ["echo"]\n',
    )
    config = load_config(root)
    with pytest.raises(ConfigError, match="available: a"):
        config.harness("b")
