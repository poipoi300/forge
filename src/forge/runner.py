"""Execute prompt sequences against an agent harness with step isolation.

Each step runs in its own workspace directory seeded from a copy of the
previous step's result (copy-forward), so every intermediate state stays on
disk for inspection and later steps cannot mutate earlier artifacts:

    runs/<project>/step-00-initial/      <- agent built the initial app here
    runs/<project>/step-01-follow-up-1/  <- copy of step-00, then agent ran
    runs/<project>/meta/step-00-initial.json, .stdout.txt, .stderr.txt

The harness is any CLI configured in forge.toml; the runner substitutes
{prompt} / {prompt_path} into its argv and runs it with the step workspace as
cwd. The runner deliberately knows nothing about what the agent does inside.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from forge.config import ForgeConfig, HarnessConfig
from forge.prompts import ProjectPrompts, PromptStep

# Copied forward between steps only when the agent created them; never seeded
# into a fresh step from the forge repo itself.
_SKIP_COPY = {".git", "node_modules", ".venv", "target", "__pycache__"}


@dataclass(frozen=True)
class StepResult:
    """Outcome of one agent invocation, persisted as the step manifest."""

    project: str
    step_index: int
    step_name: str
    prompt_file: str
    harness: str
    command: tuple[str, ...]
    workspace: str
    started_at: str
    duration_s: float
    exit_code: int | None
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def _seed_workspace(previous: Path | None, workspace: Path) -> None:
    """Create the step workspace, copying the previous step's tree if any."""
    workspace.mkdir(parents=True, exist_ok=False)
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


def _render_command(harness: HarnessConfig, step: PromptStep) -> tuple[str, ...]:
    prompt_text = step.text()
    return tuple(
        part.replace("{prompt}", prompt_text).replace("{prompt_path}", str(step.path.resolve()))
        for part in harness.command
    )


def run_step(
    config: ForgeConfig,
    harness: HarnessConfig,
    project: str,
    step: PromptStep,
    previous_workspace: Path | None,
) -> StepResult:
    """Run one prompt in a fresh workspace seeded from the previous step.

    The manifest and full stdout/stderr land in <project>/meta/ regardless of
    outcome; a crashed or timed-out harness still leaves inspectable state.
    """
    step_dir_name = f"step-{step.index:02d}-{step.name}"
    project_root = config.workspace_root / project
    workspace = project_root / step_dir_name
    meta_dir = project_root / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    _seed_workspace(previous_workspace, workspace)
    command = _render_command(harness, step)

    started = datetime.now(tz=UTC)
    clock_start = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    stdout = b""
    stderr = b""
    try:
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
        timed_out = True
        stdout = e.stdout or b""
        stderr = e.stderr or b""
    except FileNotFoundError:
        stderr = f"harness executable not found: {command[0]}".encode()

    result = StepResult(
        project=project,
        step_index=step.index,
        step_name=step.name,
        prompt_file=str(step.path),
        harness=harness.name,
        command=command,
        workspace=str(workspace),
        started_at=started.isoformat(),
        duration_s=round(time.monotonic() - clock_start, 3),
        exit_code=exit_code,
        timed_out=timed_out,
    )
    (meta_dir / f"{step_dir_name}.json").write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    (meta_dir / f"{step_dir_name}.stdout.txt").write_bytes(stdout)
    (meta_dir / f"{step_dir_name}.stderr.txt").write_bytes(stderr)
    return result


def run_project(
    config: ForgeConfig,
    project_prompts: ProjectPrompts,
    harness_name: str | None = None,
    through_step: int | None = None,
) -> list[StepResult]:
    """Run a project's prompt sequence, stopping early on a failed step.

    Args:
        through_step: Last step index to run (inclusive); None runs all.

    Raises:
        FileExistsError: when the project already has workspaces under
            workspace_root — runs are append-only; delete or rename the old
            run directory to rerun.
    """
    harness = config.harness(harness_name)
    project_root = config.workspace_root / project_prompts.project
    existing = [p.name for p in project_root.glob("step-*")] if project_root.exists() else []
    if existing:
        raise FileExistsError(
            f"{project_root} already contains {', '.join(sorted(existing))}; move or delete the previous run first"
        )

    results: list[StepResult] = []
    previous: Path | None = None
    for step in project_prompts.steps:
        if through_step is not None and step.index > through_step:
            break
        result = run_step(config, harness, project_prompts.project, step, previous)
        results.append(result)
        if not result.ok:
            break
        previous = Path(result.workspace)
    return results
