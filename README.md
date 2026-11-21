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

## Evaluation runs

List the prompt projects with `uv run forge list`. Run two independent
trajectories with `uv run forge run habit-tracker --repeat 2`. A later
invocation of the same project also starts a fresh run. Add
`--through-step 1` to attempt only the initial prompt and first follow-up.

Each run writes `runs/<project>/<run_id>/meta/run.json`. Its versioned
manifest includes all planned steps, their outcomes, and the run's wall time.
The `meta` directory also contains each step's manifest and the stdout and
stderr logs for attempted steps. Log paths are relative to `meta`.
Successful steps seed the next workspace. After a failure, remaining steps
within the requested limit are marked `prior_step_failed`. Steps beyond the
limit are marked `through_step`. Skips have a null exit reason and no
workspace or logs.

Attempt outcomes are `ok`, `timeout`, `crash` (a signal or unclassified
nonzero exit), `gate_fail` (a reported gate rejection), and
`harness_error` (setup, launch, or a reported harness error). The run takes
the first failure's reason, or `ok` when all attempts succeed.

Harness wrappers can include `{telemetry_path}` in their command and write a
JSON object at that path before returning. Optional fields are `tokens`
(nonnegative integer), `cost_usd` (measured dollars), `quota_percent`
(measured share of a quota consumed by the attempt, from 0 to 100), and
`exit_reason` (`gate_fail` or `harness_error`). Forge also reads token
counts from Claude Code's single-invocation JSON results when
`telemetry_format = "claude-json"` is set. Claude reports its CLI dollar
total as a client-side estimate, so Forge leaves that measurement unknown
unless a wrapper supplies it.
[Claude Code cost tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking)

Unknown measurements are null with a false coverage flag. A measured zero
has a true flag. Run-level coverage counts attempts with a measurement for
each unit. `cost_usd_per_attempted_task` divides measured dollars by all
attempted steps, including failures, and is null when any attempt lacks
dollar coverage or when there were no attempts.
