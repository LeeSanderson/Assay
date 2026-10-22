# Assay
Assay measures the value of a context artifact for a coding agent: a skill, a rules file, an instruction file, or a hook.

## Setup

Install [uv](https://docs.astral.sh/uv/), then run `uv sync` at the repository root. `pyproject.toml` pins `harbor==0.24.0` and the repository commits `uv.lock`, so every host gets the same Harbor version.

The analysis also needs these tools on the host:

- Docker, for the trials and for the replay of the trace snapshots.
- `jq` on the PATH, for the neutral listing of the person check (for example, `winget install jqlang.jq`).

The commands in this README are for PowerShell 7 (`pwsh`), run from the repository root. Use PowerShell 7 and not Windows PowerShell 5.1: in PowerShell 7, `>` writes UTF-8 with no BOM, which the analysis scripts can read.

## Run Harbor

Always run Harbor through uv, so that it uses the locked version:

```powershell
uv run harbor --version   # reports 0.24.0
uv run harbor <command>
```

To change the Harbor version, edit the pin in `pyproject.toml`, run `uv lock`, and commit `uv.lock`.

## The analysis process

Phase 0 has six stages. Do them in this order, one job at a time for stages 2 to 4. Each stage reads the output of the stages before it.

| Stage | Command | Reads | Writes |
|---|---|---|---|
| 1. Run the jobs | `uv run assay run` | `jobs/*.yaml` | `results/<job-id>/<trial>/` |
| 2. Check the trace | `uv run assay trace-check` | `results/<job-id>/` | the console only |
| 3. Replay the trace snapshots | `uv run assay replay` | `results/<job-id>/`, the task packs | `analysis/<job-id>/<trial>/replay.jsonl`, `replay-works.json` |
| 4. Cross-check the agent's test runs | `uv run assay agent-runs` | `results/`, `replay.jsonl` | `analysis/<job-id>/<trial>/agent-runs.jsonl`, `cross-check.json` |
| 5. Check `trajectory.py` by hand | `jq`, `uv run assay trajectory`, `uv run assay compare-labels` | `results/`, `analysis/`, the labeling sheet | `analysis/<job-id>/<trial>/listing.txt`, `analysis/trajectory.jsonl` |
| 6. Write the Phase 0 summary | `uv run assay summary` | `results/`, `analysis/` | `analysis/phase0-summary.md`, `phase0-summary.json` |

`assay` is the one tool for every stage except the `jq` listing of stage 5. `uv run assay` with no subcommand lists the subcommands, and `uv run assay <subcommand> --help` shows the arguments of one.

`<job-id>` is the folder name of the job in `results/`, for example `phase0-cross`. A trial folder is a folder in `results/<job-id>/` that holds a `lock.json`. Git ignores `results/` and `analysis/`, so the commands below also keep the filled labeling sheet and the corrections in `analysis/`.

Most commands below use the variable `$job`. Set it to the job you analyze:

```powershell
$job = 'phase0-cross'   # or phase0-extra, or phase0-local
```

### Stage 1: Run the jobs

The three Phase 0 job files are in `jobs/`. Each runs at `-k 1` with `instruments.agent:InstrumentedClaudeCode`, so every trial, the control included, carries the trace hook. Trials go to `results/<job_name>/`.

| Job file | Trials |
|---|---|
| `jobs/phase0-cross.yaml` | Haiku and Sonnet × control and `instrument-tdd` × TypeScript and Go: 8 |
| `jobs/phase0-extra.yaml` | Haiku × `instrument-tdd` × TypeScript and Go: 2 |
| `jobs/phase0-local.yaml` | the local model × `instrument-tdd` × one task pack: 1 |

**Set the Claude Code version first.** On the day of the smoke trial, read the version of the `stable` channel of Claude Code. Replace the placeholder `SET-ON-SMOKE-TRIAL-DAY` with it in all three job files, in one commit, before the smoke trial runs. In `phase0-cross.yaml` the value is written once and shared through a YAML anchor. A fast test (`tests/test_job_files.py`) fails if the three files do not hold one version. `uv run assay run` stops before Harbor starts if a job's version is not `stable`, `latest` or `X.Y.Z` (for example the placeholder, or no version), and the agent's `setup()` makes the same check for a direct `harbor run`. Do not change the version for the remaining Phase 0 trials (PRD, "Version pins").

Launch each job from the repository root with `assay run`, the only supported way to start a job (ADR 0002). It gives the job file to `harbor run` with `-c`, and every other option goes to Harbor unchanged:

```powershell
uv run assay run -c jobs/phase0-cross.yaml --dry-run   # check: 8 trials, nothing runs
uv run assay run -c jobs/phase0-cross.yaml -y --debug
uv run assay run -c jobs/phase0-extra.yaml -y --debug
```

The hosted jobs read `ANTHROPIC_API_KEY` from the host environment:

```powershell
$env:ANTHROPIC_API_KEY = '<your key>'
```

`--debug` shows Harbor's debug log on the console. Harbor writes the same log, at debug level, to `results/<job_name>/job.log` and `<trial>/trial.log` with or without the flag. The console shows only "Running agent" while Claude Code works; to follow the agent, tail `results/<job_name>/<trial>/agent/claude-code.txt`, which Harbor writes while the agent runs (one JSON event per line):

```powershell
Get-Content results\phase0-cross\*\agent\claude-code.txt -Wait -Tail 20
```

**Re-running a job.** A re-run with the same job file resumes the job in `results/<job_name>/`: Harbor keeps the finished trials and runs the rest. Harbor cannot resume a job whose job file has changed. In that case `assay run` stops before Harbor starts and names the folder. To delete the folder and start fresh, add `--overwrite`:

```powershell
uv run assay run -c jobs/phase0-cross.yaml -y --debug --overwrite   # deletes results/phase0-cross/ without asking, then runs
uv run assay run -c jobs/phase0-cross.yaml --overwrite --dry-run   # says what it would delete; deletes nothing
```

`--overwrite` deletes the folder even when the job file has not changed. A `--dry-run` without `--overwrite` only warns about a changed job file. `--job-name` and `-o`/`--jobs-dir` on the command line change the folder, as they do in Harbor.

**The local job** needs three more steps:

1. Set the task pack. After the hosted trials, replace the marked `tasks:` path in `jobs/phase0-local.yaml` (`SET AFTER THE HOSTED TRIALS`) with the chosen pack.
2. Fill in `jobs/phase0-local.L6.md`, the record of the local setup (L6).
3. Set `ASSAY_LOCAL_BASE_URL` on the host to the server address. This is the only place the address appears (L10). Without it, Harbor stops before any trial runs.

```powershell
$env:ASSAY_LOCAL_BASE_URL = 'http://<server address>:<port>'
uv run assay run -c jobs/phase0-local.yaml -y --debug
```

### Stage 2: Check the trace

The trace check makes sure that the trace hook worked in each trial (PRD section 5, "The trace check"). It prints one JSON line for each trial, with the names of the checks that the trial fails:

```powershell
uv run assay trace-check results\$job
```

An empty `failed_checks` list means that the trial passes. A trial that fails is a failure of the infrastructure: run it again in the same cell. The command stops with exit code 2 if the trials of the job do not share one Claude Code version.

### Stage 3: Replay the trace snapshots

`assay replay` runs the task pack's `test.sh` on each snapshot in the trial's `trace.git`, in a fresh container with no network. It replays each trial two times. Docker must be running.

```powershell
uv run assay replay results\$job
```

For each trial, the command prints `replay works` or `replay does not work` and the causes. It exits with 1 when replay does not work on a trial. It writes `analysis/<job-id>/<trial>/replay.jsonl` (one line for each snapshot) and `replay-works.json` (the verdict).

Harbor deletes each trial's task image, so replay rebuilds it from the pack's Dockerfile, whose base image is pinned by digest. `replay-works.json` records the rebuilt image ID and that base image. For each failure, find the cause, fix it, and replay all the trials again (PRD section 7, Phase 0).

### Stage 4: Cross-check the agent's test runs

`assay agent-runs` finds each test run of the agent and compares its exit code with the replay of the same snapshot. Run it after stage 3:

```powershell
uv run assay agent-runs results\$job
```

It prints one JSON line for each trial, with the coverage and the agreement. It writes `analysis/<job-id>/<trial>/agent-runs.jsonl` and `cross-check.json`.

### Stage 5: Check `trajectory.py` by hand

A person labels the ten hosted trials and compares the labels with `trajectory.py`, for test-first order and for red-to-green order and the TDD loop. The full procedure is in the PRD, section 5, "How a person checks `trajectory.py`" and its red-to-green extension. Stages 3 and 4 must be complete for each hosted job. In short:

1. Print the neutral listing of each trial with `jq`. The listing gives no class, no seen state, no verdict, and no count. The header of `analyze/listing.jq` explains each field. This loop writes the listing of each trial of the job to `analysis/<job-id>/<trial>/listing.txt`:

   ```powershell
   [Console]::OutputEncoding = [Text.UTF8Encoding]::new()   # read jq's output as UTF-8
   $trials = Get-ChildItem results\$job -Directory | Where-Object { Test-Path "$_\lock.json" }
   foreach ($t in $trials) {
     $out = "analysis\$job\$($t.Name)"
     jq -r `
       --slurpfile trace  "$t\artifacts\logs\artifacts\trace\trace.jsonl" `
       --slurpfile replay "$out\replay.jsonl" `
       --slurpfile runs   "$out\agent-runs.jsonl" `
       -f analyze\listing.jq "$t\agent\trajectory.json" > "$out\listing.txt"
   }
   ```

2. Copy `labeling/sheet-template.csv` and fill one row per trial before `trajectory.py` runs. Use the trial folder name for `trial`. For test-first order, give the verdict, the two anchors (`step_id`, position, and path of the first test write and of the first implementation write), and a note. For red-to-green order, give the verdict, the `tool_use_id` of the first seen red and of the first seen green, the three counts of the TDD loop, and a note. Leave a cell blank when there is no such write or seen state. You can read `trajectory.json` when the listing is not sufficient.

   ```powershell
   Copy-Item labeling\sheet-template.csv analysis\sheet.csv
   ```

3. Run `assay trajectory` on the trials of both hosted jobs, then compare. PowerShell does not expand a wildcard for `assay`, so the first command lists the trial folders. `assay compare-labels` prints each difference and exits with 1 when any trial differs:

   ```powershell
   $trials = Get-ChildItem results\phase0-cross, results\phase0-extra -Directory |
     Where-Object { Test-Path "$_\lock.json" }
   uv run assay trajectory $trials.FullName > analysis\trajectory.jsonl
   uv run assay compare-labels analysis\sheet.csv analysis\trajectory.jsonl
   ```

4. For each difference, find the cause and fix the script, the label, or the rule in the PRD. Record each correction in a copy of `labeling/corrections-template.csv` (`corrected` is `script`, `label`, or `rule`). Repeat until one full pass over the ten trials gives no difference for each metric.

   ```powershell
   Copy-Item labeling\corrections-template.csv analysis\corrections.csv
   ```

### Stage 6: Write the Phase 0 summary

After stages 3 and 4 have run on each job, write the summary of every Phase 0 acceptance value. It goes to `analysis/phase0-summary.md` (for a person) and `analysis/phase0-summary.json`, and the command writes nothing else:

```powershell
uv run assay summary results\phase0-cross results\phase0-extra results\phase0-local
```

## Run the tests

```powershell
uv run pytest             # fast tests; skips tests marked `slow`
uv run pytest -m slow     # only the slow tests
uv run pytest -m ""       # all tests, slow included
```

A test that needs Docker or Harbor gets the `@pytest.mark.slow` marker. The default run skips it.
