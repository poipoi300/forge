"""Host-tool declarations shared by forge.toml and forge.project.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_MANIFEST = "forge.project.toml"
_TOOL_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.+-]*")


class ConfigError(Exception):
    """A forge configuration file is missing or invalid."""


@dataclass(frozen=True)
class ToolGroup:
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()


@dataclass(frozen=True)
class HarnessRequirements:
    cli: str
    tools: ToolGroup = ToolGroup()


@dataclass(frozen=True)
class Requirements:
    host: ToolGroup = ToolGroup()
    gates: dict[str, ToolGroup] = field(default_factory=dict)
    harnesses: dict[str, HarnessRequirements] = field(default_factory=dict)


def read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"{path}: {error}") from error


def _table(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a table")
    return value


def _tool_name(value: object, path: str) -> str:
    if not isinstance(value, str) or not _TOOL_NAME.fullmatch(value):
        raise ConfigError(f"{path} must name a PATH executable (no paths or arguments)")
    return value


def _tool_list(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{path} must be a list of executable names")
    return tuple(_tool_name(tool, path) for tool in value)


def _tools(table: dict[str, object], path: str, extra: tuple[str, ...] = ()) -> ToolGroup:
    unknown = table.keys() - {"required", "optional", *extra}
    if unknown:
        raise ConfigError(f"{path} has unknown keys: {', '.join(sorted(unknown))}")
    return ToolGroup(
        required=_tool_list(table.get("required", []), f"{path}.required"),
        optional=_tool_list(table.get("optional", []), f"{path}.optional"),
    )


def parse_requirements(value: object) -> Requirements:
    table = _table(value, "requirements")
    host = _tools(table, "requirements", ("gate", "harness"))
    gates: dict[str, ToolGroup] = {}
    for name, value in _table(table.get("gate", {}), "requirements.gate").items():
        path = f"requirements.gate.{name}"
        gates[name] = _tools(_table(value, path), path)
    harnesses: dict[str, HarnessRequirements] = {}
    for name, value in _table(table.get("harness", {}), "requirements.harness").items():
        path = f"requirements.harness.{name}"
        group = _table(value, path)
        harnesses[name] = HarnessRequirements(
            _tool_name(group.get("cli"), f"{path}.cli"), _tools(group, path, ("cli",))
        )
    return Requirements(host, gates, harnesses)


def load_project_requirements(path: Path) -> Requirements:
    """Load just the host-tool declarations from a project manifest."""
    if path.is_dir():
        path = path / PROJECT_MANIFEST
    raw = read_toml(path)
    try:
        return parse_requirements(raw.get("requirements", {}))
    except ConfigError as error:
        raise ConfigError(f"{path}: {error}") from error
