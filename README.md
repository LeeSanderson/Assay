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

**Set the Claude Code version first.** On the day of the smoke trial, read the version of the `stable` channel of Claude Code. Replace the placeholder `SET-ON-SMOKE-TRIAL-DAY` with it in all three job files, in one commit, before the smoke trial runs. In `phase0-cross.yaml` the value is written once and shared through a YAML anchor. A fast test (`tests/test_job_files.py`) fails if the three files do not hold one version. `uv run assay run` stops before Harbor starts if a job's version is not `stable`, `latest` or `X.Y.Z` (for example the placeholder, or no version), and the agent's `setup()` makes the same check for a direct `harbor run`. Do not change the version for the remaining Phase 0 trials (PRD, "Version pins").

Launch each job from the repository root with `assay run`, the only supported way to start a job (ADR 0002). It gives the job file to `harbor run` with `-c`, and every other option goes to Harbor unchanged:

```sh
uv run assay run -c jobs/phase0-cross.yaml --dry-run   # check: 8 trials, nothing runs
uv run assay run -c jobs/phase0-cross.yaml -y
uv run assay run -c jobs/phase0-extra.yaml -y
```

The hosted jobs read `ANTHROPIC_API_KEY` from the host environment.

**Re-running a job.** A re-run with the same job file resumes the job in `results/<job_name>/`: Harbor keeps the finished trials and runs the rest. Harbor cannot resume a job whose job file has changed. In that case `assay run` stops before Harbor starts and names the folder. To delete the folder and start fresh, add `--overwrite`:

```sh
uv run assay run -c jobs/phase0-cross.yaml -y --overwrite   # deletes results/phase0-cross/ without asking, then runs
uv run assay run -c jobs/phase0-cross.yaml --overwrite --dry-run   # says what it would delete; deletes nothing
```

`--overwrite` deletes the folder even when the job file has not changed. A `--dry-run` without `--overwrite` only warns about a changed job file. `--job-name` and `-o`/`--jobs-dir` on the command line change the folder, as they do in Harbor.

**The local job** needs three more steps:

1. Set the task pack. After the hosted trials, replace the marked `tasks:` path in `jobs/phase0-local.yaml` (`SET AFTER THE HOSTED TRIALS`) with the chosen pack.
2. Fill in `jobs/phase0-local.L6.md`, the record of the local setup (L6).
3. Set `ASSAY_LOCAL_BASE_URL` on the host to the server address. This is the only place the address appears (L10). Without it, Harbor stops before any trial runs.

```sh
export ASSAY_LOCAL_BASE_URL=http://<server address>:<port>
uv run assay run -c jobs/phase0-local.yaml -y
```

## Check `trajectory.py` by hand

A person labels the ten hosted trials and compares the labels with `trajectory.py`, for test-first order and for red-to-green order and the TDD loop. The full procedure is in the PRD, section 5, "How a person checks `trajectory.py`" and its red-to-green extension. In short:

1. Run `replay.py` and `agent_runs.py` on the job, so each trial has `analysis/<job-id>/<trial>/replay.jsonl` and `agent-runs.jsonl`. Harbor deletes each trial's task image, so replay rebuilds it from the pack's Dockerfile, whose base image is pinned by digest. `replay-works.json` records the rebuilt image ID and that base image.
2. Print the neutral listing of each trial with `jq` (`jq` must be on the PATH). The listing gives no class, no seen state, no verdict, and no count. The header of `analyze/listing.jq` explains each field.

   ```sh
   jq -r \
     --slurpfile trace  results/<job-id>/<trial>/artifacts/logs/artifacts/trace/trace.jsonl \
     --slurpfile replay analysis/<job-id>/<trial>/replay.jsonl \
     --slurpfile runs   analysis/<job-id>/<trial>/agent-runs.jsonl \
     -f analyze/listing.jq results/<job-id>/<trial>/agent/trajectory.json
   ```

3. Copy `labeling/sheet-template.csv` and fill one row per trial before `trajectory.py` runs. Use the trial folder name for `trial`. For test-first order, give the verdict, the two anchors (`step_id`, position, and path of the first test write and of the first implementation write), and a note. For red-to-green order, give the verdict, the `tool_use_id` of the first seen red and of the first seen green, the three counts of the TDD loop, and a note. Leave a cell blank when there is no such write or seen state. You can read `trajectory.json` when the listing is not sufficient.
4. Run `trajectory.py` and compare. The command prints each difference and exits with 1 when any trial differs:

   ```sh
   uv run python -m analyze.trajectory results/<job-id>/*/ > trajectory.jsonl
   uv run python -m analyze.compare_labels <sheet.csv> trajectory.jsonl
   ```

5. For each difference, find the cause and fix the script, the label, or the rule in the PRD. Record each correction in a copy of `labeling/corrections-template.csv` (`corrected` is `script`, `label`, or `rule`). Repeat until one full pass over the ten trials gives no difference for each metric.

## Write the Phase 0 summary

After `replay.py` and `agent_runs.py` have run on each job, write the summary of every Phase 0 acceptance value. It goes to `analysis/phase0-summary.md` (for a person) and `analysis/phase0-summary.json`, and the command writes nothing else:

```sh
uv run python -m analyze.summary results/phase0-cross results/phase0-extra results/phase0-local
```

## Run the tests

```sh
uv run pytest             # fast tests; skips tests marked `slow`
uv run pytest -m slow     # only the slow tests
uv run pytest -m ""       # all tests, slow included
```

A test that needs Docker or Harbor gets the `@pytest.mark.slow` marker. The default run skips it.
