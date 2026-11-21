"""The work-tracking gate: known work lives in issues, never in markers or files."""

from pathlib import Path

import pytest

from forge.hooks import todo

WORDS = ["TODO", "FIXME", "XXX", "HACK"]
LEADERS = ["#", "//", "/*", "<!--", "--", ";", "%", "x = 1  #", "call(); //", 'say("#"); //']


def check(tmp_path: Path, name: str, text: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    status = todo.main([str(path)])
    return status, capsys.readouterr().out


@pytest.mark.parametrize("word", WORDS)
@pytest.mark.parametrize("leader", LEADERS)
def test_rejects_every_marker_after_any_comment_leader(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], leader: str, word: str
) -> None:
    status, out = check(tmp_path, "code.txt", f"first line\n{leader} {word}: later\n", capsys)
    assert status == 1
    assert out.startswith(f"{tmp_path / 'code.txt'}:2: {word} comment")


@pytest.mark.parametrize(
    "line",
    [
        "# {word}(poipoi300/forge#2): handle the empty case",
        "// See poipoi300/forge#2. {word}: drop this branch",
        "# {word} https://github.com/poipoi300/forge/issues/2",
    ],
)
def test_rejects_markers_that_link_an_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str) -> None:
    status, _ = check(tmp_path, "linked.py", line.format(word=WORDS[0]) + "\n", capsys)
    assert status == 1


@pytest.mark.parametrize(
    "text",
    [
        "# Empty input is rejected upstream. See poipoi300/forge#2.\n",
        "The gate rejects {word} comments in code.\n",
        "# a todo list widget\n",
        "runtime=$(mktemp -d /tmp/x.XXXXXX)  # private dir\n",
        "# {word}_LIMIT is the name of the constant\n",
        "| --- | --- |\n",
    ],
)
def test_accepts_comments_and_prose_without_a_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    assert check(tmp_path, "notes.md", text.format(word=WORDS[0]), capsys) == (0, "")


@pytest.mark.parametrize(
    "name",
    ["TODO", "TODO.md", "docs/todo.txt", "Todos.org", "notes/FIXME.md", "TODO.rst", "todo.markdown", "TODO.adoc"],
)
def test_rejects_work_tracking_files(tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str) -> None:
    status, out = check(tmp_path, name, "nothing to see\n", capsys)
    assert status == 1
    assert out == f"{tmp_path / name}: work-tracking file; track the work in issues\n"


@pytest.mark.parametrize(
    "name",
    ["todo.py", "src/todos.rs", "fixme.ts", "todo_view.py", "mastodon.md", "src/hackathon.rs", "TODOLIST_SPEC.md"],
)
def test_accepts_files_that_only_contain_the_word(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    assert check(tmp_path, name, "fine\n", capsys) == (0, "")


@pytest.mark.parametrize(
    ("text", "line"),
    [
        ("/*\n  {word}: drop the fallback\n*/\n", 2),
        ("/**\n * Parses input.\n * {word}\n */\n", 3),
        ("<!--\n{word}: rewrite\n-->\n", 2),
        ("let x = 1; /* {word} */ let y = 2;\n", 1),
    ],
)
def test_rejects_markers_anywhere_in_a_block_comment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, line: int
) -> None:
    status, out = check(tmp_path, "block.txt", text.format(word=WORDS[0]), capsys)
    assert status == 1
    assert out.startswith(f"{tmp_path / 'block.txt'}:{line}: {WORDS[0]} comment")


@pytest.mark.parametrize(
    "text",
    [
        'url = "https://example.com/docs#{word}"\n',
        'let path = "a//{word}";\n',
        '/* sized */ let label = "{word}";\n',
        "/* one */ value = {word}_LIMIT; /* two */\n",
        'let open = "/* not a comment";\nlet label = "{word}";\n',
    ],
)
def test_accepts_markers_in_strings_and_code_outside_comments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    assert check(tmp_path, "code.rs", text.format(word=WORDS[0]), capsys) == (0, "")


@pytest.mark.parametrize(
    ("name", "text", "line"),
    [
        ("escape.rs", 'let dir = "C:\\\\"; // {word}: handle drives\n', 1),
        ("nested.rs", "/* outer /* inner */ still a comment {word} */\n", 1),
        ("nested.rs", "/* outer /* inner */ */ fn f() {{}} // {word}\n", 1),
        ("lib.py", 'text = "a"  # {word}: tidy\n', 1),
    ],
)
def test_finds_markers_past_escapes_and_nested_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, text: str, line: int
) -> None:
    status, out = check(tmp_path, name, text.format(word=WORDS[0]), capsys)
    assert status == 1
    assert out.startswith(f"{tmp_path / name}:{line}: {WORDS[0]} comment")


@pytest.mark.parametrize(
    "text",
    [
        "MARK = '# {word}'\n",
        'HELP = """\nLines like // {word} are examples.\n"""\n',
        'def f():\n    """Explain the # {word} convention."""\n',
    ],
)
def test_python_strings_and_docstrings_are_not_comments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    assert check(tmp_path, "lib.py", text.format(word=WORDS[0]), capsys) == (0, "")


def test_a_python_comment_after_a_unicode_line_separator_in_a_string_is_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out = check(tmp_path, "lib.py", f'TEXT = "a\u2028b"\n# {WORDS[0]}: later\n', capsys)
    assert status == 1
    assert out.startswith(f"{tmp_path / 'lib.py'}:2: {WORDS[0]} comment")


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("let quote = '\"'; // {word}: escape it\n", True),
        ("let b = b'\\''; // {word}\n", True),
        ('let help = r#"\nline // {word} in a raw string\n"#;\n', False),
        ('let help = "first\n// {word} in a multiline string\n";\n', False),
        ("fn f<'a>(x: &'a str) {{}} // {word}\n", True),
        ("let x = 1; # {word} is no Rust comment\n", False),
    ],
)
def test_rust_files_lex_rust_literals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, flagged: bool
) -> None:
    status, _ = check(tmp_path, "lib.rs", text.format(word=WORDS[0]), capsys)
    assert status == int(flagged)


def test_reports_every_offence_in_one_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text = "".join(f"# {word}\n" for word in WORDS)
    status, out = check(tmp_path, "TODO.md", text, capsys)
    assert status == 1
    assert len(out.splitlines()) == len(WORDS) + 1


def test_reads_files_that_are_not_utf8(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "latin1.txt"
    path.write_bytes(b"caf\xe9\n# " + WORDS[1].encode() + b"\n")
    assert todo.main([str(path)]) == 1
