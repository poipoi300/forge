"""Load and validate forge.toml, the runner configuration."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "forge.toml"
_COMMIT_ID = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


class ConfigError(Exception):
    """forge.toml is missing, malformed, or references undefined entries."""


@dataclass(frozen=True)
class HarnessConfig:
    """One agent CLI the runner can invoke.

    Attributes:
        name: Key of the [harness.<name>] table.
        command: Argv template with optional prompt and telemetry paths.
        telemetry_format: Native output format to read for usage.
    """

    name: str
    command: tuple[str, ...]
    telemetry_format: str | None = None


@dataclass(frozen=True)
class PinnedSeed:
    """A local fixture repository and the full ID of its starting commit."""

    repository: Path
    commit: str


@dataclass(frozen=True)
class ForgeConfig:
    """Validated view of forge.toml."""

    default_harness: str
    workspace_root: Path
    step_timeout_s: float
    harnesses: dict[str, HarnessConfig]
    seeds: dict[str, PinnedSeed] = field(default_factory=dict)

    def harness(self, name: str | None = None) -> HarnessConfig:
        """Return the named harness, or the default when name is None."""
        key = name if name is not None else self.default_harness
        if key not in self.harnesses:
            available = ", ".join(sorted(self.harnesses))
            raise ConfigError(f"harness {key!r} not defined in forge.toml (available: {available})")
        return self.harnesses[key]


def load_config(repo_root: Path) -> ForgeConfig:
    """Parse <repo_root>/forge.toml into a ForgeConfig.

    Raises:
        ConfigError: on a missing file, unparseable TOML, missing keys, or a
            default_harness that names no [harness.*] table.
    """
    path = repo_root / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(f"{path} not found")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from e

    runner = raw.get("runner")
    if not isinstance(runner, dict):
        raise ConfigError("forge.toml must contain a [runner] table")

    harness_tables = raw.get("harness")
    if not isinstance(harness_tables, dict) or not harness_tables:
        raise ConfigError("forge.toml must define at least one [harness.<name>] table")

    harnesses: dict[str, HarnessConfig] = {}
    for name, table in harness_tables.items():
        command = table.get("command") if isinstance(table, dict) else None
        if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
            raise ConfigError(f"[harness.{name}] needs a non-empty 'command' list of strings")
        telemetry_format = table.get("telemetry_format")
        if telemetry_format is not None and telemetry_format != "claude-json":
            raise ConfigError(f"[harness.{name}] telemetry_format must be 'claude-json' when set")
        harnesses[name] = HarnessConfig(name=name, command=tuple(command), telemetry_format=telemetry_format)

    default_harness = runner.get("default_harness")
    if not isinstance(default_harness, str) or default_harness not in harnesses:
        raise ConfigError("[runner] default_harness must name a defined [harness.*] table")

    workspace_root = runner.get("workspace_root", "runs")
    if not isinstance(workspace_root, str) or not workspace_root:
        raise ConfigError("[runner] workspace_root must be a non-empty string")

    step_timeout_s = runner.get("step_timeout_s", 3600)
    if not isinstance(step_timeout_s, int | float) or step_timeout_s <= 0:
        raise ConfigError("[runner] step_timeout_s must be a positive number")

    seed_tables = raw.get("seed", {})
    if not isinstance(seed_tables, dict):
        raise ConfigError("forge.toml seed must be a table of [seed.<project>] entries")
    seeds: dict[str, PinnedSeed] = {}
    for project, table in seed_tables.items():
        repository = table.get("repository") if isinstance(table, dict) else None
        if not isinstance(repository, str) or not repository or "\0" in repository:
            raise ConfigError(f"[seed.{project}] repository must be a non-empty local path without NUL characters")
        commit = table.get("commit")
        if not isinstance(commit, str) or not _COMMIT_ID.fullmatch(commit):
            raise ConfigError(f"[seed.{project}] commit must be a full Git commit ID")
        seeds[project] = PinnedSeed(repository=(repo_root / repository).absolute(), commit=commit.lower())

    return ForgeConfig(
        default_harness=default_harness,
        workspace_root=repo_root / workspace_root,
        step_timeout_s=float(step_timeout_s),
        harnesses=harnesses,
        seeds=seeds,
    )
