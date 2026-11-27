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
and moves both pins together. forge is public, so neither needs a
credential. Workflows that call an older `gates.yml` with a `forge-token`
secret must drop that `secrets:` mapping in the same change that moves the
pins, because the current workflow no longer declares it.

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
source = ["src"]  # directories, not package names

[tool.coverage.report]
include_namespace_packages = true
```

Locally the hook tests the checked-out tree, so it refuses a push of any
other ref or with staged, unstaged or untracked changes; push from a clean
checkout of what you push. pre-commit hands a pre-push hook only the first ref of a multi-ref
push, so push one ref at a time. Call `gates.yml` once per
workflow run: its artifact names are per run.

## Setup

```sh
uv sync --locked
uv run pre-commit install --install-hooks -t pre-commit -t pre-push
```

Use `uv run forge doctor` to see which host tools are installed and which
harnesses are available. On Arch Linux, doctor checks the package owner of
the executable selected by `PATH`. A copy with no package owner is marked
`unmanaged`. The report exits with status 1 when a required host or gate
tool is missing. Optional tools, unmanaged tools, and unavailable harnesses
are advisory.

Project manifests (`forge.project.toml`) can use the same declarations as
`forge.toml`. List host executables by name and group gate dependencies under
their gate IDs. A harness is available when its CLI and any tools in its
`required` list are present.

```toml
[requirements]
required = ["git"]
optional = ["gh"]

[requirements.gate.tests-and-diff-coverage]
required = ["git", "uv"]

[requirements.harness.pi]
cli = "pi"
```

Run `uv run forge doctor --manifest <project-directory> --json` to get the
same report for a project's declarations. Project reports check presence and
package ownership by default. With a trusted project and PATH, add
`--trust-manifest` to also run each executable's version command.

Run all gates manually:

```sh
uv run --locked pre-commit run --all-files
uv run --locked pre-commit run --hook-stage pre-push --all-files
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
`runs/my-task/<run_id>/meta/step-00-initial.json` records the Git SHA in
`starting_head` before the harness runs. Follow-ups copy the previous workspace's files without
its Git metadata. Steps without a Git seed record `starting_head` as `null`.

## License

MIT. See [LICENSE](LICENSE).
