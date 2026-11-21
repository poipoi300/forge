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
| `.pre-commit-config.yaml` | Local gates: hygiene + format/lint/types on commit, tests + diff-coverage on push |
| `tools/repo_hygiene.py` | Zero-network reimplementations of the standard pre-commit hygiene hooks |
| `tools/coverage_gate.sh` | Test suite under coverage, then ≥90% coverage required on changed lines |
| `.github/workflows/ci.yml` | The same gates enforced server-side on every push/PR |

## Setup

```sh
uv sync --group dev
uv run pre-commit install --install-hooks -t pre-commit -t pre-push
```

Run all gates manually:

```sh
uv run pre-commit run --all-files
bash tools/coverage_gate.sh
```

## Start a task from a pinned commit

Add a seed for the project in `forge.toml`. For a project with a prompt at
`prompts/my-task.md`, use the following table and replace the example commit
with the full commit ID from your local fixture repository.

```toml
[seed.my-task]
repository = "fixtures/my-task"
commit = "0123456789abcdef0123456789abcdef01234567"
```

Run `uv run forge run my-task`. Relative fixture paths are relative to
`forge.toml`. The initial workspace checks out the pinned commit with a detached
HEAD and contains its Git ancestry. The initial manifest at
`runs/my-task/meta/step-00-initial.json` records the Git SHA in `starting_head`
before the harness runs. Follow-ups copy the previous workspace's files without
its Git metadata. Steps without a Git seed record `starting_head` as `null`.
