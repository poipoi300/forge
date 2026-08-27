"""Discover project prompt sequences in the prompts/ folder.

Naming contract: <project>.md is the initial prompt, <project>_follow-up_<n>.md
the sequential follow-ups. A sequence is the initial prompt plus follow-ups in
ascending n with no gaps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FOLLOW_UP = re.compile(r"^(?P<project>.+)_follow-up_(?P<n>\d+)$")


class PromptError(Exception):
    """The prompts folder violates the naming contract."""


@dataclass(frozen=True)
class PromptStep:
    """One prompt in a project's sequence.

    Attributes:
        index: 0 for the initial prompt, n for follow-up n.
        name: Step slug used in workspace directory names.
        path: The prompt .md file.
    """

    index: int
    name: str
    path: Path

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class ProjectPrompts:
    """A project's full prompt sequence, initial first."""

    project: str
    steps: tuple[PromptStep, ...]


def discover_projects(prompts_dir: Path) -> dict[str, ProjectPrompts]:
    """Map project name -> ordered prompt sequence for every project found.

    Raises:
        PromptError: on a follow-up without an initial prompt, or a gap in
            follow-up numbering (e.g. 1 and 3 without 2).
    """
    initials: dict[str, Path] = {}
    follow_ups: dict[str, dict[int, Path]] = {}
    for path in sorted(prompts_dir.glob("*.md")):
        match = _FOLLOW_UP.match(path.stem)
        if match:
            follow_ups.setdefault(match["project"], {})[int(match["n"])] = path
        else:
            initials[path.stem] = path

    orphans = sorted(set(follow_ups) - set(initials))
    if orphans:
        raise PromptError(f"follow-ups without an initial prompt: {', '.join(orphans)}")

    projects: dict[str, ProjectPrompts] = {}
    for project, initial_path in initials.items():
        numbered = follow_ups.get(project, {})
        expected = list(range(1, len(numbered) + 1))
        if sorted(numbered) != expected:
            raise PromptError(f"{project}: follow-up numbers {sorted(numbered)} are not 1..{len(numbered)}")
        steps = [PromptStep(0, "initial", initial_path)]
        steps.extend(PromptStep(n, f"follow-up-{n}", numbered[n]) for n in expected)
        projects[project] = ProjectPrompts(project=project, steps=tuple(steps))
    return projects
