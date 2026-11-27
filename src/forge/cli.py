"""forge command-line interface.

uv run forge list
uv run forge doctor
uv run forge run habit-tracker url-shortener
uv run forge run --all
uv run forge run --prompt "build me a pomodoro timer" --name pomodoro
uv run forge run habit-tracker --harness pi --repeat 2 --through-step 1
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import mkdtemp

from forge.config import ConfigError, load_config
from forge.doctor import check_requirements, format_report, terminal_text
from forge.prompts import ProjectPrompts, PromptError, PromptStep, discover_projects, validate_project_name
from forge.requirements import load_project_requirements
from forge.runner import RunResult, run_project


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _report(run: RunResult) -> None:
    print(f"{run.project} {run.run_id}: {run.exit_reason} -> {run.manifest_path}")
    for step in run.steps:
        label = f"  step {step.step_index} ({step.step_name})"
        if not step.attempted:
            print(f"{label}: skipped ({step.skip_reason})")
            continue
        cost = step.telemetry.cost_usd
        cost_label = "unknown USD cost" if cost is None else f"{cost:g} USD"
        print(f"{label}: {step.exit_reason} in {step.duration_s}s ({cost_label}) -> {step.workspace}")


def _custom_project(prompt_text: str, name: str, scratch_dir: Path) -> ProjectPrompts:
    """Wrap an ad-hoc prompt as a single-step project, persisting the text."""
    validate_project_name(name)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = Path(mkdtemp(prefix="prompt-", dir=scratch_dir)) / "prompt.md"
    prompt_path.write_text(prompt_text + "\n", encoding="utf-8")
    return ProjectPrompts(project=name, steps=(PromptStep(0, "initial", prompt_path),))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list discovered projects and their step counts")
    doctor = sub.add_parser("doctor", help="report host-tool requirements and harness availability")
    doctor.add_argument("--json", action="store_true", help="emit the machine-readable report")
    doctor.add_argument("--manifest", type=Path, help="check a forge.project.toml file or project directory")
    doctor.add_argument(
        "--trust-manifest", action="store_true", help="allow version probes for executables declared by this project"
    )

    run = sub.add_parser("run", help="run prompt sequences through an agent harness")
    run.add_argument("projects", nargs="*", help="project names from prompts/")
    run.add_argument("--all", action="store_true", help="run every discovered project")
    run.add_argument("--prompt", help="ad-hoc prompt text instead of a discovered project")
    run.add_argument("--name", help="project name for --prompt (required with it)")
    run.add_argument("--harness", help="harness from forge.toml (default: [runner] default_harness)")
    run.add_argument("--through-step", type=int, help="stop after this step index (0 = initial only)")
    run.add_argument("--repeat", type=int, default=1, help="number of independent runs per project (default: 1)")

    args = parser.parse_args(argv)
    root = _repo_root()
    try:
        if args.command == "doctor":
            manifest: Path | None = args.manifest
            if args.trust_manifest and manifest is None:
                doctor.error("--trust-manifest requires --manifest")
            requirements = load_config(root).requirements if manifest is None else load_project_requirements(manifest)
            report = check_requirements(requirements, probe_versions=manifest is None or args.trust_manifest)
            print(json.dumps(asdict(report)) if args.json else format_report(report))
            return 0 if report.ok else 1
        config = load_config(root)
        projects = discover_projects(root / "prompts")
    except (ConfigError, PromptError) as e:
        print(f"error: {terminal_text(str(e))}", file=sys.stderr)
        return 2

    if args.command == "list":
        for name in sorted(projects):
            print(f"{name}: {len(projects[name].steps)} steps")
        return 0

    if args.repeat < 1:
        run.error("--repeat must be a positive integer")

    if args.prompt:
        if args.projects or args.all:
            print("error: --prompt cannot be combined with project names or --all", file=sys.stderr)
            return 2
        if not args.name:
            print("error: --prompt requires --name", file=sys.stderr)
            return 2
        try:
            selected = [_custom_project(args.prompt, args.name, config.workspace_root / "_custom-prompts")]
        except (PromptError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    elif args.all:
        selected = [projects[name] for name in sorted(projects)]
    elif args.projects:
        unknown = sorted(set(args.projects) - set(projects))
        if unknown:
            print(f"error: unknown projects: {', '.join(unknown)} (see `forge list`)", file=sys.stderr)
            return 2
        selected = [projects[name] for name in args.projects]
    else:
        print("error: give project names, --all, or --prompt", file=sys.stderr)
        return 2

    any_failed = False
    for project_prompts in selected:
        for _ in range(args.repeat):
            try:
                result = run_project(config, project_prompts, args.harness, args.through_step)
            except (ConfigError, PromptError, OSError) as e:
                print(f"error: {project_prompts.project}: {e}", file=sys.stderr)
                any_failed = True
                break
            _report(result)
            any_failed = any_failed or result.exit_reason != "ok"
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
