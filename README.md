# Assay
Assay measures the value of a context artifact for a coding agent: a skill, a rules file, an instruction file, or a hook.

## Commands

`assay` is the one tool for running and analysing a job. Run it through uv from the repository root:

| Command | What it does |
|---|---|
| [`uv run assay run -c jobs/<file>.yaml`](#assay-run) | Starts a job: runs `harbor run` with the job file, after it checks the Claude Code version and the job's results folder. `--overwrite` deletes earlier results first. |
| [`uv run assay trace-check results/<job-id>`](#assay-trace-check) | Checks that the trace hook worked in each trial of the job. |
| [`uv run assay replay results/<job-id>`](#assay-replay) | Gives the test state (`no-tests`, `red-compile`, `fail` or `pass`) of each trace snapshot of each trial, and says whether replay works. |
| [`uv run assay agent-runs results/<job-id>`](#assay-agent-runs) | Cross-checks each test run of the agent with the replay of the same snapshot. |
| [`uv run assay trajectory results/<job-id>...`](#assay-trajectory) | Measures test-first order, red-to-green order and the TDD loop of each trial of one or more jobs, and writes them to `analysis/trajectory.jsonl`. |
| [`uv run assay compare-labels <sheet.csv> <trajectory.jsonl>`](#assay-compare-labels) | Compares the labeling sheet with the output of `assay trajectory`, and prints each difference. |
| [`uv run assay summary results/<job-id>...`](#assay-summary) | Writes the Phase 0 summary of one or more jobs. |

The sections below say why each command exists and what result to expect. PRD section 5 gives the full rules.

### `assay run`

Runs an Assay job in Harbor: it checks the job file, then runs `harbor run` with it.

Every result must trace back to a committed job file, and every trial must run the pinned Claude Code version. `assay run` makes sure of both before Harbor starts. It refuses a job without `-c`, and a job whose Claude Code version is not `stable`, `latest` or `X.Y.Z` (for example the placeholder). Harbor cannot resume a job whose job file changed, and it cannot overwrite earlier results, so `assay run` looks at the job's results folder first. If that folder holds results of a different config, it stops and says to re-run with `--overwrite`.

**Expected result:** Harbor's exit code, and one trial folder for each trial in `results/<job_name>/`. A `--dry-run` lists the trials and runs none: 4 each for `phase0-cross-control` and `phase0-cross-tdd`, 2 for `phase0-extra` and 1 for `phase0-local`. Exit code 2 means that `assay run` stopped before Harbor started, and the message says why.

### `assay trace-check`

Checks that the trace hook worked in each trial of a job.

Replay and every process metric depend on the trace that the trace hook writes in each trial. If the hook did not work, the measurements of that trial are not valid. The trace check makes eight checks on each trial:

1. `instruments`: the trial ran the committed `instruments/` folder (the same digest).
2. `seed`: the hook made the first snapshot, of the seed repository.
3. `tool-calls`: each tool call in the trajectory has exactly one trace line.
4. `errors`: no trace line records a hook error.
5. `changed`: at least one snapshot holds a change.
6. `claude-code-version`: the Claude Code that ran is the pinned version.
7. `harbor-version`: the Harbor that ran is the version in `uv.lock`.
8. `file-writes`: each successful `Edit`, `MultiEdit`, or `Write` that changed a file in the seed repository has that path in its trace line.

**Expected result:** one JSON line per trial, each with `"failed_checks": []`, and exit code 0. Phase 0 needs every trial to pass. A trial that fails a check is a failure of the infrastructure: fix the cause, and run the trial again in the same cell. Exit code 2 means that the trials of the job ran more than one Claude Code version.

### `assay replay`

Runs the task pack's tests on each snapshot of each trial, to find the test state after each change the agent made.

The trajectory of a trial shows the order in which the agent wrote files, but not whether the tests passed or failed between the writes. The trace hook saves a snapshot of the repository after each tool call that changes it. After the trial, `assay replay` runs the task pack's unchanged `tests/test.sh` on each snapshot, in a fresh container with no network, and reads the test state from the `reward.json` that the script writes.

Replay is the only source of the test state, for every trial and every condition, so that all conditions are measured the same way. It also works when the agent writes files through `Bash`, and when the agent never runs the tests itself. The test runs of the agent are only a cross-check (`assay agent-runs`). `assay trajectory` needs the replay for red-to-green order and the TDD loop; without it, both are null.

Phase 0 replays each trial two times, to show that replay can rebuild the environment of the trial (PRD section 8, risk 1). Harbor deletes each trial's task image, so replay rebuilds it from the pack's Dockerfile, whose base image is pinned by digest.

**Expected result:** `<trial>: replay works` for every trial, and exit code 0. Replay works on a trial when all three are true:

- Each snapshot gives a test state. A timeout or a container error is a failure; `red-compile` is a test state, not a failure.
- The replay of the last snapshot gives the same `reward.json`, field for field, as the trial's verifier.
- The two runs give the same result for each snapshot.

Phase 0 needs replay to work on all eleven trials. A trial where it does not work prints `replay does not work` and the causes, and the command exits 1. For each failure, find the cause, fix it, and replay all the trials again. If replay cannot rebuild the trial's environment and the cause cannot be fixed, the PRD's fallback is to make the mutation score the primary process metric.

### `assay agent-runs`

Checks each test run of the agent against the replay of the same snapshot.

The agent's own test runs are a second view of the test state: each one gives an exit code at the moment the agent ran it. `assay agent-runs` finds each `Bash` call that runs the pack's test command in the seed repository (for example `go test` or `npm test`). It ties the run to the last snapshot before it, and checks that the exit code agrees with the replay of that snapshot. A pass agrees with exit code 0; `fail` and `red-compile` agree with any other exit code. A run that selects some of the tests (for example `go test -run X`) is `partial`, and it is not compared. The runs that agree are the "seen states" that red-to-green order and the TDD loop use.

**Expected result:** one JSON line per trial, and exit code 0. Each line gives two values:

- **Coverage**: the share of snapshots that have a test run after them and before the next snapshot. It shows how often the agent ran the tests. It has no target value.
- **Agreement**: the share of compared runs that agree with the replay. Expect 1 (100%). `differences` lists the `tool_use_id` of each run that does not agree. For each one, a person finds the cause: the test-run pattern, the observation, or the replay. Only a replay that does not give the trial's environment is a failure of the replay.

### `assay trajectory`

Measures how each trial worked: test-first order, red-to-green order and the TDD loop.

Give one or more job folders, `results/<job-id>`, as for `assay summary`. The command analyses each trial folder of each job (a folder that holds a `lock.json`), in name order. It reads each trial's replay and agent runs from `analysis/<job-id>/<trial>/`. `--analysis` changes the `analysis` root.

It writes `analysis/trajectory.jsonl`, with one JSON line for each trial, and replaces an earlier file, so the file holds only the jobs given. Each line has these values:

- **Test-first order**, from the order of the writes only: `test-first`, `implementation-first`, `same-turn`, `throwaway-tests`, `no-test` or `no-implementation`. The anchors are the first kept test write and the first implementation write. `throwaway-tests` means the agent wrote test files but kept none; its test anchor has `kept: false` and the source that found the write (`trace`, `tool` or `bash`).
- **Red-to-green order**, from the seen states: `red-to-green` (the agent first saw the tests fail, and later saw them pass), `green-first`, `never-green` or `not-observed`. The anchors are the first seen red and the first seen green.
- **The TDD loop**: the counts of red-to-green cycles, of tests never seen red, and of refactor steps.
- Whether a `Bash` call wrote to the repository, and whether the instrument skill loaded before the first file write.
- **Ad-hoc runs**: the count of `Bash` calls that run a script the agent wrote (for example `npx tsx /tmp/verify.ts`), and the step of the first. They are not test runs, so the cross-check does not see them.
- **Web access**: whether the agent may have reached the web, and the steps where it did: a `WebFetch` or `WebSearch` call that did not fail, or a `Bash` command with a URL, `curl`, `wget` or `git clone`. A flagged trial may have read the exercise's solution. It stays in the data; `assay summary` also gives its figures without the flagged trials.

**Expected result:** `wrote analysis/trajectory.jsonl`, one line in it for each trial, and exit code 0. No verdict is the expected one: a verdict measures the agent, and is not a pass or a fail. Red-to-green order and the TDD loop are `null` when the trial has no `replay.jsonl` and `agent-runs.jsonl`; run `assay replay` and `assay agent-runs` first. Phase 0 finds out whether the values are correct by comparing them with a person (`assay compare-labels`).

### `assay compare-labels`

Compares a person's labels of the trials with the output of `assay trajectory`.

`assay trajectory` is useful only if its rules give the same answer as a careful person. In Phase 0, a person labels the ten hosted trials from the neutral `jq` listing before `assay trajectory` runs. `assay compare-labels` then compares the labels with the script. The two agree on a trial, for one metric, when every field of that metric is the same: for test-first order, the verdict and the two anchors; for red-to-green order, the verdict, the two anchors and the three counts of the TDD loop. Notes are not compared.

**Expected result:** each trial prints `test_first: agrees  red_to_green: agrees`, the last line is `agrees every time: test_first=True  red_to_green=True`, and the exit code is 0. Phase 0 needs one full pass over the ten trials with no difference, for each metric. Each difference prints the field and the two values, and the command exits 1. A trial that is in one file only is also a difference. For each difference, fix the script, the label or the rule in the PRD, record the correction, and compare again.

### `assay summary`

Writes the Phase 0 summary: every Phase 0 acceptance value, for one or more jobs.

Phase 0 blocks all other phases, and its acceptance values come from every stage. `assay summary` puts them in one place:

- For each trial: the trace check, the replay verdict, the process metrics, the coverage and agreement, and the cost.
- The shares of trials with a file-writing `Bash` call (risk 2).
- The pooled coverage and agreement.
- The cost for each model tier, and the total hosted cost against the £15 cap.
- The values of the local trial (risks 9 and 10).

It writes `analysis/phase0-summary.md` and `analysis/phase0-summary.json`, and nothing else.

**Expected result:** `wrote ...phase0-summary.md and ...phase0-summary.json`, and exit code 0. Phase 0 passes when the summary shows all of these:

- The trace check passes on every trial.
- Replay works on every trial.
- The hosted trials are `within the cap` of £15. The summary converts USD with the rate `USD_PER_GBP` in `analyze/summary.py`; set it to the rate on the day.
- The local trial's trajectory holds its tool arguments.

The person check (`assay compare-labels`) is the other acceptance value, and it is not in the summary. Where the summary says "record by hand from the server log", record the local trial's prefix cache hits and background requests by hand. Exit code 2 means that the trials of a job ran more than one Claude Code version.

### Help

`uv run assay` lists the commands, and `uv run assay <command> --help` shows the arguments of one. Do not run `harbor` directly: start every job with `assay run` (ADR 0002). [The analysis process](#the-analysis-process) gives the order of the commands and what each one reads and writes.

## Setup

Install [uv](https://docs.astral.sh/uv/), then run `uv sync` at the repository root. `pyproject.toml` pins `harbor==0.24.0` and the repository commits `uv.lock`, so every host gets the same Harbor version, and `assay run` uses it. To change the Harbor version, edit the pin in `pyproject.toml`, run `uv lock`, and commit `uv.lock`.

The analysis also needs these tools on the host:

- Docker, for the trials and for the replay of the trace snapshots.
- `jq` on the PATH, for the neutral listing of the person check (for example, `winget install jqlang.jq`).

**Host settings.** Copy `.env.example` to `.env` at the repository root and fill it in. The hosted jobs need `ANTHROPIC_API_KEY`; the local job needs `ASSAY_LOCAL_BASE_URL`. Git ignores `.env`. Every `assay` command loads it and prints the names of the keys it loaded, never the values:

```powershell
Copy-Item .env.example .env
```

A variable set in the shell still wins over `.env`. The order of the sources, strongest first: Harbor's `--env-file`, the shell, `.env`, then `.env.local` (Harbor's fallback).

`assay run` turns Harbor's usage telemetry off (`HARBOR_TELEMETRY=0`). On Windows its sender flashes a console window, and it sends each job's model names and cost to Harbor's maintainers. Set `HARBOR_TELEMETRY=1` in the shell or `.env` to turn it back on.

The commands in this README are for PowerShell 7 (`pwsh`), run from the repository root. Use PowerShell 7 and not Windows PowerShell 5.1: in PowerShell 7, `>` writes UTF-8 with no BOM, which the analysis scripts can read.

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

Every stage uses an `assay` command, except the `jq` listing of stage 5.

`<job-id>` is the folder name of the job in `results/`, for example `phase0-cross-tdd`. A trial folder is a folder in `results/<job-id>/` that holds a `lock.json`. Git ignores `results/` and `analysis/`, so the commands below also keep the filled labeling sheet and the corrections in `analysis/`.

Most commands below use the variable `$job`. Set it to the job you analyze:

```powershell
$job = 'phase0-cross-tdd'   # or phase0-cross-control, phase0-extra, or phase0-local
```

### Stage 1: Run the jobs

The Phase 0 job files are in `jobs/`. Each runs at `-k 1` with `instruments.agent:InstrumentedClaudeCode`, so every trial, the control included, carries the trace hook. Trials go to `results/<job_name>/`.

| Job file | Trials |
|---|---|
| `jobs/phase0-cross-control.yaml` | Haiku and Sonnet × control × TypeScript and Go: 4 |
| `jobs/phase0-cross-tdd.yaml` | Haiku and Sonnet × `instrument-tdd` × TypeScript and Go: 4 |
| `jobs/phase0-extra.yaml` | Haiku × `instrument-tdd` × TypeScript and Go: 2 |
| `jobs/phase0-local.yaml` | the local model × `instrument-tdd` × one task pack: 1 |
| `jobs/phase0-smoke.yaml` | Haiku × `instrument-tdd` × TypeScript: 1. Use it to check the setup before the jobs above. |

The cross trials are two jobs because Harbor sets extra instructions per job, not per agent. Each `instrument-tdd` job passes `variants/instrument-tdd/extra-instruction.md`, which names the skill; the control job passes nothing. The web tools are off in every trial unless a job sets `kwargs.allow_web: true` (ADR 0003).

**Set the Claude Code version first.** On the day of the smoke trial, read the version of the `stable` channel of Claude Code. Replace the placeholder `SET-ON-SMOKE-TRIAL-DAY` with it in all the job files, in one commit, before the smoke trial runs. In each cross job the value is written once and shared through a YAML anchor. A fast test (`tests/test_job_files.py`) fails if the files do not hold one version. `uv run assay run` stops before Harbor starts if a job's version is not `stable`, `latest` or `X.Y.Z` (for example the placeholder, or no version), and the agent's `setup()` makes the same check for a direct `harbor run`. Do not change the version for the remaining Phase 0 trials (PRD, "Version pins").

Launch each job from the repository root with `assay run`, the only supported way to start a job (ADR 0002). It gives the job file to `harbor run` with `-c`, and every other option goes to Harbor unchanged:

```powershell
uv run assay run -c jobs/phase0-cross-control.yaml --dry-run   # check: 4 trials, nothing runs
uv run assay run -c jobs/phase0-cross-control.yaml -y --debug
uv run assay run -c jobs/phase0-cross-tdd.yaml -y --debug
uv run assay run -c jobs/phase0-extra.yaml -y --debug
```

The hosted jobs read `ANTHROPIC_API_KEY` from `.env` (see [Setup](#setup)).

`--debug` shows Harbor's debug log on the console. Harbor writes the same log, at debug level, to `results/<job_name>/job.log` and `<trial>/trial.log` with or without the flag. The console shows only "Running agent" while Claude Code works; to follow the agent, tail `results/<job_name>/<trial>/agent/claude-code.txt`, which Harbor writes while the agent runs (one JSON event per line):

```powershell
Get-Content results\phase0-cross-tdd\*\agent\claude-code.txt -Wait -Tail 20
```

**Re-running a job.** A re-run with the same job file resumes the job in `results/<job_name>/`: Harbor keeps the finished trials and runs the rest. Harbor cannot resume a job whose job file has changed. In that case `assay run` stops before Harbor starts and names the folder. To delete the folder and start fresh, add `--overwrite`:

```powershell
uv run assay run -c jobs/phase0-cross-tdd.yaml -y --debug --overwrite   # deletes results/phase0-cross-tdd/ without asking, then runs
uv run assay run -c jobs/phase0-cross-tdd.yaml --overwrite --dry-run   # says what it would delete; deletes nothing
```

`--overwrite` deletes the folder even when the job file has not changed. A `--dry-run` without `--overwrite` only warns about a changed job file. `--job-name` and `-o`/`--jobs-dir` on the command line change the folder, as they do in Harbor.

**The local job** needs three more steps:

1. Set the task pack. After the hosted trials, replace the marked `tasks:` path in `jobs/phase0-local.yaml` (`SET AFTER THE HOSTED TRIALS`) with the chosen pack.
2. Fill in `jobs/phase0-local.L6.md`, the record of the local setup (L6).
3. Set `ASSAY_LOCAL_BASE_URL` in `.env` to the server address (see [Setup](#setup)). This is the only place the address appears (L10). Without it, Harbor stops before any trial runs.

```powershell
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

3. Run `assay trajectory` on both hosted jobs, then compare. `assay trajectory` writes `analysis\trajectory.jsonl`. `assay compare-labels` prints each difference and exits with 1 when any trial differs:

   ```powershell
   uv run assay trajectory results\phase0-cross-control results\phase0-cross-tdd results\phase0-extra
   uv run assay compare-labels analysis\sheet.csv analysis\trajectory.jsonl
   ```

4. For each difference, find the cause and fix the script, the label, or the rule in the PRD. Record each correction in a copy of `labeling/corrections-template.csv` (`corrected` is `script`, `label`, or `rule`). Repeat until one full pass over the ten trials gives no difference for each metric.

   ```powershell
   Copy-Item labeling\corrections-template.csv analysis\corrections.csv
   ```

### Stage 6: Write the Phase 0 summary

After stages 3 and 4 have run on each job, write the summary of every Phase 0 acceptance value. It goes to `analysis/phase0-summary.md` (for a person) and `analysis/phase0-summary.json`, and the command writes nothing else:

```powershell
uv run assay summary results\phase0-cross-control results\phase0-cross-tdd results\phase0-extra results\phase0-local
```

## Run the tests

```powershell
uv run pytest             # fast tests; skips tests marked `slow`
uv run pytest -m slow     # only the slow tests
uv run pytest -m ""       # all tests, slow included
```

A test that needs Docker or Harbor gets the `@pytest.mark.slow` marker. The default run skips it.
