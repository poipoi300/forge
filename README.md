# forge

A system for taking projects from specification to shipped software with quality
enforced along the whole lifecycle — and for measuring how changes to the system
itself affect that lifecycle.

## The idea

A project is a **trajectory, not an artifact**. No repo is right after one
iteration; what matters is that every iteration moves inside an area that gets
more and more sharply defined over time. The definition comes from two kinds of
rules:

- **Deterministic gates** — formatters, linters, type checkers, tests,
  diff-coverage thresholds. Cheap, objective, run on every commit and push.
- **Non-deterministic gates** — agent review passes judging design, flexibility,
  performance, and presentation against the project's spec and preferences.
  Subjective, but repeatable enough to trend.

The intended default routine for a new project:

1. **Intake** — collect details, specification, and preferences.
2. **Generate** — produce a repo skeleton: README, CI, gates wired up.
3. **Iterate** — build, test against both rule kinds, edit until compliant.
4. **Tighten** — as the project matures, the acceptable area shrinks: thresholds
   rise, review criteria sharpen, new gates appear.

## North stars

**Flexibility** · **Performance** · **Quality** (including presentation).

A meta-goal sits above these: the system should make it possible to **compare
the impact of different changes** on a project's trajectory. How fast and how
easily can an agent make a correct change in the codebase? Changes to CLAUDE.md,
skills, gate thresholds, or repo structure should be evaluable by their effect
on that answer.

## What's here now

The deterministic gate layer, published for projects to use by reference.

| Piece | Purpose |
|---|---|
| `.pre-commit-hooks.yaml` | forge's gate hooks: repo hygiene, the TODO gate, and tests under coverage with ≥90% required on changed lines |
| `src/forge/hooks/` | The hooks' implementations |
| `.github/workflows/gates.yml` | Reusable CI: every hook on each platform lane, then one coverage gate over all lanes' merged reports |
| `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | forge's own gates, run from this checkout |

## Using forge from a project

A project never copies forge's files. It pins a forge commit in two places
and moves both pins together.

`.pre-commit-config.yaml`:

```yaml
default_install_hook_types: [pre-commit, pre-push]
default_stages: [pre-commit]
repos:
  - repo: https://github.com/poipoi300/forge
    rev: <forge commit SHA>
    hooks:
      - id: trailing-whitespace
      # ... the other hygiene hooks and no-todo ...
      - id: tests-and-diff-coverage
        args: [--python]  # or [--rust], or both
```

`.github/workflows/ci.yml`:

```yaml
on: [push, pull_request]
permissions:
  contents: read
jobs:
  gates:
    uses: poipoi300/forge/.github/workflows/gates.yml@<forge commit SHA>
    with:
      apt-packages: libfoo-dev
      rust: true
      cargo-tools: cargo-nextest@0.9.151,cargo-llvm-cov@0.9.1
    secrets:
      forge-token: ${{ secrets.FORGE_TOKEN }}
```

The workflow's inputs are listed at the top of `gates.yml`. Each lane runs
the commit stage and the push stage on its platform; the coverage hook
collects that platform's reports, and a final job merges every lane's
reports, so a line counts as covered when any platform runs it.

The coverage hook needs coverage.py to record repository-relative paths and
to know the project's first-party code, so lanes merge and a module no test
imports still counts. It refuses to run without both:

```toml
[tool.coverage.run]
relative_files = true
source = ["src"]
```

Locally the hook tests the checked-out tree, so it refuses a push of any
other ref; push from a checkout of what you push. Call `gates.yml` once per
workflow run: its artifact names are per run.

While forge is private, two grants are needed:

- forge's Actions access level lets the owner's other repositories call
  `gates.yml` (Settings → Actions → Access).
- pre-commit clones forge at the pinned commit. Locally it uses your git
  credentials. In CI, pass a read-only token for this repository as the
  `forge-token` secret; only the step that fetches the pinned hooks sees it.
  GitHub withholds secrets from runs for pull requests from forks and from
  Dependabot, so those runs cannot fetch forge until it is public.

## Setup

```sh
uv sync --locked
uv run pre-commit install --install-hooks -t pre-commit -t pre-push
```

Run all gates manually:

```sh
uv run --locked pre-commit run --all-files
uv run --locked pre-commit run --hook-stage pre-push --all-files
```
