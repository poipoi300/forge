# forge

forge takes projects from specification to shipped software with quality
enforced along the whole lifecycle. It produces repos — README, CI, gates,
and this file wired in from the first commit — and then measures how well
those repos hold up as agents iterate on them.

This file is the contributor instructions for coding agents. CLAUDE.md imports
it. Each forge project writes its own project-specific sections and links the
working-rule sections here (A note from the maintainer, Verifying, Commits,
Taste) at its pinned forge commit. You are editing the instructions every
forge project inherits.

## What makes forge special?

A project is a **trajectory, not an artifact**. No repo is right after one
iteration. What matters is that every iteration lands inside an acceptance
area that tightens over time — thresholds rise, review criteria sharpen, new
gates appear. Three things we never compromise on:

### 1. Flexibility

The measure of a forge repo is how fast and how correctly an agent can change
it. Structure that makes the next change harder is a defect even when the
current change works. This is also forge's meta-goal: changes to forge itself
are judged by their effect on agent change velocity in the repos it produces.

### 2. Performance

Gates are only respected when they're fast. Commit-stage gates run in seconds;
anything slow belongs at push or in CI. The same logic applies to generated
code: performance is a feature of the acceptance area, not an optimization
pass at the end.

### 3. Quality, including presentation

Quality covers what deterministic gates can't see: design coherence, naming,
README accuracy, how the thing reads. Presentation is part of the product.
"Works but reads like slop" does not land.

## A note from the maintainer

I like broad, general solutions — but never at the cost of design,
performance, or flexibility. Write structure, not quick fixes. Never implement
"for simplicity" or "defensively"; handle what the spec requires and fail
loudly otherwise. Use the existing, correct tool instead of hand-rolling one.
Never assume data shape or content — verify. No fragile systems: no reliance
on undefined ordering, and every field is identifiable at every point in the
program.

Treat the rest of this document as good defaults, not hard rules. If a rule
here fights the task in front of you, say so loudly and get sign-off before
breaking it.

## A small glossary

- **you** — the agent reading this file and changing the repo.
- **maintainer** — the human directing the work. That's who you're talking to.
- **gate** — one automated quality check. Deterministic gates are exact
  (format, lint, types, tests, coverage); non-deterministic gates are agent
  review passes judged against the spec.
- **acceptance area** — the region of "good enough" defined by all gates
  together. It only ever tightens.
- **trajectory** — a project's path through iterations, evaluated by whether
  it stays inside the acceptance area as the area shrinks.
- **the registry** — `src/forge/gates.py`, the machine-readable list of
  deterministic gates. Later stages reason about gates through it, never by
  grepping config files.
- **project** — a repo that uses forge. It never copies forge's files: its
  `.pre-commit-config.yaml` references forge's hooks, and its CI calls forge's
  reusable workflow, both at a pinned forge commit. Its `AGENTS.md` links this
  file's working-rule sections at that commit.

## The ways to hurt yourself

1. **Weakening a gate to make your change pass.** Don't lower thresholds, add
   excludes, blanket-`noqa`, or `# type: ignore` without a code. The
   acceptance area only tightens; loosening it is a maintainer decision, not
   a side effect of a task. If a gate is genuinely wrong, stop and say so.
2. **Letting the registry drift.** Any change to `.pre-commit-config.yaml`,
   `.pre-commit-hooks.yaml` or `.github/workflows/` updates
   `src/forge/gates.py` and its tests in the same commit. The test suite
   enforces the mirror; a drift is a failing test, not a style issue.
3. **Forgetting projects run this code.** Every project pins a forge commit
   and runs the hooks in `.pre-commit-hooks.yaml`, the workflow in
   `.github/workflows/gates.yml` and the working-rule sections of this file
   from it. A renamed hook id, a changed argument or a removed workflow input
   breaks each project when it moves its pin. Ask whether a change belongs in
   every project or just forge, and keep them free of anything
   machine-specific (paths, model routing, credentials).

## Commands

Everything runs through `uv`; never invoke `pip`, bare `python`, or a venv
directly.

| Task | Command |
|---|---|
| Install / sync deps | `uv sync --group dev` |
| Tests | `uv run pytest -q` |
| Format | `uv run ruff format .` |
| Lint | `uv run ruff check .` (add `--fix` for autofixes) |
| Types | `uv run mypy .` |
| All commit-stage gates | `uv run --locked pre-commit run --all-files` |
| Push-stage gate | `uv run --locked pre-commit run --hook-stage pre-push --all-files` (needs `origin/main`; locally override with `DIFF_COVER_COMPARE_BRANCH=main`) |

Fast gates block commits: hygiene, `ruff format`, `ruff check`,
`mypy --strict`. Slow gates block pushes: pytest under coverage plus
diff-cover requiring **≥90% coverage on changed lines**. CI re-runs everything
on push/PR, so bypassing hooks locally never lands unchecked code. Write code
that passes on the first run instead of iterating against the gates.

## Where code lives

- `src/forge/` — the package. `gates.py` is the registry.
- `src/forge/hooks/` — the gate implementations projects run: repo hygiene,
  the TODO gate, and the coverage gate that merges every platform's reports.
- `.pre-commit-hooks.yaml` — publishes those hooks for projects to pin.
  `.pre-commit-config.yaml` runs the same hooks on forge from this checkout.
- `.github/workflows/gates.yml` — the reusable CI workflow projects call.
  `ci.yml` is forge's own CI, which calls it.
- `test/` — pytest suite. Tests pin behavior, including the registry↔config
  mirror.

## Verifying

- A task is done when the gates pass, not when the edit is written. Run the
  relevant commands and report their real output — never declare success from
  the diff.
- Smallest proof first: the tests you touched, then the commit-stage gates.
- Bug fixes ship with the regression test that would have caught them.
- Test names state the behavior pinned, not the function called.

## Commits

- Small, complete increments: each commit passes all commit-stage gates and
  contains one coherent change with its tests. No WIP commits, no giant final
  commit.
- Imperative mood, capitalized subject, ≤50 chars, no trailing punctuation.
  Body only when it adds what the subject can't: wrap at 72, blank line after
  the subject, explain why rather than what.

## Taste

- Guard clauses first; handle edge cases early and exit.
- Abstract only when there is churn, or when one logical change would
  otherwise require edits in multiple files. Premature abstraction is a
  defect.
- Prefer renaming to explaining. Comments carry constraints the code can't
  say — invariants, external contracts, non-obvious "why". Never narrate the
  change you just made or reference the session that produced it.
- Types exhaustive but non-restrictive: `Iterable` over `list` for
  parameters, Python 3.12+ syntax.
- No `try/except` that swallows errors, no dead config knobs, no
  commented-out code, no debug statements.
