"""Prompt discovery: the naming contract holds for the shipped suite and edge cases."""

from pathlib import Path

import pytest

from forge.prompts import PromptError, discover_projects

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_shipped_prompt_suite_discovers_cleanly() -> None:
    projects = discover_projects(REPO_ROOT / "prompts")
    assert len(projects) == 12
    for project in projects.values():
        assert project.steps[0].name == "initial"
        assert [s.index for s in project.steps] == list(range(len(project.steps)))


def test_follow_up_numbering_gap_raises(tmp_path: Path) -> None:
    (tmp_path / "app.md").write_text("build\n", encoding="utf-8")
    (tmp_path / "app_follow-up_1.md").write_text("more\n", encoding="utf-8")
    (tmp_path / "app_follow-up_3.md").write_text("even more\n", encoding="utf-8")
    with pytest.raises(PromptError, match=r"not 1\.\.2"):
        discover_projects(tmp_path)


def test_orphan_follow_up_raises(tmp_path: Path) -> None:
    (tmp_path / "ghost_follow-up_1.md").write_text("more\n", encoding="utf-8")
    with pytest.raises(PromptError, match="ghost"):
        discover_projects(tmp_path)


def test_project_with_no_follow_ups_is_single_step(tmp_path: Path) -> None:
    (tmp_path / "solo.md").write_text("build\n", encoding="utf-8")
    projects = discover_projects(tmp_path)
    assert [s.name for s in projects["solo"].steps] == ["initial"]
