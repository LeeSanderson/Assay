# Assay
Assay measures the value of a context artifact for a coding agent: a skill, a rules file, an instruction file, or a hook.

## Commands

`assay` is the one tool for running and analysing a job. Run it through uv from the repository root:

| Command | What it does |
|---|---|
| [`uv run assay experiment <name>`](#assay-experiment) | Runs an experiment end to end: its jobs in order, the validity check, the evaluations and the summary. A second invocation resumes. |
| [`uv run assay run -c jobs/<file>.yaml`](#assay-run) | Starts one job: runs `harbor run` with the job file, after it checks the Claude Code version and the job's results folder. `--overwrite` deletes earlier results first. Use it for a job outside an experiment, such as the smoke trial. |
| [`uv run assay trace-check results/<job-id>`](#assay-trace-check) | Runs the ten-check validity check on each trial of the job, and writes `trial-check.json`. |
| [`uv run assay replay results/<job-id>`](#assay-replay) | Gives the test state (`no-tests`, `red-compile`, `fail` or `pass`) of each trace snapshot of each trial, and says whether replay works. |
| [`uv run assay agent-runs results/<job-id>`](#assay-agent-runs) | Cross-checks each test run of the agent with the replay of the same snapshot. |
| [`uv run assay trajectory results/<job-id>...`](#assay-trajectory) | Measures test-first order, red-to-green order and the TDD loop of each trial of one or more jobs, and writes them to `analysis/trajectory.jsonl`. |
| [`uv run assay compare-labels <sheet.csv> <analysis/experiment or trajectory.jsonl>`](#assay-compare-labels) | Compares the labeling sheet with the values of `trajectory`, and prints each difference. |

`trace-check`, `replay`, `agent-runs` and `trajectory` run inside `assay experiment`. The commands stay as thin entry points for one job folder, for example the smoke trial. The sections below say why each command exists and what result to expect. PRD v3 gives the full rules.

### `assay experiment`

Runs an experiment: `experiments/<name>/experiment.toml` lists its jobs in run order, its evaluations in run order, and its summary (PRD v3 sections 5 and 11). Phase 0 is the experiment `phase0-tdd`.

```powershell
uv run assay experiment phase0-tdd --dry-run   # the plan, at no cost
uv run assay experiment phase0-tdd             # run; run again to resume
```

| Option | Effect |
|---|---|
| `--job J` | Run only this job. It can repeat. The evaluations and the summary still cover every trial of the experiment. |
| `--dry-run` | Check the plan and print it: the jobs, the expected trials of each cell, the evaluations, the summary, and what resume would keep, delete and rerun. It never calls Harbor or Docker and deletes nothing. |
| `--from-scratch` | Delete `results/<name>` and `analysis/<name>`, the experiment log included, then run. |
| `--retries N` | After each job, run its infrastructure failures again, up to N times. The default is 0. |
| `--debug` | Give `--debug` to Harbor. No other option reaches Harbor. |

Before any job runs, the plan checks `experiment.toml` and each job file, the pinned Claude Code version, the variant folder of each agent's parts, the order and the dependencies of the evaluations, that the summary loads and that its options are valid, and that every `${VAR}` of a selected job file is set. A failure exits 2 at no cost.

Each job runs through `assay run` with `--jobs-dir results/<name>`, so its trials go to `results/<name>/<job>/<trial>/`. After each job, each trial gets the ten-check validity check (see [`assay trace-check`](#assay-trace-check)). An infrastructure failure, such as an API outage, is discarded with its cost in the log and runs again on the next invocation (or at once with `--retries`). A halt, such as a used-up quota, stops the experiment after the current job: fix the cause and run again. A timeout or a trial that changes no file is a result, and stays.

After the jobs, the evaluations (`replay`, `agent-runs`, `trajectory` for Phase 0) run over every kept trial. Each writes `analysis/<name>/<job>/<trial>/<evaluation>/result.json`, and a result is reused while its code and inputs are the same. Last, the summary runs again into `analysis/<name>/summary/`. Every invocation, job, discarded trial, halt, evaluation pass and summary goes to `analysis/<name>/experiment-log.jsonl`.

**The Phase 0 summary** is `experiments/phase0-tdd/summary.py`. It writes `analysis/phase0-tdd/summary/phase0-summary.md` (for a person) and `phase0-summary.json`:

- For each cell (harness, model tier, condition, language): the expected trials and the kept, discarded and halted trials. A cell with fewer kept trials than expected is marked `short`, for example the local cell before `phase0-local` runs. A short cell is not a failure.
- For each trial: the replay verdict, the process metrics, the coverage and agreement, the evaluation errors, and the cost.
- The shares of trials with a file-writing `Bash` call (risk 2), and the pooled coverage and agreement, with and without the web-access trials.
- The cost for each model tier, and the hosted cost against the £15 cap: the kept trials' cost plus the cost of each discarded trial from the experiment log. The rate `USD_PER_GBP` in the summary converts USD; set it to the rate on the day, or give `[summary] options = { usd_per_gbp = ... }` in `experiment.toml`.
- The values of the local trial from its trial record (risks 9 and 10).

**Expected result:** `experiment phase0-tdd: complete` and exit code 0. Exit code 3 means a halt, 130 an interruption (run again to resume), and 2 an error. Phase 0 passes when the summary shows all of these:

- No trial is missing (each kept trial passed the validity check).
- Replay works on every trial.
- The hosted trials are `within` the £15 cap.
- The local trial's trajectory holds its tool arguments.

The person check (`assay compare-labels`) is the other half of acceptance 1 and 6, and it is not in the summary. Record the local trial's tool calls after a mid-conversation system message, prefix cache hits and background requests by hand from the server log; the summary does not give them.

### `assay run`

Runs an Assay job in Harbor: it checks the job file, then runs `harbor run` with it.

Every result must trace back to a committed job file, and every trial must run the pinned Claude Code version. `assay run` makes sure of both before Harbor starts. It refuses a job without `-c`, and a job whose Claude Code version is not `stable`, `latest` or `X.Y.Z` (for example the placeholder). Harbor cannot resume a job whose job file changed, and it cannot overwrite earlier results, so `assay run` looks at the job's results folder first. If that folder holds results of a different config, it stops and says to re-run with `--overwrite`.

**Expected result:** Harbor's exit code, and one trial folder for each trial in `results/<job_name>/`. A `--dry-run` lists the trials and runs none: 4 each for `phase0-cross-control` and `phase0-cross-tdd`, 2 for `phase0-extra` and 1 for `phase0-local`. Exit code 2 means that `assay run` stopped before Harbor started, and the message says why.

### `assay trace-check`

Runs the validity check of the trial record on each trial of a job (PRD section 8, "The validity check").

Replay and every process metric depend on the trial record: the trace that the recorder writes in each trial, and the trajectory. If the record is not sound, the measurements of that trial are not valid. The validity check makes ten checks on each trial:

1. `instruments`: the trial ran the committed `instruments/` folder (the same digest), and `instruments.json` declares `granularity` and `calls_may_overlap`.
2. `seed`: a `seed` line exists, and its commit is the first commit.
3. `calls`: each tool call in the trajectory, failed calls included, has exactly one trace line.
4. `errors`: no trace line records a hook error.
5. `final`: a `final` line exists, it found no change, and its commit is the last commit.
6. `harness-version`: the Claude Code that ran is the pinned version.
7. `harbor-version`: the Harbor that ran is the version in `uv.lock`.
8. `condition`: the condition digests in the experiment log agree with the plan. Outside an experiment this check is skipped, and `trial-check.json` says so.
9. `claimed-paths`: each successful `Edit`, `MultiEdit`, or `Write` that changed a file in the seed repository has that path in its trace line.
10. `required-core`: the reader built every field of the required core, and `trial-check.json` names each missing field.

A trial in which the agent changes no file passes: it is a result.

**Expected result:** one JSON line per trial, each with `"failed_checks": []`, exit code 0, and `analysis/<job-id>/<trial>/trial-check.json` for each trial (`--analysis` changes the root). A failed check 1, 6, 7 or 8 is a halt: fix the cause before any trial runs again. Any other failed check is an infrastructure failure: run the trial again in the same cell. Exit code 2 means that the trials of the job ran more than one Claude Code version.

### `assay replay`

Runs the task pack's tests on each snapshot of each trial, to find the test state after each change the agent made.

The trajectory of a trial shows the order in which the agent wrote files, but not whether the tests passed or failed between the writes. The trace hook saves a snapshot of the repository after each tool call that changes it. After the trial, `assay replay` runs the task pack's unchanged `tests/test.sh` on each snapshot, in a fresh container with no network, and reads the test state from the `reward.json` that the script writes.

Replay keeps the verifier's log folder of each snapshot in `analysis/<job-id>/<trial>/replay-logs/<seq>/`, beside `replay.jsonl`: `test-stdout.txt` (the output of `test.sh`) and the logs it writes, such as `agent-tsc.log`, `outcome-tsc.log` and `outcome-jest.log`. Read them to find why a snapshot is `red-compile` or `fail`, or why it gives no test state. A snapshot that times out keeps the logs that exist at that time.

Replay is the only source of the test state, for every trial and every condition, so that all conditions are measured the same way. It also works when the agent writes files through `Bash`, and when the agent never runs the tests itself. The test runs of the agent are only a cross-check (`assay agent-runs`). `assay trajectory` needs the replay for red-to-green order and the TDD loop; without it, both are null.

Phase 0 replays each trial two times, to show that replay can rebuild the environment of the trial (PRD section 8, risk 1). Harbor deletes each trial's task image, so replay rebuilds it from the pack's Dockerfile, whose base image is pinned by digest.

**Expected result:** `<trial>: replay works` for every trial, and exit code 0. Replay works on a trial when all three are true:

- Each snapshot gives a test state. A timeout or a container error is a failure; `red-compile` is a test state, not a failure.
- The replay of the last snapshot gives the same `reward.json`, field for field, as the trial's verifier.
- The two runs give the same result for each snapshot.

Phase 0 needs replay to work on all eleven trials. A trial where it does not work prints `replay does not work` and the causes, and the command exits 1. For each failure, find the cause, fix it, and replay all the trials again. If replay cannot rebuild the trial's environment and the cause cannot be fixed, the PRD's fallback is to make the mutation score the primary process metric.

### `assay agent-runs`

Checks each test run of the agent against the replay of the same snapshot.

The agent's own test runs are a second view of the test state: each one shows red or green at the moment the agent ran it. `assay agent-runs` finds each `Bash` call that runs the pack's test command in the seed repository (for example `go test` or `npm test`). It ties the run to the last snapshot before it, and gives the run a `result`:

- The test framework's summary in the run's output decides when there is one. For jest, failed tests, failed suites or "Test suite failed to run" give `red`; passed tests and no failures give `green`. For `go test`, a `--- FAIL` or `FAIL` line, a `[build failed]` line or a compile-error header (`# <package>`) gives `red`; `ok` package lines and no failures give `green`.
- A piped run (the test command is followed by `|`, for example `yarn jest 2>&1 | tail -20`) gets its result from the output only, because its exit code is `tail`'s. With no summary in the output (for example cut off by `head`), the result is `unknown`.
- A run that is not piped and has no summary falls back to its exit code: 0 is `green`, anything else `red`.

Each line of `agent-runs.jsonl` records `result` (`red`, `green` or `unknown`), `result_source` (`output` or `exit_code`) and the raw `exit_code`. The command then checks that the result agrees with the replay of that snapshot. A pass agrees with `green`; `fail` and `red-compile` agree with `red`. A run that selects some of the tests (for example `go test -run X`) is `partial`; partial runs and runs with an `unknown` result are not compared. The runs that agree are the "seen states" that red-to-green order and the TDD loop use; an `unknown` run is never a seen state.

**Expected result:** one JSON line per trial, and exit code 0. Each line gives two values:

- **Coverage**: the share of snapshots that have a test run after them and before the next snapshot. It shows how often the agent ran the tests. It has no target value.
- **Agreement**: the share of compared runs that agree with the replay. Expect 1 (100%). `differences` lists the `tool_use_id` of each run that does not agree. For each one, a person finds the cause: the test-run pattern, the observation, or the replay. Only a replay that does not give the trial's environment is a failure of the replay.

### `assay trajectory`

Measures how each trial worked: test-first order, red-to-green order and the TDD loop.

Give one or more job folders, `results/<job-id>`. The command analyses each trial folder of each job (a folder that holds a `lock.json`), in name order. It reads each trial's replay and agent runs from `analysis/<job-id>/<trial>/`. `--analysis` changes the `analysis` root.

It writes `analysis/trajectory.jsonl`, with one JSON line for each trial, and replaces an earlier file, so the file holds only the jobs given. Each line has these values:

- **Test-first order**, from the order of the writes only: `test-first`, `implementation-first`, `same-turn`, `throwaway-tests`, `no-test` or `no-implementation`. The anchors are the first kept test write and the first implementation write. `throwaway-tests` means the agent wrote test files but kept none; its test anchor has `kept: false` and the source that found the write (`trace`, `tool` or `bash`).
- **Red-to-green order**, from the seen states: `red-to-green` (the agent first saw the tests fail, and later saw them pass), `green-first`, `never-green` or `not-observed`. The anchors are the first seen red and the first seen green.
- **The TDD loop**: the counts of red-to-green cycles, of tests never seen red, and of refactor steps.
- Whether a `Bash` call wrote to the repository, and whether the instrument skill loaded before the first file write.
- **Ad-hoc runs**: the count of `Bash` calls that run a script the agent wrote (for example `npx tsx /tmp/verify.ts`), and the step of the first. They are not test runs, so the cross-check does not see them.
- **Web access**: whether the agent may have reached the web, and the steps where it did: a `WebFetch` or `WebSearch` call that did not fail, or a `Bash` command with a URL, `curl`, `wget` or `git clone`. A flagged trial may have read the exercise's solution. It stays in the data; the Phase 0 summary also gives its figures without the flagged trials.

**Expected result:** `wrote analysis/trajectory.jsonl`, one line in it for each trial, and exit code 0. No verdict is the expected one: a verdict measures the agent, and is not a pass or a fail. Red-to-green order and the TDD loop are `null` when the trial has no `replay.jsonl` and `agent-runs.jsonl`; run `assay replay` and `assay agent-runs` first. Phase 0 finds out whether the values are correct by comparing them with a person (`assay compare-labels`).

### `assay compare-labels`

Compares a person's labels of the trials with the values of `trajectory`. The second argument is an experiment's analysis folder, such as `analysis\phase0-tdd`, whose `<job>/<trial>/trajectory/result.json` files `assay experiment` writes, or the `analysis/trajectory.jsonl` that `assay trajectory` writes.

`assay trajectory` is useful only if its rules give the same answer as a careful person. In Phase 0, a person labels the ten hosted trials from the neutral `jq` listing before `assay trajectory` runs. `assay compare-labels` then compares the labels with the script. The two agree on a trial, for one metric, when every field of that metric is the same: for test-first order, the verdict and the two anchors; for red-to-green order, the verdict, the two anchors and the three counts of the TDD loop. Notes are not compared.

**Expected result:** each trial prints `test_first: agrees  red_to_green: agrees`, the last line is `agrees every time: test_first=True  red_to_green=True`, and the exit code is 0. Phase 0 needs one full pass over the ten trials with no difference, for each metric. Each difference prints the field and the two values, and the command exits 1. A trial that is in one file only is also a difference. For each difference, fix the script, the label or the rule in the PRD, record the correction, and compare again.

### Help

`uv run assay` lists the commands, and `uv run assay <command> --help` shows the arguments of one. Do not run `harbor` directly: start every job with `assay experiment` or `assay run` (ADRs 0002 and 0004). [The analysis process](#the-analysis-process) gives the order of the commands and what each one reads and writes.

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

Phase 0 runs as one experiment, `phase0-tdd`, after the smoke gate. It has four stages. Each stage reads the output of the stages before it.

| Stage | Command | Reads | Writes |
|---|---|---|---|
| 1. Pass the smoke gate | `uv run assay run`, then `trace-check`, `replay`, `agent-runs` and `trajectory` on `results/phase0-smoke` | `jobs/phase0-smoke.yaml` | `results/phase0-smoke/`, `analysis/phase0-smoke/`, `analysis/trajectory.jsonl` |
| 2. Run the experiment | `uv run assay experiment phase0-tdd` | `experiments/phase0-tdd/experiment.toml`, `jobs/*.yaml`, the task packs | `results/phase0-tdd/<job>/<trial>/`, `analysis/phase0-tdd/` |
| 3. Check `trajectory.py` by hand | `jq`, `uv run assay compare-labels` | `results/phase0-tdd/`, `analysis/phase0-tdd/`, the labeling sheet | `analysis/phase0-tdd/<job>/<trial>/listing.txt` |
| 4. Read the Phase 0 summary | none: stage 2 writes it | `analysis/phase0-tdd/summary/phase0-summary.md` | |

Every stage uses an `assay` command, except the `jq` listing of stage 3. Git ignores `results/` and `analysis/`, so the commands below also keep the filled labeling sheet and the corrections in `analysis/`.

### The jobs

The Phase 0 job files are in `jobs/`. Each runs at `-k 1` with `instruments.agent:InstrumentedClaudeCode`, so every trial, the control included, carries the trace hook.

| Job file | Trials |
|---|---|
| `jobs/phase0-cross-control.yaml` | Haiku and Sonnet × control × TypeScript and Go: 4 |
| `jobs/phase0-cross-tdd.yaml` | Haiku and Sonnet × `instrument-tdd` × TypeScript and Go: 4 |
| `jobs/phase0-extra.yaml` | Haiku × `instrument-tdd` × TypeScript and Go: 2 |
| `jobs/phase0-local.yaml` | the local model × `instrument-tdd` × one task pack: 1 |
| `jobs/phase0-smoke.yaml` | Haiku × `instrument-tdd` × TypeScript: 1. The smoke gate, outside the experiment. |

The cross trials are two jobs because Harbor sets extra instructions per job, not per agent. Each `instrument-tdd` job passes `variants/instrument-tdd/extra-instruction.md`, which names the skill; the control job passes nothing. The experiment reads each agent's condition from the variant folder its parts come from: `phase0-cross-control` is the control, and the other three jobs are `instrument-tdd`. The web tools are off in every trial unless a job sets `kwargs.allow_web: true` (ADR 0003).

**Set the Claude Code version first.** On the day of the smoke trial, read the version of the `stable` channel of Claude Code. Write it as `kwargs.version` in all the job files, in one commit, before the smoke trial runs. In each cross job the value is written once and shared through a YAML anchor. A fast test (`tests/test_job_files.py`) fails if the files do not hold one version. `assay run` and `assay experiment` stop before Harbor starts if a job's version is not pinned, and the agent's `setup()` makes the same check for a direct `harbor run`. Do not change the version for the remaining Phase 0 trials (PRD, "Version pins").

### Stage 1: Pass the smoke gate

The smoke trial runs through `assay run`, not through the experiment (PRD v3 section 17, "The smoke gate"). Run it again after a change to a task pack, to the recorder, or to the evaluations, before the paid Phase 0 jobs:

```powershell
uv run assay run -c jobs/phase0-smoke.yaml -y --debug
uv run assay trace-check results\phase0-smoke
uv run assay replay results\phase0-smoke
uv run assay agent-runs results\phase0-smoke
uv run assay trajectory results\phase0-smoke
```

The gate passes when `analysis/trajectory.jsonl` shows that the skill loaded before the first file write, the trial is not flagged for web access, and red-to-green order is not `not-observed` when the trial has an agent test run with a red or green result. The reward is not a criterion.

`--debug` shows Harbor's debug log on the console. Harbor writes the same log, at debug level, to `results/<job_name>/job.log` and `<trial>/trial.log` with or without the flag. To follow the agent, tail `<trial>/agent/claude-code.txt`, which Harbor writes while the agent runs (one JSON event per line):

```powershell
Get-Content results\phase0-smoke\*\agent\claude-code.txt -Wait -Tail 20
```

**Re-running a single job.** A re-run of `assay run` with the same job file resumes the job in `results/<job_name>/`: Harbor keeps the finished trials and runs the rest. Harbor cannot resume a job whose job file has changed. In that case `assay run` stops before Harbor starts and names the folder. Add `--overwrite` to delete the folder and start fresh (with `--dry-run`, it only says what it would delete).

### Stage 2: Run the experiment

Check the plan first. It costs nothing: it prints the four jobs, the 11 expected trials by cell, the evaluations and the summary, and what resume would do:

```powershell
uv run assay experiment phase0-tdd --dry-run
```

Run the hosted jobs. They read `ANTHROPIC_API_KEY` from `.env` (see [Setup](#setup)):

```powershell
uv run assay experiment phase0-tdd --job phase0-cross-control --job phase0-cross-tdd --job phase0-extra --debug
```

The evaluations and the summary run after the jobs, over every trial of the experiment. Until `phase0-local` runs, the summary shows the local cell as short. If the run stops (Ctrl-C, a halt or an error), fix the cause and run the same command again: finished trials are kept, discarded and halted trials run again, and unchanged evaluation results are reused. Add `--retries 1` to rerun an infrastructure failure at once. `--from-scratch` deletes `results/phase0-tdd` and `analysis/phase0-tdd` and starts again.

**The local job** runs last, on the host of the local server, and needs three more steps:

1. Set the task pack. After the hosted trials, replace the marked `tasks:` path in `jobs/phase0-local.yaml` (`SET AFTER THE HOSTED TRIALS`) with the chosen pack.
2. Fill in `jobs/phase0-local.L6.md`, the record of the local setup (L6).
3. Set `ASSAY_LOCAL_BASE_URL` in `.env` to the server address (see [Setup](#setup)). This is the only place the address appears (L10). Without it, the plan stops before any job runs.

```powershell
uv run assay experiment phase0-tdd --job phase0-local --debug
```

### Stage 3: Check `trajectory.py` by hand

A person labels the ten hosted trials and compares the labels with `trajectory.py`, for test-first order and for red-to-green order and the TDD loop. The full procedure is in the PRD, "How a person checks `trajectory.py`" and its red-to-green extension. In short:

1. Print the neutral listing of each trial with `jq`. The listing gives no class, no seen state, no verdict, and no count. The header of `analyze/listing.jq` explains each field. This loop takes the replay snapshots and the agent's test runs from the evaluation results, and writes the listing of each hosted trial to `analysis/phase0-tdd/<job>/<trial>/listing.txt`:

   ```powershell
   [Console]::OutputEncoding = [Text.UTF8Encoding]::new()   # read jq's output as UTF-8
   foreach ($job in 'phase0-cross-control', 'phase0-cross-tdd', 'phase0-extra') {
     $trials = Get-ChildItem results\phase0-tdd\$job -Directory | Where-Object { Test-Path "$_\lock.json" }
     foreach ($t in $trials) {
       $out = "analysis\phase0-tdd\$job\$($t.Name)"
       jq -c '.value.snapshots[]' "$out\replay\result.json" > "$out\replay.jsonl"
       jq -c '.value.runs[]' "$out\agent-runs\result.json" > "$out\agent-runs.jsonl"
       jq -r `
         --slurpfile trace  "$t\artifacts\logs\artifacts\trace\trace.jsonl" `
         --slurpfile replay "$out\replay.jsonl" `
         --slurpfile runs   "$out\agent-runs.jsonl" `
         -f analyze\listing.jq "$t\agent\trajectory.json" > "$out\listing.txt"
     }
   }
   ```

2. Copy `labeling/sheet-template.csv` and fill one row per trial before you read any value of `trajectory`. Use the trial folder name for `trial`. For test-first order, give the verdict, the two anchors (`step_id`, position, and path of the first test write and of the first implementation write), and a note. For red-to-green order, give the verdict, the `tool_use_id` of the first seen red and of the first seen green, the three counts of the TDD loop, and a note. Leave a cell blank when there is no such write or seen state. You can read `trajectory.json` when the listing is not sufficient.

   ```powershell
   Copy-Item labeling\sheet-template.csv analysis\sheet.csv
   ```

3. Compare the sheet with the `trajectory` results of the experiment. `assay compare-labels` prints each difference and exits with 1 when any trial differs:

   ```powershell
   uv run assay compare-labels analysis\sheet.csv analysis\phase0-tdd
   ```

4. For each difference, find the cause and fix the script, the label, or the rule in the PRD. Record each correction in a copy of `labeling/corrections-template.csv` (`corrected` is `script`, `label`, or `rule`). After a fix to `trajectory.py`, run `uv run assay experiment phase0-tdd` again: only `trajectory` reruns. Repeat until one full pass over the ten trials gives no difference for each metric.

   ```powershell
   Copy-Item labeling\corrections-template.csv analysis\corrections.csv
   ```

### Stage 4: Read the Phase 0 summary

Each complete invocation of stage 2 writes `analysis/phase0-tdd/summary/phase0-summary.md` (for a person) and `phase0-summary.json` again. [`assay experiment`](#assay-experiment) says what they hold and when Phase 0 passes.

## Run the tests

```powershell
uv run pytest             # fast tests; skips tests marked `slow`
uv run pytest -m slow     # only the slow tests
uv run pytest -m ""       # all tests, slow included
```

A test that needs Docker or Harbor gets the `@pytest.mark.slow` marker. The default run skips it.
