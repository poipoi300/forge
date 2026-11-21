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

The first slice: repo skeleton plus the deterministic gate layer, ported from a
proven setup.

| Piece | Purpose |
|---|---|
| `.pre-commit-config.yaml` | Hygiene, format, lint and types on commit. Security scans, tests and diff coverage on push. |
| `.semgrep.yml` | Versioned static analysis rules for Python, JavaScript, TypeScript, and Rust |
| `tools/repo_hygiene.py` | Zero-network reimplementations of the standard pre-commit hygiene hooks |
| `tools/coverage_gate.sh` | Test suite under coverage, then ≥90% coverage required on changed lines |
| `.github/workflows/ci.yml` | Runs the pre-push hooks and the lint and type checks on main pushes and pull requests |

## Setup

```sh
uv sync --locked --group dev
uv run --locked pre-commit install --install-hooks -t pre-commit -t pre-push
```

When starting a project from the skeleton, keep `.pre-commit-config.yaml`,
`.github/workflows/ci.yml`, and `.semgrep.yml` together. Install `gitleaks`,
`osv-scanner`, and `semgrep` on `PATH` locally. The workflow installs the
versions CI uses. Gitleaks scans local branch and tag histories and redacts
detected values. OSV-Scanner checks resolved dependencies, including
`uv.lock`, `bun.lock`, and `Cargo.lock`, against the online OSV database.
Semgrep runs the checked-in rules with telemetry disabled. Findings fail the
push and CI gates. Push the checked-out revision with no staged changes, one
ref at a time. Pre-commit exposes only the first ref to the source and coverage
gates.

Run both gate stages manually.

```sh
uv run --locked pre-commit run --all-files
uv run --locked pre-commit run --hook-stage pre-push --all-files
```
