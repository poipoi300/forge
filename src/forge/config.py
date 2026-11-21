"""Load and validate forge.toml, the runner configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from forge.requirements import ConfigError as ConfigError
from forge.requirements import HarnessRequirements, Requirements, parse_requirements, read_toml

CONFIG_FILENAME = "forge.toml"


@dataclass(frozen=True)
class HarnessConfig:
    """One agent CLI the runner can invoke.

    Attributes:
        name: Key of the [harness.<name>] table.
        command: Argv template; "{prompt}" and "{prompt_path}" are substituted
            per step before execution.
    """

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class ForgeConfig:
    """Validated view of forge.toml."""

    default_harness: str
    workspace_root: Path
    step_timeout_s: float
    harnesses: dict[str, HarnessConfig]
    requirements: Requirements = field(default_factory=Requirements)

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
    raw = read_toml(path)

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
        harnesses[name] = HarnessConfig(name=name, command=tuple(command))

    default_harness = runner.get("default_harness")
    if not isinstance(default_harness, str) or default_harness not in harnesses:
        raise ConfigError("[runner] default_harness must name a defined [harness.*] table")

    workspace_root = runner.get("workspace_root", "runs")
    if not isinstance(workspace_root, str) or not workspace_root:
        raise ConfigError("[runner] workspace_root must be a non-empty string")

    step_timeout_s = runner.get("step_timeout_s", 3600)
    if not isinstance(step_timeout_s, int | float) or step_timeout_s <= 0:
        raise ConfigError("[runner] step_timeout_s must be a positive number")

    requirements = parse_requirements(raw.get("requirements", {}))
    for name, declaration in requirements.harnesses.items():
        if name not in harnesses or declaration.cli != harnesses[name].command[0]:
            raise ConfigError(f"[requirements.harness.{name}] cli must match the configured harness executable")
    for name, harness in harnesses.items():
        requirements.harnesses.setdefault(name, HarnessRequirements(harness.command[0]))

    return ForgeConfig(
        default_harness=default_harness,
        workspace_root=repo_root / workspace_root,
        step_timeout_s=float(step_timeout_s),
        harnesses=harnesses,
        requirements=requirements,
    )
