"""Execute isolated prompt trajectories and persist their outcomes."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Literal
from uuid import uuid4

from forge.config import ForgeConfig, HarnessConfig
from forge.prompts import ProjectPrompts, PromptStep, validate_project_name
from forge.telemetry import ExitReason, Usage, read_telemetry

# Runtime caches and repository metadata do not belong in the next snapshot.
_SKIP_COPY = {".git", "node_modules", ".venv", "target", "__pycache__"}
_PLACEHOLDER = re.compile(r"\{(prompt|prompt_path|telemetry_path)\}")

type SkipReason = Literal["prior_step_failed", "through_step"]


@dataclass(frozen=True)
class StepResult:
    """Attempted or skipped step, with log names relative to its manifest."""

    run_id: str
    project: str
    harness: str
    step_index: int
    step_name: str
    prompt_file: str
    skip_reason: SkipReason | None = None
    command: tuple[str, ...] | None = None
    workspace: str | None = None
    started_at: str | None = None
    duration_s: float | None = None
    exit_reason: ExitReason | None = None
    exit_code: int | None = None
    stdout_log: str | None = None
    stderr_log: str | None = None
    telemetry: Usage = field(default_factory=Usage)

    @property
    def ok(self) -> bool:
        return self.exit_reason == "ok"

    @property
    def attempted(self) -> bool:
        return self.skip_reason is None

    @property
    def timed_out(self) -> bool:
        return self.exit_reason == "timeout"

    def manifest(self) -> dict[str, object]:
        return {
            **asdict(self),
            "attempted": self.attempted,
            "timed_out": self.timed_out,
            "telemetry": self.telemetry.manifest(),
        }


@dataclass(frozen=True)
class RunResult:
    """One invocation of a project's full or capped prompt sequence."""

    run_id: str
    project: str
    harness: str
    started_at: str
    duration_s: float
    through_step: int | None
    exit_reason: ExitReason
    steps: tuple[StepResult, ...]
    manifest_path: Path

    def manifest(self) -> dict[str, object]:
        usage = [step.telemetry for step in self.steps if step.attempted]
        costs = [measurement.cost_usd for measurement in usage if measurement.cost_usd is not None]
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "project": self.project,
            "harness": self.harness,
            "started_at": self.started_at,
            "duration_s": self.duration_s,
            "through_step": self.through_step,
            "exit_reason": self.exit_reason,
            "attempted_steps": len(usage),
            "skipped_steps": len(self.steps) - len(usage),
            "coverage": {
                "tokens": sum(measurement.tokens is not None for measurement in usage),
                "cost_usd": len(costs),
                "quota_percent": sum(measurement.quota_percent is not None for measurement in usage),
            },
            "cost_usd_per_attempted_task": mean(costs) if costs and len(costs) == len(usage) else None,
            "steps": [step.manifest() for step in self.steps],
        }


def _write_manifest(path: Path, data: dict[str, object]) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _seed_workspace(previous: Path | None, workspace: Path) -> None:
    """Create the step workspace, copying the previous step's tree if any."""
    workspace.mkdir()
    if previous is None:
        return
    for entry in previous.iterdir():
        if entry.name in _SKIP_COPY:
            continue
        target = workspace / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, ignore=shutil.ignore_patterns(*_SKIP_COPY))
        else:
            shutil.copy2(entry, target)


def _render_command(harness: HarnessConfig, step: PromptStep, telemetry_path: Path) -> tuple[str, ...]:
    fields = {
        "prompt": step.text(),
        "prompt_path": str(step.path.resolve()),
        "telemetry_path": str(telemetry_path),
    }
    return tuple(_PLACEHOLDER.sub(lambda match: fields[match[1]], part) for part in harness.command)


def _run_step(
    config: ForgeConfig,
    harness: HarnessConfig,
    step: PromptStep,
    result: StepResult,
    workspace: Path,
    previous: Path | None,
    meta_dir: Path,
) -> StepResult:
    """Attempt a step and persist subprocess logs even on failure."""
    name = workspace.name
    telemetry_path = meta_dir / f"{name}.telemetry.json"
    started = datetime.now(tz=UTC)
    clock_start = time.monotonic()
    command: tuple[str, ...] | None = None
    exit_code: int | None = None
    exit_reason: ExitReason = "harness_error"
    stdout = b""
    stderr = b""
    try:
        _seed_workspace(previous, workspace)
        command = _render_command(harness, step, telemetry_path)
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            timeout=config.step_timeout_s,
            check=False,
        )
        exit_code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as e:
        exit_reason = "timeout"
        stdout = e.stdout or b""
        stderr = e.stderr or b""
    except FileNotFoundError as e:
        stderr = f"harness input or executable not found: {e}".encode(errors="backslashreplace")
    except (OSError, ValueError) as e:
        stderr = f"could not prepare or start harness: {e}".encode(errors="backslashreplace")

    duration = time.monotonic() - clock_start
    telemetry, reported_reason = read_telemetry(
        telemetry_path, stdout if harness.telemetry_format == "claude-json" else b""
    )
    if exit_code is not None:
        exit_reason = "ok" if exit_code == 0 else "crash"
        if reported_reason is not None and exit_code >= 0:
            exit_reason = reported_reason

    stdout_log = f"{name}.stdout.txt"
    stderr_log = f"{name}.stderr.txt"
    (meta_dir / stdout_log).write_bytes(stdout)
    (meta_dir / stderr_log).write_bytes(stderr)
    return replace(
        result,
        command=command,
        workspace=str(workspace) if workspace.is_dir() else None,
        started_at=started.isoformat(),
        duration_s=round(duration, 3),
        exit_reason=exit_reason,
        exit_code=exit_code,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
        telemetry=telemetry,
    )


def run_project(
    config: ForgeConfig,
    project_prompts: ProjectPrompts,
    harness_name: str | None = None,
    through_step: int | None = None,
) -> RunResult:
    """Run a trajectory in a fresh directory and record every planned step.

    through_step is the last allowed step index, inclusive. A failed step
    stops execution because later steps build on the preceding step's output.
    """
    project = project_prompts.project
    validate_project_name(project)
    harness = config.harness(harness_name)
    started = datetime.now(tz=UTC)
    clock_start = time.monotonic()
    run_id = str(uuid4())
    run_root = config.workspace_root.resolve() / project / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    meta_dir = run_root / "meta"
    meta_dir.mkdir()

    results: list[StepResult] = []
    previous: Path | None = None
    exit_reason: ExitReason = "ok"
    for step in project_prompts.steps:
        result = StepResult(run_id, project, harness.name, step.index, step.name, str(step.path))
        workspace = run_root / f"step-{step.index:02d}-{step.name}"
        if through_step is not None and step.index > through_step:
            result = replace(result, skip_reason="through_step")
        elif exit_reason != "ok":
            result = replace(result, skip_reason="prior_step_failed")
        else:
            result = _run_step(config, harness, step, result, workspace, previous, meta_dir)
            assert result.exit_reason is not None
            exit_reason = result.exit_reason
            previous = workspace
        _write_manifest(meta_dir / f"{workspace.name}.json", result.manifest())
        results.append(result)

    run = RunResult(
        run_id=run_id,
        project=project,
        harness=harness.name,
        started_at=started.isoformat(),
        duration_s=round(time.monotonic() - clock_start, 3),
        through_step=through_step,
        exit_reason=exit_reason,
        steps=tuple(results),
        manifest_path=meta_dir / "run.json",
    )
    _write_manifest(run.manifest_path, run.manifest())
    return run
