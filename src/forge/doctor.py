"""Check declared host tools and report harness availability."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from forge.requirements import Requirements, ToolGroup

ToolStatus = Literal["present", "missing", "unmanaged"]


@dataclass(frozen=True)
class ToolReport:
    name: str
    status: ToolStatus
    path: str | None
    version: str | None
    package: str | None
    ownership_unknown: bool
    required: bool
    required_by: tuple[str, ...]
    optional_for: tuple[str, ...]


@dataclass(frozen=True)
class HarnessReport:
    cli: str
    status: Literal["available", "unavailable"]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    tools: tuple[ToolReport, ...]
    harnesses: dict[str, HarnessReport]


def _scopes(requirements: Requirements) -> Iterable[tuple[str, ToolGroup]]:
    yield "host", requirements.host
    for name, tools in requirements.gates.items():
        yield f"gate.{name}", tools
    for name, harness in requirements.harnesses.items():
        yield f"harness.{name}", ToolGroup(harness.tools.required, (harness.cli, *harness.tools.optional))


def _is_arch() -> bool:
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return False
    return release.get("ID") == "arch" or "arch" in release.get("ID_LIKE", "").split()


def _probe(
    command: tuple[str, ...], *, env: dict[str, str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=cwd,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _version(path: str) -> str | None:
    probe = _probe((path, "--version"), env={**os.environ, "LC_ALL": "C"})
    if probe is None or probe.returncode:
        return None
    return next((line.strip() for line in (probe.stdout or probe.stderr).splitlines() if line.strip()), None)


def _tool_report(
    name: str,
    required_by: tuple[str, ...],
    optional_for: tuple[str, ...],
    *,
    arch: bool,
    pacman: str | None,
    probe_version: bool,
) -> ToolReport:
    required = any(not scope.startswith("harness.") for scope in required_by)
    path = shutil.which(name)
    if path is None:
        return ToolReport(name, "missing", None, None, None, False, required, required_by, optional_for)

    path = str(Path(path).absolute())
    version = _version(path) if probe_version else None
    owner = (
        _probe((pacman, "-Qqo", "--", path), env={"PATH": os.defpath, "LC_ALL": "C"}, cwd=Path(pacman).parent)
        if pacman
        else None
    )
    package = owner.stdout.strip() if owner is not None and owner.returncode == 0 else None
    unmanaged = owner is not None and owner.returncode == 1 and "No package owns " in owner.stderr
    return ToolReport(
        name=name,
        status="unmanaged" if unmanaged else "present",
        path=path,
        version=version,
        package=package,
        ownership_unknown=arch and package is None and not unmanaged,
        required=required,
        required_by=required_by,
        optional_for=optional_for,
    )


def check_requirements(requirements: Requirements, *, probe_versions: bool = False) -> DoctorReport:
    """Probe the host once per tool. Version commands require trusted declarations and PATH."""
    required_by: dict[str, set[str]] = defaultdict(set)
    optional_for: dict[str, set[str]] = defaultdict(set)
    for scope, group in _scopes(requirements):
        for tool in group.required:
            required_by[tool].add(scope)
        for tool in group.optional:
            optional_for[tool].add(scope)

    arch = _is_arch()
    # A project can shadow a tool on PATH, including the package manager itself.
    pacman = shutil.which("pacman", path=os.defpath) if arch else None
    tools = tuple(
        _tool_report(
            name,
            tuple(sorted(required_by[name])),
            tuple(sorted(optional_for[name])),
            arch=arch,
            pacman=pacman,
            probe_version=probe_versions,
        )
        for name in sorted(required_by.keys() | optional_for.keys())
    )
    missing = {tool.name for tool in tools if tool.status == "missing"}
    harnesses: dict[str, HarnessReport] = {}
    for name, harness in sorted(requirements.harnesses.items()):
        absent = tuple(sorted(missing.intersection((harness.cli, *harness.tools.required))))
        harnesses[name] = HarnessReport(harness.cli, "unavailable" if absent else "available", absent)

    return DoctorReport(not any(tool.required and tool.name in missing for tool in tools), tools, harnesses)


def terminal_text(value: str) -> str:
    """Render untrusted text without emitting terminal control characters."""
    return "".join(character if character.isprintable() else ascii(character)[1:-1] for character in value)


def format_report(report: DoctorReport) -> str:
    lines: list[str] = []
    for tool in report.tools:
        owner = "package ownership unknown" if tool.ownership_unknown else tool.package
        details = ", ".join(detail for detail in (tool.version, tool.path, owner) if detail)
        policy = "required" if tool.required else "optional"
        lines.append(f"{tool.name}: {tool.status} ({policy})" + (f" — {details}" if details else ""))
    for name, harness in report.harnesses.items():
        detail = f"missing {', '.join(harness.missing)}" if harness.missing else harness.cli
        lines.append(f"harness {name}: {harness.status} ({detail})")
    return "\n".join(map(terminal_text, lines)) if lines else "No host-tool requirements declared."
