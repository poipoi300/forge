"""The coverage gate: collect per platform, merge every lane, and hold changed lines to 90%."""

import fnmatch
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from forge.hooks import coverage


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", ".")
    git(repo, "commit", "-qm", message)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git repository on `main` with one base commit, used as the working directory."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    git(root, "commit", "--allow-empty", "-qm", "base")
    git(root, "switch", "-qc", "feature")
    monkeypatch.chdir(root)
    monkeypatch.setenv("DIFF_COVER_COMPARE_BRANCH", "main")
    for name in ("FORGE_COVERAGE_COLLECT", "FORGE_COVERAGE_REPORTS", "FORGE_DIFF_RANGE_NOTATION", "PRE_COMMIT_TO_REF"):
        monkeypatch.delenv(name, raising=False)
    # Project tools come from this interpreter rather than a uv project.
    tools = Path(sys.executable).parent
    monkeypatch.setattr(coverage, "project_tool", lambda tool, *argv: [str(tools / tool), *argv])
    return root


def write_python_project(repo: Path, *, tested: tuple[str, ...], extra_config: str = "") -> None:
    (repo / "pyproject.toml").write_text(
        '[tool.coverage.run]\nrelative_files = true\nbranch = true\nsource = ["."]\n'
        f"{extra_config}\n[tool.coverage.report]\ninclude_namespace_packages = true\n"
    )
    (repo / "app.py").write_text(
        textwrap.dedent(
            """\
            def linux():
                return "linux"


            def windows():
                return "windows"
            """
        )
    )
    calls = "".join(f"    app.{name}()\n" for name in tested)
    (repo / "test_app.py").write_text(f"import app\n\n\ndef test_app():\n    pass\n{calls}")


def write_lane(lanes: Path, name: str, root: str, sep: str, hits: str) -> None:
    lane = lanes / name / "rust"
    lane.mkdir(parents=True)
    (lane / "manifest.txt").write_text(f"{root}{sep}Cargo.toml\n")
    (lane / "lcov.info").write_text(f"SF:{root}{sep}app.rs\n{hits}\nend_of_record\n")


def test_python_changes_pass_only_when_their_lines_are_covered(repo: Path) -> None:
    write_python_project(repo, tested=("linux",))
    commit_all(repo, "half covered")
    assert coverage.main(["--python"]) == 1
    write_python_project(repo, tested=("linux", "windows"))
    commit_all(repo, "fully covered")
    assert coverage.main(["--python"]) == 0


def test_python_lanes_merge_so_a_line_covered_on_any_platform_counts(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    for lane, name in [("linux", "linux"), ("windows", "windows")]:
        write_python_project(repo, tested=(name,))
        monkeypatch.setenv("FORGE_COVERAGE_COLLECT", str(reports / lane))
        assert coverage.main(["--python"]) == 0
        assert (reports / lane / "python.coverage").is_file()
    monkeypatch.delenv("FORGE_COVERAGE_COLLECT")
    write_python_project(repo, tested=())
    commit_all(repo, "add app")
    monkeypatch.setenv("FORGE_COVERAGE_REPORTS", str(reports))
    assert coverage.main(["--python"]) == 0
    shutil.rmtree(reports / "windows")
    assert coverage.main(["--python"]) == 1


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (
            '[tool.coverage.run]\nsource = ["."]\n[tool.coverage.report]\ninclude_namespace_packages = true\n',
            "[run] relative_files = true",
        ),
        (
            (
                '[tool.coverage.run]\nrelative_files = true\nsource_pkgs = ["app"]\n'
                "[tool.coverage.report]\ninclude_namespace_packages = true\n"
            ),
            "[run] source = [<first-party directories>]",
        ),
        (
            (
                '[tool.coverage.run]\nrelative_files = true\nsource = ["app"]\n'
                "[tool.coverage.report]\ninclude_namespace_packages = true\n"
            ),
            "[run] source = [<first-party directories>]",
        ),
        (
            "[tool.coverage.run]\nrelative_files = true\n[tool.coverage.report]\ninclude_namespace_packages = true\n",
            "[run] source = [<first-party directories>]",
        ),
        ('[tool.coverage.run]\nrelative_files = true\nsource = ["."]\n', "[report] include_namespace_packages = true"),
        (
            (
                '[tool.coverage.run]\nrelative_files = true\nsource = [".", "None"]\n'
                "[tool.coverage.report]\ninclude_namespace_packages = true\n"
            ),
            "[run] source = [<first-party directories>]",
        ),
    ],
)
def test_python_collection_requires_portable_and_complete_measurement(
    repo: Path, capsys: pytest.CaptureFixture[str], config: str, message: str
) -> None:
    write_python_project(repo, tested=("linux", "windows"))
    (repo / "pyproject.toml").write_text(config)
    commit_all(repo, "add app")
    with pytest.raises(SystemExit) as exit_info:
        coverage.main(["--python"])
    assert message in str(exit_info.value.code)


def test_a_changed_module_no_test_imports_fails_the_gate(repo: Path) -> None:
    write_python_project(repo, tested=("linux", "windows"))
    (repo / "extra.py").write_text("".join(f"VALUE_{n} = {n}\n" for n in range(12)))
    commit_all(repo, "add an untested module")
    assert coverage.main(["--python"]) == 1


def test_lanes_collected_in_other_checkouts_merge(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_python_project(repo, tested=("linux", "windows"))
    commit_all(repo, "add app")
    other = tmp_path / "other-checkout"
    git(tmp_path, "clone", "-q", str(repo), str(other))
    monkeypatch.chdir(other)
    monkeypatch.setenv("FORGE_COVERAGE_COLLECT", str(tmp_path / "reports" / "lane"))
    assert coverage.main(["--python"]) == 0
    monkeypatch.chdir(repo)
    monkeypatch.delenv("FORGE_COVERAGE_COLLECT")
    monkeypatch.setenv("FORGE_COVERAGE_REPORTS", str(tmp_path / "reports"))
    assert coverage.main(["--python"]) == 0


def test_parallel_mode_shards_become_one_lane_report(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_python_project(repo, tested=("linux", "windows"), extra_config="parallel = true\n")
    commit_all(repo, "add app")
    lane = tmp_path / "reports" / "lane"
    monkeypatch.setenv("FORGE_COVERAGE_COLLECT", str(lane))
    assert coverage.main(["--python"]) == 0
    assert [path.name for path in lane.iterdir()] == ["python.coverage"]
    monkeypatch.delenv("FORGE_COVERAGE_COLLECT")
    monkeypatch.setenv("FORGE_COVERAGE_REPORTS", str(tmp_path / "reports"))
    assert coverage.main(["--python"]) == 0


def test_a_root_level_coverage_module_does_not_shadow_coverage_py(repo: Path) -> None:
    write_python_project(repo, tested=("linux", "windows"))
    (repo / "coverage.py").write_text('raise SystemExit("the project module was imported")\n')
    coverage._require_portable_python_config()


def test_an_untested_module_in_a_namespace_package_fails_the_gate(repo: Path) -> None:
    write_python_project(repo, tested=("linux", "windows"))
    (repo / "pkg").mkdir()
    (repo / "pkg" / "extra.py").write_text("".join(f"VALUE_{n} = {n}\n" for n in range(12)))
    commit_all(repo, "add an untested namespace module")
    assert coverage.main(["--python"]) == 1


def test_spawned_worker_coverage_lands_in_the_lane_report(repo: Path) -> None:
    write_python_project(repo, tested=("linux",), extra_config='parallel = true\nconcurrency = ["multiprocessing"]\n')
    (repo / "test_app.py").write_text(
        "import multiprocessing\n\nimport app\n\n\n"
        "def test_app():\n    app.linux()\n"
        "    worker = multiprocessing.get_context('spawn').Process(target=app.windows)\n"
        "    worker.start()\n    worker.join()\n    assert worker.exitcode == 0\n"
    )
    commit_all(repo, "cover windows in a worker")
    assert coverage.main(["--python"]) == 0
    assert not list(repo.glob(".coverage*")), "no shard lands in the checkout"


def test_staged_or_untracked_changes_block_a_push(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_python_project(repo, tested=("linux", "windows"))
    commit_all(repo, "add app")
    (repo / "app.py").write_text("def linux():\n    return 1\n")
    git(repo, "add", "app.py")
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "feature")
    with pytest.raises(SystemExit):
        coverage.main(["--python"])
    assert "the working tree differs from the pushed commit" in capsys.readouterr().err
    git(repo, "commit", "-qm", "commit the change")
    (repo / "test_extra.py").write_text("def test_extra():\n    pass\n")
    with pytest.raises(SystemExit):
        coverage.main(["--python"])
    assert "?? test_extra.py" in capsys.readouterr().err


def test_an_initial_push_compares_with_the_empty_tree(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_python_project(repo, tested=("linux",))
    commit_all(repo, "half covered")
    empty_tree = subprocess.check_output(["git", "hash-object", "-t", "tree", "/dev/null"], text=True).strip()
    monkeypatch.setenv("DIFF_COVER_COMPARE_BRANCH", empty_tree)
    monkeypatch.setenv("FORGE_DIFF_RANGE_NOTATION", "..")
    assert coverage.main(["--python"]) == 1


def test_a_push_of_another_ref_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_python_project(repo, tested=("linux", "windows"))
    commit_all(repo, "add app")
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "main")
    with pytest.raises(SystemExit):
        coverage.main(["--python"])
    assert "not the checked-out HEAD" in capsys.readouterr().err
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "feature")
    assert coverage.main(["--python"]) == 0


def test_rust_lanes_merge_platform_only_lines_under_repository_paths(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    (repo / "app.rs").write_text("fn common() {}\n#[cfg(windows)] fn windows() {}\n")
    commit_all(repo, "add functions")
    reports = tmp_path / "reports"
    write_lane(reports, "linux", "/runner/work/app", "/", "DA:1,1")
    write_lane(reports, "macos", "/Users/runner/work/app", "/", "DA:1,0")
    write_lane(reports, "windows", r"D:\a\app", "\\", "DA:1,0\nDA:2,0")
    monkeypatch.setenv("FORGE_COVERAGE_REPORTS", str(reports))
    assert coverage.main(["--rust"]) == 1
    assert "app.rs (50.0%): Missing lines 2" in capfd.readouterr().out
    windows = reports / "windows" / "rust" / "lcov.info"
    windows.write_text(windows.read_text().replace("DA:2,0", "DA:2,1"))
    assert coverage.main(["--rust"]) == 0


def test_rust_collection_runs_nextest_under_llvm_cov_from_the_workspace_root(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "app.rs").write_text("fn covered() {}\n")
    commit_all(repo, "add app")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "cargo.log"
    cargo = bin_dir / "cargo"
    cargo.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import sys
            from pathlib import Path
            args = sys.argv[1:]
            with open({str(log)!r}, "a") as log:
                print(" ".join(args), file=log)
            if args[0] == "locate-project":
                print(Path.cwd() / "Cargo.toml")
            else:
                output = Path(args[args.index("--output-path") + 1])
                output.write_text(f"SF:{{Path.cwd() / 'app.rs'}}\\nDA:1,1\\nend_of_record\\n")
            """
        )
    )
    cargo.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert coverage.main(["--rust"]) == 0
    calls = log.read_text().splitlines()
    assert calls[0] == "locate-project --workspace --message-format plain"
    assert calls[1].startswith("llvm-cov nextest --workspace --locked --lcov --output-path ")


def test_exclude_globs_exempt_matching_paths_literally(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    exempt = ["spikes/a/src/main.rs", "spikes/a/src/bin/probe.rs", "spikes/a/src/bin/probe/main.rs"]
    gated = ["spikes/a/src/lib.rs", "spikes/a/src/engine/src/main.rs", "crates/core/src/main.rs"]
    trace = ""
    for source in [*exempt, *gated]:
        (repo / source).parent.mkdir(parents=True, exist_ok=True)
        (repo / source).write_text("fn uncovered() {}\n")
        trace += f"SF:{source}\nDA:1,0\nend_of_record\n"
    commit_all(repo, "add sources")
    lane = tmp_path / "reports" / "only" / "rust"
    lane.mkdir(parents=True)
    (lane / "manifest.txt").write_text(f"{repo / 'Cargo.toml'}\n")
    (lane / "lcov.info").write_text(trace)
    monkeypatch.setenv("FORGE_COVERAGE_REPORTS", str(tmp_path / "reports"))
    globs = ["--exclude-glob", "spikes/*/src/main.rs", "--exclude-glob", "spikes/*/src/bin/**/*"]
    assert coverage.main(["--rust", *globs]) == 1
    reported = {line.split()[0] for line in capfd.readouterr().out.splitlines() if "Missing lines" in line}
    assert reported == set(gated)


def test_exclusions_are_escaped_so_a_path_only_matches_itself(repo: Path) -> None:
    for name in ("a[b]/x.rs", "ab/x.rs"):
        (repo / name).parent.mkdir()
        (repo / name).write_text("")
    (pattern,) = coverage._excluded(["a[[]b]/*.rs"])
    assert fnmatch.fnmatch((repo / "a[b]/x.rs").as_posix(), pattern)
    assert not fnmatch.fnmatch((repo / "ab/x.rs").as_posix(), pattern)


def test_two_dot_notation_compares_a_force_pushed_tip_with_the_replaced_one(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_python_project(repo, tested=("linux",))
    commit_all(repo, "half covered")
    git(repo, "switch", "-qc", "replaced", "main")
    write_python_project(repo, tested=("linux",))
    commit_all(repo, "the same tree, rewritten")
    git(repo, "switch", "-q", "feature")
    monkeypatch.setenv("DIFF_COVER_COMPARE_BRANCH", "replaced")
    # Against the merge base the half-covered file is new; against the replaced tip it is unchanged.
    assert coverage.main(["--python"]) == 1
    monkeypatch.setenv("FORGE_DIFF_RANGE_NOTATION", "..")
    assert coverage.main(["--python"]) == 0


@pytest.mark.parametrize(
    ("argv", "env", "message"),
    [
        ([], {}, "choose at least one language"),
        (["--python", "--fail-under", "80"], {}, "below forge's floor of 90"),
        (["--python"], {"FORGE_DIFF_RANGE_NOTATION": "...."}, "FORGE_DIFF_RANGE_NOTATION"),
        (["--python"], {"FORGE_COVERAGE_COLLECT": "a", "FORGE_COVERAGE_REPORTS": "b"}, "not both"),
    ],
)
def test_rejects_settings_that_would_weaken_or_confuse_the_gate(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    env: dict[str, str],
    message: str,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit) as exit_info:
        coverage.main(argv)
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


def test_reports_mode_needs_at_least_one_lane(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("FORGE_COVERAGE_REPORTS", str(tmp_path / "empty"))
    with pytest.raises(SystemExit):
        coverage.main(["--python"])
    assert "no lane reports" in capsys.readouterr().err


def test_fetches_a_compare_branch_missing_locally(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(repo), str(origin))
    git(repo, "remote", "add", "origin", str(origin))
    write_python_project(repo, tested=("linux", "windows"))
    commit_all(repo, "add app")
    monkeypatch.setenv("DIFF_COVER_COMPARE_BRANCH", "origin/main")
    assert coverage.main(["--python"]) == 0
