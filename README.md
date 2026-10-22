# Assay
Assay measures the value of a context artifact for a coding agent: a skill, a rules file, an instruction file, or a hook.

## Setup

Install [uv](https://docs.astral.sh/uv/), then run `uv sync` at the repository root. `pyproject.toml` pins `harbor==0.24.0` and the repository commits `uv.lock`, so every host gets the same Harbor version.

## Run Harbor

Always run Harbor through uv, so that it uses the locked version:

```sh
uv run harbor --version   # reports 0.24.0
uv run harbor <command>
```

To change the Harbor version, edit the pin in `pyproject.toml`, run `uv lock`, and commit `uv.lock`.

## Run the Phase 0 jobs

The three Phase 0 job files are in `jobs/`. Each runs at `-k 1` with `instruments.agent:InstrumentedClaudeCode`, so every trial, the control included, carries the trace hook. Trials go to `results/<job_name>/`.

| Job file | Trials |
|---|---|
| `jobs/phase0-cross.yaml` | Haiku and Sonnet × control and `instrument-tdd` × TypeScript and Go: 8 |
| `jobs/phase0-extra.yaml` | Haiku × `instrument-tdd` × TypeScript and Go: 2 |
| `jobs/phase0-local.yaml` | the local model × `instrument-tdd` × one task pack: 1 |

**Set the Claude Code version first.** On the day of the smoke trial, read the version of the `stable` channel of Claude Code. Replace the placeholder `SET-ON-SMOKE-TRIAL-DAY` with it in all three job files, in one commit, before the smoke trial runs. In `phase0-cross.yaml` the value is written once and shared through a YAML anchor. A fast test (`tests/test_job_files.py`) fails if the three files do not hold one version. Do not change the version for the remaining Phase 0 trials (PRD, "Version pins").

Launch each job from the repository root:

```sh
uv run harbor run -c jobs/phase0-cross.yaml --dry-run   # check: 8 trials, nothing runs
uv run harbor run -c jobs/phase0-cross.yaml -y
uv run harbor run -c jobs/phase0-extra.yaml -y
```

The hosted jobs read `ANTHROPIC_API_KEY` from the host environment.

**The local job** needs three more steps:

1. Set the task pack. After the hosted trials, replace the marked `tasks:` path in `jobs/phase0-local.yaml` (`SET AFTER THE HOSTED TRIALS`) with the chosen pack.
2. Fill in `jobs/phase0-local.L6.md`, the record of the local setup (L6).
3. Set `ASSAY_LOCAL_BASE_URL` on the host to the server address. This is the only place the address appears (L10). Without it, Harbor stops before any trial runs.

```sh
export ASSAY_LOCAL_BASE_URL=http://<server address>:<port>
uv run harbor run -c jobs/phase0-local.yaml -y
```

## Run the tests

```sh
uv run pytest             # fast tests; skips tests marked `slow`
uv run pytest -m slow     # only the slow tests
uv run pytest -m ""       # all tests, slow included
```

A test that needs Docker or Harbor gets the `@pytest.mark.slow` marker. The default run skips it.
