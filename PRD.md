# Assay — Product Requirements Document

**Owner:** Lee Sanderson · Version 3.0 · 4 November 2026

*This document uses Simplified Technical English (ASD-STE100). Spelling is American, as Rule 1.14 requires.*

*Version 3 puts the **experiment** at the center. Part I is the platform: it is the same for each experiment. Part II is the experiment catalogue: the TDD skill-transfer experiment in full, and sketches of the next experiments. The terms are in [`GLOSSARY.md`](GLOSSARY.md). The decisions are in [`docs/adr/`](docs/adr/) and in the map [Experiments as the core of Assay](https://github.com/LeeSanderson/Assay/issues/44).*

---

# Part I — The platform

## 1. What Assay is

**The name.** An assay is a test that measures the strength or the purity of a substance. A metallurgist assays an ore to find how much metal it holds, because the claim on the label is not the measurement. Assay does the same for a context artifact.

Assay measures the value of a context artifact. A context artifact is a skill, a rules file, an instruction file, or a hook for a coding agent. This document uses the short form "artifact".

Assay measures two effects of an artifact. The first effect is the change in the work of the agent. The second effect is the change in cost. Assay also measures how these effects change with the model tier, with the harness, and with the target language.

Assay answers questions of this form. Does the TDD skill improve the output of Haiku in Go? Does it improve the output of Sonnet in TypeScript by the same amount? Is an open-weight model on local hardware sufficient for either? Do Claude Code and opencode give the same result on the same tasks? What does each result cost?

Each question is one **experiment**. Assay has four parts:

- A corpus of **task packs** in more than one language.
- A **configuration** model: the conditions, the harnesses, and the model tiers that a trial can use.
- A **trial record**: fixed, harness-neutral telemetry for each trial.
- An **experiment** runner, `uv run assay experiment`. It runs the Harbor jobs of one experiment, then its **evaluations**, then its **summary**. It resumes after an interruption.

[Harbor](https://www.harborframework.com/) runs every trial.

## 2. The boundary with Harbor

Assay re-implements nothing that Harbor supplies. If Assay re-implements a function of Harbor, that is a defect ([ADR 0004](docs/adr/0004-assay-experiment-sequences-harbor-jobs.md)).

This rule replaces two rules of version 2: "Assay is not a runner", and the budget of 400 to 600 lines for the analyzer.

`assay experiment` runs the jobs of an experiment one after another. Each job runs through the `assay run` path ([ADR 0002](docs/adr/0002-assay-launcher-wraps-harbor-run.md)). Assay never drives an agent. Assay never schedules the trials inside a job. Harbor keeps the concurrency inside a job.

An experiment needs more than one Harbor job. Harbor sets extra instructions for each job, and thus two conditions are two jobs. A harness or a local setup can also split a job.

| Harbor owns | Assay owns |
|---|---|
| The sandbox and one container image for each task pack | The task packs and their withheld reference tests |
| Model selection, agent selection, and matrix expansion inside one job | The experiment: the order of its jobs, and the factor levels that it reads from them |
| Repetitions, concurrency, and the resume of one job | Resume across the jobs, the evaluations, and the summary |
| Capture of the trajectory and the cost | The recorder contract, the trial record, and its validity check |
| The result tree on disk | The evaluations, the summary, and the experiment log |

The task packs are native to Harbor. Thus any user of Harbor can run the corpus without an installation of Assay. This property gives the replication path, and it also prevents the growth of an adapter layer.

```
  tasks/**                variants/**              jobs/*.yaml
  (task packs)            (control + variants)     (committed Harbor jobs)
        │                        │                        │
        └────────────────────────┼────────────────────────┘
                                 ▼
             experiments/<name>/experiment.toml
             jobs (in order) · evaluations · summary
                                 ▼
         ┌──────────────────────────────────────────┐
         │  uv run assay experiment <name>          │
         │  for each job, in order:                 │
         │    HARBOR runs the job (all its trials)  │
         │    validity check on each trial          │
         │    discard and rerun infra failures      │
         └───────────────────┬──────────────────────┘
                             ▼
     results/<experiment>/<job>/<trial>/      Harbor tree + recorder trace folder
                             ▼
         evaluations, per trial, in listed order (reused when unchanged)
                             ▼
     analysis/<experiment>/<job>/<trial>/<evaluation>/result.json
                             ▼
         summary, across all trials (always reruns)
                             ▼
     analysis/<experiment>/summary/        analysis/<experiment>/experiment-log.jsonl
```

## 3. Why Assay is necessary

Two decisions occur every day across the industry. The first decision is the choice of model tier for a kind of work. The second decision is the choice of artifact. No measurement supports either decision today.

The published evidence shows that a simple measurement gives a false result. Three studies from 2026 examined repository context files ([arXiv 2602.11988](https://arxiv.org/abs/2602.11988), [2601.20404](https://arxiv.org/abs/2601.20404), [2607.27250](https://arxiv.org/html/2607.27250)). The studies found a small change in the success rate of tasks. The studies also found a large change in cost. One study measured a decrease of 29% in runtime and 17% in output tokens. Another study measured an increase of more than 20% in cost.

A harness that measures only the success rate therefore reports no effect. The real effect is large. Assay measures both.

No current tool closes this gap:

- `skill-creator` from Anthropic runs paired trials with a skill and without a skill. It uses one language only. It has no model tier axis. An agent grades the output instead of a real test suite.
- The test-generation benchmarks use Python only. Three examples are SWT-Bench, TDD-Bench-Verified, and TestGenEval. Therefore no current corpus can measure transfer between languages.
- Harbor supplies the execution matrix. Harbor has no concept of an experimental condition. Harbor computes `pass@k`, and `pass@k` is not an effect size.

## 4. Scope of the platform

The platform includes these items:

- The task-pack contract (section 6).
- The configuration model: conditions, variants with six parts, harnesses, and model tiers (section 7).
- The recorder contract, the trial record, and its validity check (section 8).
- The evaluation contract and the built-in evaluations (section 9).
- The summary contract and the built-in `paired-delta` summary (section 10).
- `assay experiment`, with resume (section 11).

The platform excludes these items:

- Code that re-implements a function of Harbor (section 2).
- A plugin interface, a web interface, and a hosted service.
- Public leaderboards and rankings of frontier models.
- Job files that Assay generates. An experiment references committed job files.

## 5. Experiments

An **experiment** is one question. It declares its jobs, its evaluations, and its summary. Everything else comes from its jobs: its task packs, its repetitions, its factors, and their levels. `experiment.toml` does not repeat a value that a job file holds.

### Factors

A **factor** is one axis that an experiment varies. The factor set is closed. It has three factors. Assay reads the level of each factor from each agent of each job file, at plan time:

| Factor | Levels | Source of the level of an agent |
|---|---|---|
| `harness` | The agent programs, such as Claude Code or opencode | The agent class (`import_path`) or the agent name |
| `model_tier` | The models, hosted or local | `model_name`, without change |
| `condition` | `control` and the variants | The variant folder that the parts of the agent come from |

**The condition.** Assay reads the variant parts that each agent receives (skills, settings, MCP servers, extra instructions, instruction file, and tools mount). The variant folder that holds the parts names the condition (section 7). An agent with no variant part is the control. If the parts of an agent come from more than one variant folder, Assay refuses the plan. Thus a job cannot have the wrong condition label.

A factor **varies** when the jobs hold more than one level of it. Assay needs no declaration for this.

The experiment declares no baseline. A baseline is necessary only for a comparison, and a comparison is the work of the summary (section 10). An option of the summary selects the comparisons.

A harness comparison is valid because the prompts and the tools of a harness are part of the harness. The comparison measures the full harness.

Language is not a factor. It is a part of the cell, and Assay reads it from the path of the task pack.

A setting that does not change in the experiment is not a factor. For example, a context limit is a fixed setting in the job files of an experiment, and the job files record it.

A **cell** is one combination of harness, model tier, condition, and language. A cell holds the trials across task packs and repetitions. A **short cell** holds fewer kept trials than its jobs promise. A job that did not run yet, or a discarded trial that was not replaced, gives a short cell. The summary shows a short cell. A short cell is not a failure.

### `experiment.toml`

Each experiment has a folder, `experiments/<name>/`. The file `experiments/<name>/experiment.toml` declares the experiment:

```toml
# experiments/phase0-tdd/experiment.toml
jobs = [                              # run in this order, one after another
  "jobs/phase0-cross-control.yaml",
  "jobs/phase0-cross-tdd.yaml",
  "jobs/phase0-extra.yaml",
  "jobs/phase0-local.yaml",
]

evaluations = ["replay", "agent-runs", "trajectory"]   # run order; a built-in name or ./path

# [evaluation-options.<name>]         # only for an evaluation that takes options

[summary]                             # optional
use = "./summary.py"
```

These rules apply:

1. **Jobs.** `jobs` lists the committed job files in run order. Assay never generates a job file. Harbor resumes a job only when its configuration is exactly the same, so the committed file is the source of truth. The job file is also the only source of the factor levels of its trials.
2. **Expected trials.** Assay calculates the expected trials of each cell from the job files: task packs × agents × `n_attempts`. The summary uses this count to find a short cell.
3. **Results folder.** Assay gives `--jobs-dir results/<experiment>` to Harbor. The trials of a job go to `results/<experiment>/<job_name>/`. Two experiments never share a Harbor job folder.
4. **Evaluations.** `evaluations` lists each evaluation by a built-in name, or by a path that starts with `./`. The listed order is the run order. An evaluation occurs one time only, because its results go to a folder with its name. The validity check of the trial record is never listed. It always runs.
5. **Evaluation options.** An evaluation that takes options gets a table `[evaluation-options.<name>]`. A path needs quotes, for example `[evaluation-options."./checks.py"]`. A table for an evaluation that is not listed is an error.
6. **Summary.** The `[summary]` table is optional. It has `use` and optional `options`.
7. **Unknown keys.** Assay refuses each unknown key, in each table. In TOML, a key belongs to the last table header above it. Thus `jobs` or `evaluations` below `[summary]` becomes `summary.jobs`, and this rule makes that mistake fail.

### Trials belong to one experiment

A trial belongs to the experiment that ran it. Experiments share their inputs: task packs, job files, and variants. Experiments do not share trials. To ask a new question of existing trials, add an evaluation to the experiment that owns them. Resume then runs only that evaluation.

## 6. Task packs

A **task pack** is one self-contained task. The platform defines a task pack by a contract, and not by its content. A task pack must have these parts:

1. **A seed repository**, committed in the image as one commit, `seed`.
2. **An image** that starts from a base image pinned by digest, and that holds `git`. A change of digest is a change of the task pack.
3. **Withheld reference tests.** The reference tests are always a pristine suite that the agent cannot read. When the seed repository has its own tests, the reference tests are those tests at their `seed` version, plus optional characterization tests.
4. **A verifier**, `tests/test.sh`, that writes `reward.json`. The outcome pass copies the repository to a scratch directory, removes each test file of the agent from the copy, adds the reference tests, and runs them.
5. **A gold solution**, `solution/solve.sh`, that calibrates the verifier.
6. **The provenance**, in the `[metadata]` table of `task.toml`: the source repository, the commit, the path of each copied file, each change, the file list of the seed repository, and the image digest.

Harbor copies `tests/` to `/tests/` after the agent stops. Thus the agent cannot read the reference tests.

`reward.json` holds a dictionary of metrics. It does not hold one pass value or one fail value.

A seed repository holds no agent configuration: no `.claude/` directory, no `CLAUDE.md`, and no `AGENTS.md`. A task image holds no `~/.claude/skills` and no harness. A variant supplies agent configuration (section 7).

### The pack recipe

Each experiment has a **pack recipe**. The pack recipe gives the source of the tasks, and what each seed repository, prompt, and set of reference tests holds. For example, the TDD experiment uses a stub with no tests (Part II, section 15). A refactoring experiment uses a working codebase with its own tests.

The task packs go into `tasks/` in the repository. An external dataset comes in through the import step of the recipe. The import step pins the digest, makes the starting state `seed`, and records the provenance.

### Tools that every condition shares

A tool that every condition of an experiment needs goes into the image of the task pack. A tool that only one variant has is an environment tool (section 7).

## 7. Configuration

### Conditions

A **condition** controls one thing only. It controls what the agent receives in addition to the task prompt. The task prompt, the seed repository, the model, the harness, and the language are the same across all conditions of one comparison.

An experiment has one control condition and zero or more variants.

**The control.** The agent receives the task prompt and nothing else. Harbor runs the control with no variant part. By default, the `paired-delta` summary compares each variant with the control.

**The measurement instruments.** A measurement instrument records what occurs in a trial. It runs in the same way in every condition, and the control is one of them. It is not a part of a variant, and it never goes into the context of the agent. The recorder is the measurement instrument of each harness (section 8).

### Variants

A **variant** is a named bundle of agent configuration. A bundle holds any combination of these six parts. The job file is the only place that gives the parts to an agent:

| Part | In the job file | Content |
|---|---|---|
| Skills | `skills` of the agent (`--skill <dir>`, repeatable) | One or more skill directories. A directory of directories injects all of them. |
| Hooks and settings | `kwargs.config` of the agent (`--ak config=<path or JSON>`) | A settings object for Claude Code. Harbor uploads it and starts the agent with `--settings`. |
| MCP servers | `--mcp-config <path>`, repeatable | An `.mcp.json` file. |
| Extra instructions | `extra_instruction_paths` of the job | Text that Harbor adds to the prompt. |
| Instruction file | `kwargs.instruction_file` of the agent | A file of standing instructions that the harness loads from disk. |
| Environment tools | An `environment.mounts` entry of the job | Command-line programs, in a read-only folder from a tools image. |

Assay sets no limit on the number of variants. Assay also sets no limit on which parts a variant uses. A variant with skills only tests a skill. A variant with a settings object only tests a hook. A variant with both tests the combination of the two.

A variant is a complete configuration. It is not a rule that modifies another configuration. Therefore an artifact with no code examples needs no special treatment, and a change of any kind becomes a new variant.

### Variant folders

A variant folder, `variants/<name>/`, is only a group of related files: the parts of one variant. Jobs use the files by their paths. Many jobs can use the same folder, in one experiment or in many experiments. The experiment never names a variant, and there is no manifest of the parts.

The `phase0-tdd` experiment (section 17) shows the relation:

```
experiments/phase0-tdd/experiment.toml
  jobs = ["jobs/phase0-cross-control.yaml", "jobs/phase0-cross-tdd.yaml",
          "jobs/phase0-extra.yaml", "jobs/phase0-local.yaml"]
            │
            ├─ phase0-cross-control.yaml   no part            → condition: control
            │
            └─ phase0-cross-tdd.yaml ┐
               phase0-extra.yaml     ├─ parts from variants/instrument-tdd/
               phase0-local.yaml     ┘                    → condition: instrument-tdd

variants/instrument-tdd/
  tdd/SKILL.md, tests.md, mocking.md      the skill
  extra-instruction.md                    the extra instructions
  variant.toml                            the description (optional)
```

Each of the three jobs gives the agent the same two files by their paths:

```yaml
# jobs/phase0-cross-tdd.yaml (part)
extra_instruction_paths: [variants/instrument-tdd/extra-instruction.md]
agents:
  - model_name: anthropic/claude-haiku-5-5
    skills: [variants/instrument-tdd/tdd]
```

The summary puts the trials of the three jobs together in one condition, `instrument-tdd`, because their parts come from the same folder. A job name cannot do this, because three jobs have this condition. The control job gives no part, so its trials are the condition `control`.

The rules:

1. **The name.** The condition of an agent is the variant folder that its parts come from. An agent with no part is the control. If the parts of an agent come from two variant folders, or from outside `variants/`, Assay refuses the plan.
2. **The identity.** The identity of a condition is the digest of the content of the parts that the agent receives. The validity check compares it with what ran (section 8, check 8).
3. **Shared parts are copies.** A variant that has a part of another variant holds its own copy of that part. For example, `variants/tdd-ts-with-gate/` holds a copy of the skill of `variants/tdd-examples-ts/`. The comparison of the two variants proves that the copy is identical.
4. **The description.** An optional file, `variants/<name>/variant.toml`, describes the artifact. It never names a part. It is beside the skill directories, and never inside one, so it never goes into the container.

```toml
# variants/tdd-examples-ts/variant.toml
label     = "TDD skill, TypeScript examples"
published = true                        # the artifact as its author released it
source    = "mattpocock/skills"
```

| Field | Content |
|---|---|
| `label` | A name for people |
| `published` | `true` when the artifact is the version that its author released |
| `instrument` | `true` for an instrument variant |
| `source`, `source_path`, `source_hash`, `edits` | The provenance of a frozen artifact |

An **instrument variant** holds an instrument skill. The skill makes a behavior occur, so that a person can check a measurement. The summary gives no effect size for an instrument variant. The summary never shows an instrument variant as an artifact under test.

### Comparability

Assay calculates the difference between two bundles, part for part. It does this for each pair of conditions that the summary compares.

- A comparison between a variant and the control is always valid.
- A comparison between two variants is **controlled** when exactly one part is different. Then the rules below apply.
- When more than one part is different, the summary marks the comparison `UNCONTROLLED`.

The rules for a controlled comparison between two variants:

- The token counts of the two bundles differ by 5% or less. Without this rule, the length of the prompt confounds the measured effect. The study from ETH found that long context files can decrease the success rate.
- The file name, the front matter, and the description of each skill are the same in both bundles. Therefore both variants have the same chance to activate.
- Skill directory names are unique inside one bundle. Harbor removes a duplicate name and keeps the last copy, and a duplicate therefore changes the result with no error.
- A person writes the changed part. Code examples compile, and they pass the linter of their language.
- The same text as extra instructions in one variant, and as an instruction file in the other, is a controlled comparison of the delivery.
- Two variants have the same tools when their tools locks have the same content.

### The instruction file

The **instruction file** is a file of standing instructions that the harness loads from disk on its own, such as `CLAUDE.md` or `AGENTS.md`. The agent can read it again or change it during the trial. It is a different part from **extra instructions**, which Harbor adds to the prompt.

1. **One file, one content.** A variant has one instruction file for every harness. The recorder of each harness knows the one name that its harness loads: `CLAUDE.md` for Claude Code, and `AGENTS.md` for opencode, pi, and Codex. Assay writes the file under that name only. Thus the harness never loads the content two times. Text for one harness only is a different variant.
2. **At the repository root.** The agent class of Assay writes the file at the root of the seed repository. Assay does not use the global location of a harness (such as `~/.claude/CLAUDE.md`). A harness gives a global file a different frame from a project file, so the two are different treatments.
3. **Out of the history.** The agent class writes the file after the `seed` commit. It lists the file in `.git/info/exclude` of the task repository and of `trace.git`. Thus no snapshot holds the file: not `seed`, not `final`, and not a snapshot after a tool call.
4. **Edits are results.** The recorder calculates the digest of the file at setup and after the agent stops. It writes the file name and the two digests (`absent` if the agent deleted the file) to `instruments.json`. A changed file is a result, not an infrastructure failure. The trace holds the edit as a tool call. A **file write** stays defined over the seed repository.
5. **Plan time.** The `kwargs.instruction_file` of an agent is a part of its variant. It must be in the variant folder of the agent, and its content is part of the digest of the condition. A control agent has no instruction file. `lock.json` records only the path, so the digests in `instruments.json` prove the content.

### Environment tools

**Environment tools** are command-line programs that only the trials of one variant have. They come from a **tools image**. The job file mounts the tools image as a read-only folder. Thus the container of the control and the container of the variant differ only by that folder.

1. **The tools lock.** The folder `variants/<name>/tools/` holds a **tools lock** and the Dockerfile that builds the tools image from it. The tools lock lists the download address and the SHA-256 checksum of each file. The build fails if a checksum does not agree. The identity of the tools is the content of the tools lock, and not the digest of an image built from it. A rebuild with `--no-cache` gives a new image digest, so an image digest is not a stable identity.

   The tools lock is a TOML file with one `[[file]]` entry for each download. The Dockerfile downloads each file, checks it, and puts the programs in `/opt/assay-tools/bin/`. The checksums below are placeholders, and the list of wheels is shortened:

   ```toml
   # variants/security-semgrep/tools/tools.lock
   [[file]]                          # a static build: one archive, one program
   name   = "gh"
   url    = "https://github.com/cli/cli/releases/download/v2.83.0/gh_2.83.0_linux_amd64.tar.gz"
   sha256 = "<64 hex>"

   [[file]]                          # semgrep has no static build, so the bundle holds its own Python
   name   = "python"
   url    = "https://github.com/astral-sh/python-build-standalone/releases/download/<release>/cpython-3.11.18+<release>-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
   sha256 = "<64 hex>"

   [[file]]                          # one entry for each wheel that semgrep needs, its dependencies included
   name   = "semgrep"
   url    = "https://files.pythonhosted.org/packages/<path>/semgrep-1.183.0-cp310.cp311.cp312.cp313.py310.py311.py312.py313-none-manylinux_2_34_x86_64.whl"
   sha256 = "<64 hex>"
   ```

   | Field | Content |
   |---|---|
   | `name` | A name for people. It does not set the name of a program. |
   | `url` | The download address of one file. A wheel entry gives a full file address, never a version range, so pip resolves nothing. |
   | `sha256` | The checksum of the file. The build fails if the file does not agree. |

2. **The tag.** The tag of the tools image is `assay-tools/<name>`. The tag names the variant folder, and thus the tools lock `variants/<name>/tools/tools.lock`. The image has a label that holds the digest of the tools lock that built it.
3. **Delivery.** The job file of the condition mounts the tools image under `environment.mounts` (`type: image`, `read_only: true`) at `/opt/assay-tools`. Assay fixes this target. The mount `source` is the tag. The control job has no tools mount.
4. **PATH.** In `setup()`, the agent class links each file in `/opt/assay-tools/bin/` into `/usr/local/bin`. Setup refuses a tool whose name `command -v` already finds, because a link must never hide a system program such as `/usr/bin/git`. No snapshot holds the links. The verifier also sees the tools.
5. **The record.** For each trial, the recorder calculates one digest of the mounted tree at setup and writes it to `instruments.json`. A build of Python bundles must set `SOURCE_DATE_EPOCH`, or two builds from one tools lock give different digests.
6. **Plan time.** `assay experiment` checks that the image exists locally and that its label holds the digest of the current tools lock. If the image is missing, or the label does not agree, Assay builds it from the tools lock. Thus a missing image is never an infrastructure failure at trial time. A missing mount image stops a trial at environment start, so this check is necessary.
7. **Builds.** The build downloads files from GitHub releases and PyPI, at build time only. A tool must be a static build or a build for the glibc of Debian bookworm. A musl build does not run in the task images.
8. **No text.** Assay adds no text about the tools. The instruction file or the extra instructions of the variant tell the agent about the tools.

Replay needs no tools image. It runs only the images of the task packs.

### Where hook scripts live

This section applies to a hook that is a part of an artifact under test. The hooks of the measurement instruments use a different route (section 8).

A hook command is a shell string. A short hook needs no file. A long hook needs a script, and that script must reach the container on every trial.

Put the script inside a skill directory. Harbor uploads each skill directory to `/harbor/skills/<name>/` for each trial. The directory stays there for the full trial. This route holds the script independent of the task image, which is the property Assay needs.

The execute bit of a file stays only if the file on the host has it. Harbor does not add it, and the skill digest does not include file modes. Therefore the hook command starts the script through the shell: `bash /harbor/skills/<name>/hook.sh`.

Put the settings object inline in the job configuration, and not as a file path. For a file path, the lock records the path only and not the content. Inline settings put the exact hook declaration into the `config.json` and the `lock.json` of each trial.

### Harnesses

A **harness** is the agent program that drives the model in a trial. It has its own system prompt and tools. Harbor 0.24 runs about 40 harnesses, and one job can mix harnesses.

A harness is usable in an experiment only when it has a **recorder** and a **reader** (section 8). Claude Code has both. Harbor runs opencode, pi, and Codex, and each of them writes ATIF with verbatim tool arguments and has a hook after each tool call. Thus each of them can have a recorder. Their gaps are:

| Harness | Gaps |
|---|---|
| Claude Code | The exit code is in the result text of a failed call only. |
| pi | Nearly complete. |
| opencode | A failed call loses its result and its error flag, and the hook does not fire when a tool fails. The recorder must recover failed calls, for example from the session export. No exit codes and no time for each tool call. |
| Codex | It speaks only the OpenAI Responses API. It edits through `apply_patch`. The exit code is in the result text only. |

Assay uses a harness that gives verbatim tool arguments. A harness that only drives a terminal (`mini-swe-agent`, `terminus-2`) gives file content inside a shell command. `aider` writes no ATIF. Assay does not use these harnesses.

### Version pins

Harbor releases a new version every two to four weeks, often with breaking changes. Claude Code releases a new version almost every day. Thus each trial must use pinned versions of both, and each trial must record them ([issue #10](https://github.com/LeeSanderson/Assay/issues/10)).

**Harbor.** The file `pyproject.toml` at the root of the repository pins `harbor==0.24.0` exactly. The repository commits `uv.lock`. Each job runs through the locked `harbor run` (ADR 0002). Both harness hosts use the same lock file. A change of the Harbor version is a commit to `uv.lock`.

**The harness.** Each job file pins the harness version in `kwargs.version`. All model tiers of one experiment use the same version.

**A change of the harness version.** If the pinned version fails, use the version of the `stable` channel on the day of the change. Run again each trial that used the old version. Change the version first only if the failure is a known regression of the harness.

**The install route.** Harbor installs the pinned harness in each trial through its bootstrap script. A task image never holds a harness, because a change of the image digest is a change of the task pack, and because an installed harness ties its version to the image. When agents have no network access, the install route changes. This is an open item.

**The record.** `instruments.json` holds the Harbor version of each trial. The `lock.json` file of each trial holds the requested harness version in `kwargs.version`. The ATIF trajectory holds the version that ran, in `agent.version`. The validity check compares these values (section 8).

### Limits of Harbor for this purpose

| Need | State |
|---|---|
| Two or more skills in one trial | Supported. `--skill` repeats. Harbor records the name, the source, and the digest of each skill in the job lock. |
| Hooks | Harbor has no hook flag. Harbor uploads the settings object without inspection, and Claude Code reads the `hooks` key from it. |
| A plugin as one unit | Not supported. Split the plugin into skills, an MCP file, and a settings object. |
| Slash commands from a plugin | No mechanism exists. An experiment that needs commands needs a different runner. |
| The ACP agent path (`--agent acp:<id>`) | This path does not copy skills. Use a native adapter for every Assay trial. |
| An instruction file | Harbor supports no instruction file for any harness. The agent class of Assay writes it. |
| A different image for each job | Not supported. Harbor has no job-level image override. Environment tools use a mount. |
| A terminal recording | Only the Terminus-2 agent writes `recording.cast`. |
| Skills or settings from the task | The Claude Code adapter also copies any `~/.claude/skills` in the task image. Claude Code also reads a `.claude/settings.json` in the seed repository. A task image and a seed repository must hold neither. |
| Per-test results | `ctrf.json` is a convention of the task and not a product of Harbor. The task writes it from the test runner. |
| More than one verifier pass | Harbor runs `tests/test.sh` one time. The script itself runs the tests as many times as the task needs. |
| MCP on pi | Harbor pins pi to `>=0.84.1,<0.86.0` for MCP. The current pi is 1.4.0. |

### Model tiers, and the local tier

A **model tier** is one model on the model axis, hosted or local. The local tier gives three things. It removes the money cost from one model tier, and therefore it buys repetitions. It extends the central question below the cheapest hosted model: is a model on your own hardware sufficient for this work? It also runs against a private codebase with no data that leaves the network.

Harbor supports this through environment variables. For the `claude-code` adapter, set `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` under the `env:` key of the agent. Harbor then gives `model_name` to the server without change, and the server must accept that exact name. Harbor has no special flags for a local model. The default network mode of a task is `public`, and therefore the container reaches the server at its network address (L7).

#### The reference setup

The reference setup is guidance. Another local setup can be different from it. Each local setup must obey the requirements below, and it must write the record that L6 gives.

| Item | Reference setup |
|---|---|
| Hardware | AMD Ryzen AI Max+ 395 with 128 GB of unified memory |
| Operating system | Windows. Harbor and Docker run in WSL2 on the same machine. |
| Inference server | `llama-server` from llama.cpp, native on Windows (not in WSL2). It is built from fork commit `c49ebdb` (`charlie12345/experimental/rocmi4-iu4`, gfx1151 ROCm), because Laguna needs this fork. |
| API | The Anthropic Messages API (`/v1/messages`) of `llama-server`. The local tier needs no proxy. |
| Model | `laguna-s-2.1` from Poolside, quantization `Q4_K_M`. The context is 262,144 tokens, with one slot. |
| Chat template | The template in the model file, without change. It accepts the system message that Claude Code sends in the middle of the conversation. |
| Thinking | On. This is the default of the model. |
| Address | `http://192.168.1.252:8080`. A DHCP reservation keeps this address fixed. |
| Fallback model | Qwen3-Coder-30B-A3B, if the local trial time is too long (Risk P3). It is a different local setup with its own L6 record. A Qwen model needs a changed chat template, because its default template rejects a system message in the middle of the conversation. |

*Source: Harbor v0.24.0, research in [issue #2](https://github.com/LeeSanderson/Assay/issues/2) and [issue #3](https://github.com/LeeSanderson/Assay/issues/3), and the decision in [issue #4](https://github.com/LeeSanderson/Assay/issues/4).*

#### Requirements

| # | Requirement |
|---|---|
| L1 | One harness serves every model tier of a comparison across model tiers. Two harnesses confound the model with the harness. A comparison across harnesses holds the model tier fixed. |
| L2 | The harness records verbatim tool arguments. The preferred harness for the local tier is Claude Code against a server that speaks the Anthropic format, because it keeps the trajectory of the hosted tiers unchanged. |
| L3 | The local tier declares a `concurrency_group` with `n_concurrent = 1`. One local server answers one request at a time. The hosted tiers keep their parallel trials. |
| L4 | The local tier runs with a higher `timeout_multiplier`. This key applies to the full job and not to one agent, so the local tier runs as a separate job. The summary gives the timeout rate for each model tier. A trial that reaches the timeout is not a failure of capability. |
| L5 | The summary gives seconds for each solved task pack beside the figure in USD. The local model has a price of zero, so that Harbor can calculate the cost of its steps. The token counts stay correct. |
| L6 | The results record the model file, the quantization, the chat template, the inference server with its version, the full server command line with its environment flags, the thinking setting, the hardware, and the operating system. The agent configuration rejects unknown keys, so this record goes in a file beside the job configuration (`jobs/<job>.L6.md`). A model name alone is not a stable identifier. A different quantization, build option, or thinking setting is a different model. |
| L7 | The container reaches the server at its network address, and not through `host.docker.internal`. In WSL2, `host.docker.internal:host-gateway` goes to the WSL2 virtual machine and not to the Windows host. Thus the reference setup adds no `extra_hosts` overlay and changes no networking on the `main` service. This also keeps the egress sidecar correct. If the address cannot be reached, use WSL2 mirrored networking and `127.0.0.1`. |
| L8 | The local tier is one model tier of the same experiment. It uses the same task packs, the same variants, and the same verifiers as the hosted tiers. Its job runs on its own host, and it is one job of the experiment. |
| L9 | Every model tier sets `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` under `env:`. Background requests (titles and summaries) use the one server slot and remove the prefix cache. Every model tier sets them, so the harness stays the same (L1). |
| L10 | One setting, `ASSAY_LOCAL_BASE_URL`, holds the server address. No other file contains the address. To use a different local setup, change this one setting. |

```yaml
# jobs/phase0-local.yaml — the local tier
timeout_multiplier: 3.0             # job level; no agent has this key
agents:
  - import_path: instruments.agent:InstrumentedClaudeCode   # Claude Code with the recorder
    model_name: laguna-s-2.1        # the server receives this exact name
    concurrency_group: local-llm
    n_concurrent: 1
    env:
      ANTHROPIC_BASE_URL: ${ASSAY_LOCAL_BASE_URL}           # one setting only (L10)
      ANTHROPIC_API_KEY: dummy
      DISABLE_NON_ESSENTIAL_MODEL_CALLS: "1"                # every model tier (L9)
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"
    kwargs:
      version: "<pinned Claude Code version>"
```

## 8. The trial record

The **trial record** is the fixed, harness-neutral telemetry of one trial. It is a view and not a file ([ADR 0005](docs/adr/0005-trial-record-is-a-view-over-a-recorder-contract.md)). Each harness has two parts that make it:

- A **recorder** writes the trace folder in the trial. All recorders write the same contract.
- A **reader** builds the trial record in memory from the trace folder and from the Harbor trial folder.

Assay writes no normalized copy of the record. The digest of the record for resume is the digest of the files that the reader reads. No evaluation reads the raw Harbor folder. If an evaluation needs a fact, the fact becomes a field of the record, and each reader gives it or marks it absent.

### The recorder contract

The recorder writes to `/logs/artifacts/trace/` in the trial. Harbor copies this folder to `<trial>/artifacts/logs/artifacts/trace/`.

| File | Content |
|---|---|
| `trace.git` | A git repository, linear from the `seed` commit to the `final` commit. Each other commit is a snapshot after a tool call (or after a turn) that changed the repository. |
| `trace.jsonl` | One line for each fire of the recorder. |
| `instruments.json` | The digest of the instruments, the merged settings object, the Harbor version, `granularity`, the overlap flag, the instruction-file digests, and the tools digest. |

Each line of `trace.jsonl` holds these fields:

| Field | Value |
|---|---|
| `seq` | The number of the fire, from 0 |
| `ts` | The time, in ISO-8601 |
| `event` | `seed`, `call`, or `final` |
| `tool_use_id` | The id of the tool call. It connects the line to the tool call in ATIF. |
| `changed` | `true` or `false`. `null` if the recorder failed. |
| `commit` | The snapshot commit, only when `changed` is `true` |
| `paths` | The status (`A`, `M`, or `D`) and the path of each file that changed since the last snapshot. The recorder does not find renames (`--no-renames`). Thus a renamed file gives `D` for the old path and `A` for the new path. |
| `error` | A short cause, only when the recorder failed |

The record does not copy the arguments or the result of the tool. ATIF holds them. Other data that one harness needs goes in a sibling folder, and only the reader of that harness reads it.

**Granularity.** `instruments.json` declares `granularity`: `per-tool-call` or `per-turn`. It also declares whether the tool calls of one step can overlap. Claude Code and pi can run the tool calls of one message in parallel, so a snapshot after one call can hold the change of another call. The attribution of a change to a call is exact for a step with one call. An evaluation that needs exact attribution treats an overlapping step with more than one call as one unit, or marks it.

**Seed and final.** The agent class makes the `seed` snapshot before the agent starts. After the harness stops, it makes the `final` snapshot. The `final` commit is always the last commit. If the `final` snapshot finds a change, a tool call was not recorded, and the trial is an infrastructure failure.

### The record

The record holds ordered **steps**. Each step has a `source` (agent, user, or system), a timestamp, input tokens, cached tokens, output tokens, and the cost when the harness gives the cost for each step. Each step holds its **tool calls**.

Each tool call has an id, a verbatim `name`, verbatim `arguments`, and a `kind` that the reader sets: `shell` (with a normalized `command`), `web`, `skill`, or `other`. There is no `edit` kind. **File writes** come from the repository history only, and the reader does not normalize edit calls.

**The required core.** Each reader must give these fields in full:

- Every tool call in order, failed calls included.
- The history, joined to the calls, with its granularity.
- The totals of tokens, cost, and time.
- The identity: the harness name, its pinned version and the version that ran, the model tier, the task pack path and digest, the variant bundle digest (empty for the control), the instruments digest, and the Harbor version.

The condition and the cell are labels that Assay finds at plan time from the job files. They are in `TrialInput` and not in the record. The validity check compares the condition with the record.

**Optional parts.** A reader gives these parts or marks them absent. It never guesses them: the result of a call, the error flag, the exit code, the duration of each call, and the cost of each step. An evaluation declares the optional parts that it needs. Assay refuses an experiment before any job runs if an evaluation needs a part that the reader of one of its harnesses cannot give.

**Checkout.** `checkout(commit)` gives a clone of `trace.git` at that commit, with its history back to `seed`. Thus a scanner can compare `seed` with `final` (for example semgrep `--baseline-commit`, golangci-lint `new-from-rev`, or gitleaks `seed..final`).

### The Claude Code recorder

The Claude Code recorder is the trace hook. It keeps snapshots only. It does not run tests in the trial. The tests run after the trial, on the snapshots.

1. The hook fires on `PostToolUse` and on `PostToolUseFailure`, for every tool (matcher `*`). A failed tool can also write a file, and a `Bash` call can write a file. Each fire writes a `call` line.
2. The hook is synchronous. Thus the agent cannot change the repository while the hook runs. The timeout of the hook is 10 seconds.
3. On each fire, the hook compares the repository with the last snapshot. If the repository changed, the hook makes a new commit in `trace.git`. This repository has its own index. The hook never reads or writes the `.git` directory of the agent.
4. The snapshot holds each file under `/app`, the seed repository, except `.git/`, `node_modules/`, and the instruction file. The hook ignores each `.gitignore` file, because an agent can write a `.gitignore` file that hides its own files.
5. On each fire, the hook appends one line to `trace.jsonl`, also when the repository did not change.

**The hook is silent.** The hook always stops with exit code 0. It writes nothing to standard output, and it returns no JSON. Thus Claude Code gives nothing from the hook to the agent, and the hook does not steer the agent. The hook writes its errors to `errors.log` in the trace folder. If the hook fails, it still appends its line with an `error` field. The hook sets its own git configuration: no global configuration file, `safe.directory=*`, and a fixed name and date for each commit.

**How the hook gets into the container** ([ADR 0001](docs/adr/0001-instruments-via-custom-agent-class.md)). The hook does not go through `--skill` or through the settings object of a variant. A skill directory must hold a `SKILL.md` file, and the agent then sees the skill in each condition. Instead, every Assay job runs `instruments.agent:InstrumentedClaudeCode` through `import_path`. This class is a small subclass of the `claude-code` agent of Harbor. In `setup()`, the class does these steps:

1. It uploads the directory `instruments/` to `/harbor/instruments/`. The directory holds the hook script, a static `jq` binary that the hook uses to read its input, and the class.
2. It adds the instrument hooks to the settings object of the variant, after the hooks of the variant. The `kwargs.config` value of the job keeps the settings of the variant only, without change. The hook command is `bash /harbor/instruments/trace.sh`.
3. It stops the job with an error if the settings of the variant contain `disableAllHooks`, or another key that stops the instrument hooks.
4. It runs the hook script one time with `event` set to `seed`. This makes the first snapshot, the seed repository, before the agent starts.
5. It writes the instruction file and the tool links of the variant, if the variant has them (section 7).
6. It writes `instruments.json`. Harbor records the import path of the class, but not its content. Harbor records its own version only in the job lock, and not in the trial. This file closes these gaps.

After the harness stops, the class runs the hook script one time with `event` set to `final`.

The Claude Code reader is `analyze/trial.py`. A failed call has `extra.tool_result_is_error` set to true on its observation result, and its content starts with `Exit code N`. A call that passes has no exit code field.

### The validity check

The validity check of the trial record runs on each trial after its job, and before any evaluation. It replaces `trace-check`. It has ten checks:

| # | Check | Class of a failure |
|---|---|---|
| 1 | Instruments: the digest is the digest of the committed `instruments/`. `granularity` and the overlap flag are declared. | Halt |
| 2 | Seed: a `seed` line exists, and its commit is the first commit. | Infrastructure failure |
| 3 | Calls: for `per-tool-call`, each tool call (failed calls included) has exactly one line, by id. For `per-turn`, each agent step has one line. | Infrastructure failure |
| 4 | Errors: no line has an `error` field. | Infrastructure failure |
| 5 | Final: a `final` line exists, and it found no change. | Infrastructure failure |
| 6 | Harness version: the version that ran is the pinned version. Mixed versions of one harness in one job stop the job. | Halt |
| 7 | Harbor version: the version in `instruments.json` is the version in the committed `uv.lock`. | Halt |
| 8 | Condition: the variant digest that ran agrees with the condition that Assay found for the agent at plan time. | Halt: a wrong condition is a change in the configuration, and a new trial reads the same files |
| 9 | Claimed paths: each path that the reader finds in the arguments of a successful call is in the snapshot of that call, or the content did not change. Assay skips this check when the reader gives no paths. | Infrastructure failure |
| 10 | Required core: the reader built every field of the required core. | Infrastructure failure |

Check 9 tests the recorder, and not the detection of file writes. The Claude Code reader gives the paths of `Write`, `Edit`, and `MultiEdit` calls. To find a change for a `Write` call, the reader compares its content with the file in the previous snapshot. A file write through `Bash` relies on the history only.

A trial in which the agent changes no file is a result, and not a failure.

The check writes `trial-check.json` in `analysis/<experiment>/<job>/<trial>/`. Only a trial that passes all ten checks goes to the evaluations.

## 9. Evaluations

An **evaluation** is a step that turns the trial record and the repository of one trial into metrics. Evaluations are Python. They run after the trials, one trial at a time. An evaluation can start its own containers.

An evaluation is **built-in** (referenced by name) or **experiment-local** (referenced by a path in `experiments/<name>/`).

### The evaluation contract

A module exposes one value:

```python
EVALUATION = Evaluation(
    name="trajectory",
    evaluate=evaluate,              # (TrialInput) -> JSON value, for one trial
    depends_on=("replay", "agent-runs"),
    needs=(),                       # optional parts of the record that it needs
    pins=pins,                      # (TrialInput) -> {key: value}
    online=False,
)
```

1. **`evaluate`.** It gets one trial and returns a JSON value. It evaluates `seed` and `final` in the same call. A raised exception gives an error result. Assay never reuses an error result. Each evaluation that depends on an error result gets an error result, and Assay does not call it.
2. **`depends_on`.** Dependencies are hard only. Assay stops before any job runs if the experiment lists an evaluation before its dependency, or does not list a dependency.
3. **`pins`.** It gives the pinned external inputs: tool image digests, the hash of a rule set, or the date of a vulnerability database snapshot.
4. **`online`.** An evaluation can use online services, because it runs outside the sandbox of the trial. An online evaluation must write `data_version` in its value (a database time or a response hash). Assay reuses its results only when every trial has a result that it can reuse. Otherwise it runs again for every trial of the experiment, and never for a part of them.
5. **Listable.** An experiment can list an evaluation only if every level of every factor can give the evaluation its inputs. Thus a harness comparison compares only the parts of the record that each harness gives.

`TrialInput` holds:

| Field | Content |
|---|---|
| `job`, `trial`, `cell`, `task_pack` | The identity of the trial in the experiment |
| `record` | The trial record (section 8) |
| `deps` | The value of each dependency |
| `options` | The options from `experiment.toml` |
| `out` | An empty folder for the files of the evaluation |
| `containers` | `pack_image(pack)`, `run(image, cmd, mounts, network, timeout)`, and `service(image, ports)` |
| `checkout(commit)` | A clone with history, with `seed()` and `final()` |

The `network` value of `run` is `none` (the default), `internal`, or `online`. Assay refuses `online` if the evaluation does not declare `online=True`.

### Results and reuse

Assay writes the result of each evaluation for each trial to `analysis/<experiment>/<job>/<trial>/<evaluation>/result.json`. The file holds `evaluation`, `digest`, `code`, `inputs`, `started_at`, `duration_sec`, `value`, and `error`. The `out/` folder of the evaluation is beside it.

Assay reuses a result when its digest is the same and it holds no error. The digest has two parts:

- **`code`.** The digest of the import closure: the module of the evaluation, and each module of the repository that it imports. Assay finds the closure from the imports. This digest is coarse, but it is never stale.
- **`inputs`.** The digests of the trial record, the task pack, the options, the value of each dependency (`deps.<name>`), and each pin (`pins.<key>`). Assay uses the digest of the value of a dependency. Thus a dependency that runs again and gives the same value causes no evaluation after it to run again.

### Built-in evaluations

| Name | Metrics | State |
|---|---|---|
| `replay` | The test state of each snapshot (Part II, section 16) | First slice |
| `agent-runs` | The test runs of the agent and their agreement with replay | First slice |
| `trajectory` | Test-first order, red-to-green order, the TDD loop | First slice |
| `reference-replay` | The reference tests on each snapshot | Later |
| `sonar` | The `new_*` measures of a local SonarQube Community Build server, `seed` against `final`, one project per trial | Later |
| Scanner diffs | New findings of semgrep, golangci-lint, ESLint, jscpd, lizard, gosec, govulncheck, osv-scanner, gitleaks, and `npm audit`, `seed` against `final` | Later |

semgrep, golangci-lint, and gitleaks compare against the `seed` commit by themselves. For the other scanners, the evaluation compares the SARIF or JSON output of `seed` and `final` in Python.

The commands `assay replay`, `assay agent-runs`, `assay trajectory`, and `assay trace-check` stay as thin entry points for one job folder. Outside an experiment, `assay trajectory` can run without its dependencies.

## 10. The summary

The **summary** is the optional last step of an experiment. It combines the evaluation results of all trials. It is the only step that crosses trials, and thus the only home of paired deltas and confidence intervals. It always runs again.

The summary decides what to compare. A descriptive summary gives the values of each cell with their confidence intervals, and needs no baseline. A summary that compares levels takes its comparisons as options.

A module exposes `SUMMARY = Summary(summarize)`. `summarize(view, options, out)` gets an `ExperimentView`:

- The varied factors, with their levels.
- The kept trials, each with its cell, its task pack, its record, and the value and error of each evaluation.
- The expected trials of each cell.
- Every event of the experiment log.

The summary writes to `analysis/<experiment>/summary/`.

### The `paired-delta` summary

`paired-delta` is a built-in summary. Its options name the metric values and the comparisons. A comparison is a baseline, or a list of explicit pairs of levels:

```toml
[summary]
use     = "paired-delta"
options = { metrics = ["reward"], baseline = { job = "phase0-cross-control", model = "anthropic/claude-haiku-5-5" } }
```

A `baseline` selects one agent in one job. The fields must match exactly one agent, or Assay refuses the plan. That agent gives the baseline level of each varied factor. With no comparison option, `paired-delta` compares each variant with the control.

A comparison changes one factor only. Two levels of a factor compare only where they share the levels of the other factors. `paired-delta` marks a level that shares no other levels with its pair, and it gives no delta for it.

`paired-delta` pairs by task pack: for each level, it takes the mean over the repetitions, and it subtracts the mean of the other level of the pair. It gives bootstrap confidence intervals over the task packs. It marks short cells from the expected and kept counts. An experiment-local summary can call it.

### Reporting rules

- Every value carries a confidence interval. The summary gives no bare point estimates.
- Each cell shows its count of kept trials beside its confidence interval.
- If the spread of a cell is larger than its effect, the summary marks that cell `UNSTABLE`. It does not give a mean value for that cell.
- The summary gives the total cost from the experiment log, with the cost of discarded trials, and the rate of infrastructure failures for each cell.
- Verification is deterministic where this is possible. If a metric needs a model to grade it, the evaluation repeats the grade and reports the rate of agreement.

## 11. `assay experiment`

```
uv run assay experiment <name> [--job J]... [--dry-run] [--from-scratch] [--retries N] [--debug]
```

| Option | Effect |
|---|---|
| `<name>` | The experiment `experiments/<name>/experiment.toml`. One experiment for each invocation. |
| `--job J` | Run only these jobs. It can repeat. The evaluations and the summary always cover every trial of the experiment. |
| `--dry-run` | Do the plan-time checks, print the plan, and stop. It costs nothing. It never calls Harbor or `Containers`, and it deletes nothing. |
| `--from-scratch` | Delete `results/<experiment>` and `analysis/<experiment>`, the experiment log included, then run. With `--dry-run`, it only prints. |
| `--retries N` | After each job, run its infrastructure failures again, up to N times. The default is 0. |
| `--debug` | Give `--debug` to Harbor. |

There is no general pass-through of options to Harbor. A pass-through would change the Harbor configuration, break resume, and make the committed job files no longer the source of truth. `assay run` stays the launcher for one job, such as a smoke trial.

### Plan time

Before any job runs, `assay experiment` does these checks. A failure stops the invocation at no cost.

1. `experiment.toml` and each job file are valid. `experiment.toml` has no unknown key, and no options table for an evaluation that it does not list.
2. Each harness version is pinned.
3. The parts of each agent come from one variant folder, or the agent has no part and is the control (section 7).
4. Each evaluation comes after its dependencies, and each dependency is listed.
5. Each evaluation can get its inputs from every level of every factor.
6. The options of the summary are valid. For example, a `baseline` matches exactly one agent.
7. Every `${VAR}` in a selected job file is set (for example `ASSAY_LOCAL_BASE_URL`).
8. Each tools image exists and agrees with its tools lock, or Assay builds it (section 7).

The plan gives the jobs, the expected trials of each cell, and what resume will delete, run again, or reuse.

### The run

For each selected job, in order:

1. Assay runs the job through Harbor with `--jobs-dir results/<experiment>`.
2. Assay runs the validity check on each trial.
3. Assay discards each infrastructure failure and runs it again, up to `--retries`.

After the last job, Assay runs the evaluations on every trial of the experiment, then the summary.

Jobs run one after another. Parallel jobs are an open item.

### Resume

Resume is the default. A new invocation continues the experiment:

1. Assay deletes each earlier infrastructure failure, after it writes a log event.
2. Harbor resumes each job. It runs again only the trials that have no `result.json`. Harbor keeps a trial with an error unless Assay deletes it.
3. Assay reuses each evaluation result whose digest is the same.
4. The summary always runs again.

Each invocation is also a retry. There is no lifetime limit for one trial. Harbor's own `retry.max_retries` stays at 0, so retries occur only in Assay.

### Infrastructure failures

A trial is an **infrastructure failure** when its outcome does not show the agent at work on the task under its declared conditions. Otherwise it is a result, and it stays, also when it ended badly. In Harbor 0.24, the verifier runs after an agent timeout and after a non-zero exit of the agent. Thus a model service outage gives a reward of 0 that looks like a failure of the agent. Assay discards it by its exception type.

| Outcome | Class |
|---|---|
| `AgentTimeoutError` | Result |
| `ContextWindowExceededError`, `OutputTokenExceededError`, `AgentSafetyRefusalError` | Result, counted for each cell |
| `VerifierTimeoutError` | Result. The reference tests failed. The gold solution shows that the timeout is sufficient. |
| No changed file | Result |
| `ApiRateLimitError`, `ApiOverloadedError`, `ApiInternalServerError`, `ApiConnectionClosedError`, `ApiResponseStalledError`, `NetworkConnectionError` (a local model server that stops is one of them) | Infrastructure failure. Assay discards its reward. |
| `SandboxBuildFailedError`, `EnvironmentStartTimeoutError`, `HealthcheckError`, `AgentSetupTimeoutError`, an error in the `setup()` of the agent class, `CancelledError` | Infrastructure failure |
| `RewardFileNotFoundError`, `RewardFileEmptyError`, `VerifierOutputParseError`, `AddTestsDirError`, `DownloadVerifierDirError` | Infrastructure failure, named in the summary. A repeat shows a defect in the task pack. |
| A plain `NonZeroAgentExitCodeError`, `UnknownApiError`, and each exception type that this table does not list | Infrastructure failure. The summary lists it by type, so that a person classifies each new type. |
| Validity checks 2, 3, 4, 5, 9, 10 | Infrastructure failure |
| `ApiUsageLimitError`, `AgentAuthenticationError`, `ModelNotFoundError`, validity checks 1, 6, 7, 8 | **Halt** |

A **halt** is an infrastructure failure that another run would only repeat. A halt takes effect when the current job ends. There is no cancel in the middle of a job. No retries and no more jobs run. Assay keeps the results, and it marks the trials of the halt as infrastructure failures. Thus the next invocation runs them again, after a person fixes the cause.

**Pairing.** A trial that runs again takes the place of the discarded trial: the same job, condition, task pack, and repetition. An infrastructure failure that is never resolved makes its cell short by one repetition. Assay never imputes a value for it.

### The experiment log

The **experiment log** is `analysis/<experiment>/experiment-log.jsonl`. Assay appends to it across invocations. Each line has `at`, `invocation` (an id for each invocation), and `event`:

| Event | Fields |
|---|---|
| `invocation-started` | The command line, the Assay commit, and the Harbor version |
| `job-started` | Job, file, and condition |
| `job-finished` | The exit code, the trials, and the duration |
| `trial-discarded` | Job, trial, cell, task pack, the cause (`{exception}` or `{failed_checks}`), tokens, `cost_usd`, and duration |
| `halt` | The fields of `trial-discarded`, and a message |
| `evaluation-finished` | The counts of results that ran, were reused, and are errors, and the duration |
| `summary-written` | The files |
| `invocation-finished` | The outcome: `complete`, `halted`, `interrupted`, or `error` |

## 12. Architecture

```
assay/
  pyproject.toml                 pins harbor==0.24.0
  uv.lock                        committed
  assay/
    cli.py                       assay run, assay experiment, and the thin entry points
  tasks/<language>/<slug>/
    instruction.md               prompt for the agent
    task.toml                    [verifier] [agent] [environment] [metadata]
    environment/Dockerfile       pinned image of the task pack
    solution/solve.sh            gold solution, to calibrate the verifier
    tests/test.sh                withheld reference tests, writes reward.json
  variants/
    <name>/                      every part of one variant: skills, settings, extra instructions, instruction file
    <name>/variant.toml          optional: label, instrument, published, provenance; never a part
    <name>/tools/                tools lock and the Dockerfile of the tools image
  instruments/
    agent.py                     InstrumentedClaudeCode: recorder, instruction file, tool links
    trace.sh                     the Claude Code recorder
    jq                           static binary that the recorder uses
  jobs/
    <job>.yaml                   committed Harbor job configurations
    <job>.L6.md                  the local setup record of a local job
  experiments/<name>/
    experiment.toml              factors, jobs, evaluations, summary
    *.py                         experiment-local evaluations and summary
  analyze/
    trial.py                     the Claude Code reader
    replay.py, agent_runs.py,
    trajectory.py                built-in evaluations
    trace_check.py               the validity check
  results/<experiment>/<job>/    output tree of Harbor, kept locally and not committed
  analysis/<experiment>/         evaluation results, summary, experiment log; not committed
```

A skill directory holds a `SKILL.md` file, because the `--skill` flag of Harbor takes a directory.

The raw trajectories stay in `results/` on the local machine, and not only the totals. The repository does not commit `results/` or `analysis/`, and `.gitignore` excludes them. Results in this field come from a second analysis with a metric that was not obvious at first. A second run costs money. A second analysis is free, and resume runs only the new evaluation.

## 13. Platform build plan, success criteria, and risks

### Build plan

| Slice | Deliverable | Acceptance criteria |
|---|---|---|
| P1 | The first slice of `assay experiment` | It runs `experiments/phase0-tdd/` end to end, with the recorder contract, the Claude Code reader, the ten validity checks, resume, the ported `replay`, `agent-runs`, and `trajectory`, and an experiment-local Phase 0 summary. The spec issue gives the acceptance criteria. |
| P2 | `paired-delta` and `reference-replay` | A TDD summary over a full matrix uses `paired-delta`. |
| P3 | The instruction file and environment tools | A variant with each part runs, and `instruments.json` records its digests. |
| P4 | `sonar` and the scanner diffs | An experiment lists them, and each result records its pins. |
| P5 | Online evaluations and `Containers.service` | An online evaluation records `data_version` and runs again for every trial together. |
| P6 | A recorder and a reader for another harness | The harness passes the ten validity checks. |

P1 comes first, because the paid Phase 0 jobs run through it.

### Success criteria

1. One command runs an experiment end to end, and runs it again after an interruption with no repeated cost.
2. A new experiment needs only an `experiment.toml`, job files, and its evaluations. It needs no change to the platform.
3. Assay re-implements nothing that Harbor supplies.
4. A published corpus that another person can run under Harbor without an installation of Assay.
5. Each trial records exactly what it had: its versions, its variant bundle, its instruction file, and its tools.

### Risks

| # | Risk | Validation | Fallback |
|---|---|---|---|
| P1 | The hook route depends on behavior that the Harbor documents and the Claude Code documents do not describe: hooks from `--settings` fire, and a subclass of the agent can upload files in `setup()`. A new version of Harbor can change the agent class. | Every trial passes the validity check. The smoke trial confirms that the tool call ID in ATIF is the same as `tool_use_id`. | Pin the version of Harbor in `uv.lock`, and record it in each trial. If a new version breaks the subclass, change the subclass or keep the old version. |
| P2 | The Anthropic-format route for the local tier is not tested. | Phase 0 runs one local trial against `/v1/messages` of the local server and inspects the trajectory. | Use opencode for every model tier. This needs the opencode recorder first (P6). |
| P3 | The local tier is slow, and wall clock replaces money as the binding constraint. | Time one local trial in Phase 0, and multiply by the local trials of the experiment. | Cut the local tier to one language, or reduce its repetitions and widen its confidence intervals. |
| P4 | A combination study multiplies the variants. Six bundle parts with two states each give 64 variants. Job files by hand become a burden. | Count the trials before each job, and compare the count against the budget. | Use a fractional design. Test each part against the control first, and test only the pairs that show an effect. Generate job files later, if necessary. |
| P5 | Harbor resumes a job only when its configuration is exactly the same. | The resume acceptance test of P1. | Keep job files committed. Never pass options through to Harbor. |
| P6 | A recorder for another harness cannot give the required core. opencode loses failed calls. | P6 passes the ten validity checks. | Leave the harness out of the experiments until its recorder gives the required core. |
| P7 | The BuildKit cache of Docker Desktop removes the cache of a task pack, and a cached build becomes cold. | Time the builds over a long experiment. | Accept the time, or pin a shared base image. |

### Open items

| # | Item |
|---|---|
| 1 | A recorder and a reader for opencode, pi, and Codex. Does the reference llama.cpp fork serve `/v1/responses` and the freeform `apply_patch` of Codex? Is gemini-cli or qwen-coder worth a recorder? |
| 2 | Job files that Assay generates from the declared factors, if job files by hand become a burden (Risk P4). |
| 3 | Parallel jobs, if the wall clock becomes the constraint for the hosted tiers. |
| 4 | The operation of a local Sonar server: start-up cost, one server across evaluations, and the quality profile pinned with the server version. |
| 5 | Scanner inputs: the source of semgrep rules (the community rules forbid redistribution), dependencies for type-checking scanners, pinned vulnerability databases against online lookups, and gitleaks as a long-term choice. |
| 6 | Factors other than harness, model tier, and condition, such as a context limit. |
| 7 | Task packs from outside the repository at run time (such as the Harbor hub), checked against the task-pack contract. |
| 8 | The install route of a harness when the agent has no network access. |

---

# Part II — The experiment catalogue

## 14. The TDD skill-transfer experiment

The TDD skill-transfer experiment asks: does the value of the TDD skill change with the language of its examples, with the target language, and with the model tier? Phase 0 is its measurement spike. The `phase0-tdd` experiment runs Phase 0 through `assay experiment`.

The experiment uses one harness, Claude Code. It does not vary the harness, and therefore the token counts stay comparable.

### Design

```
3 model tiers   local open-weight, Haiku, Sonnet
3 conditions    control + 2 artifact variants
2 languages     TypeScript, Go
6 task packs    reference tests withheld
5 repetitions
= 540 trials

The two hosted tiers are 360 trials at £40 to £110.
The local tier is 180 trials at no money cost, and it is the slowest model tier.
```

The varied factors are `model_tier` and `condition`. The summary compares each variant with the control. The comparison between model tiers is decided in Phase 1.

## 15. The TDD pack recipe

A task pack comes from one Exercism exercise. The same exercise gives one pack in TypeScript and one pack in Go. The Phase 0 packs are `tasks/typescript/split-second-stopwatch/` and `tasks/go/split-second-stopwatch/`, and they go into the corpus without change.

**The seed repository.** The seed repository holds the stub file of the exercise and the toolchain configuration. It holds no test file. The Dockerfile copies it to the image and makes it a git repository with one commit, `seed`. The image holds the installed dependencies.

| Language | Seed repository |
|---|---|
| TypeScript | The stub `.ts` file, `package.json`, `yarn.lock`, `.yarnrc.yml`, `tsconfig.json`, `jest.config.cjs`, `babel.config.cjs`, `eslint.config.mjs` |
| Go | The stub `.go` file, `go.mod` |

Do not copy these parts of the Exercism directory: `.meta/` (it holds the solution), `.docs/`, `.exercism/`, `.vscode/`, `test-runner.mjs`, and each test file. No file in a seed repository, and no package in the Yarn cache of the TypeScript image, names Exercism. The stubs hold no Exercism boilerplate.

**The prompt.** `instruction.md` is the `.docs/instructions.md` file of the exercise without change, then an **Interface** section, then one footer. The Interface section states the interface that the reference tests check: the type and format of each value the stub returns, the format of each input, and each error case with its exact message. It is written from the reference tests only and adds no behavior that they do not check. It does not show the reference tests, and it does not name a test command. The footer is the same in each pack, and only the file name changes:

> Implement the solution in `<stub file>`. Keep the exported names and signatures as they are. Tests that you cannot see will check your solution.

The footer does not tell the agent to write tests. The prompt is the same in each condition, and an instruction about tests would change the control too.

**The sources.** The reference tests and the gold solution come from the Exercism track without change, at one pinned commit. Only mechanical changes are permitted: `xit` becomes `it`, and the reference test files get the prefix `assay_reference_` (Go) or `assay-reference.` (TypeScript). `solution/solve.sh` copies `.meta/proof.ci.ts` or `.meta/example.go` over the stub.

**The image.** `environment/Dockerfile` starts from `node:<LTS>-bookworm` or `golang:<version>-bookworm`, pinned by digest. The versions agree with the pinned Exercism commit.

**The limits.** The agent timeout is 1800 seconds, and a job for a slow model tier can make it longer. The verifier timeout is 600 seconds. Each container has 2 CPUs and 4096 MB of memory. The network is open, because the agent must reach the model API. The web tools of the agent are off ([ADR 0003](docs/adr/0003-web-tools-off-by-default.md)).

**The verifier.** `tests/test.sh` runs two passes:

1. **The outcome pass.** The script copies the repository to a scratch directory and removes each test file of the agent from the copy. Then it adds the reference tests and runs them. In Go, all test files of one package compile together, and one bad test of the agent would make each reference test fail. If the agent changed a signature of the stub, the reference tests do not compile, and the reward is 0.
2. **The agent pass.** The script runs the tests of the agent in the repository without change.

In Phase 0, `reward.json` holds these metrics. Each value is a number.

| Metric | Value |
|---|---|
| `reward` | 1 if each reference test passes, else 0 |
| `reference_compiles` | 1 or 0 |
| `reference_passed`, `reference_total` | Counts from the outcome pass |
| `agent_tests_compile` | 1 or 0 |
| `agent_tests_passed`, `agent_tests_total` | Counts from the agent pass. 0 if the agent wrote no test. |

Phase 1 adds the metrics of the quality tier.

## 16. The TDD measurements

### The version 1 variants

Version 1 measures the TDD skill. Each variant uses the skills part only. The published skill has worked examples in TypeScript. The second variant holds the same prose with the examples rewritten in Go.

The corpus has two languages. Therefore these two variants produce every combination of example language and target language:

| Target language | control | `tdd-examples-ts`<br>(published) | `tdd-examples-go` |
|---|---|---|---|
| **TypeScript** | no artifact | examples **match** the target | examples **do not match** the target |
| **Go** | no artifact | examples **do not match** the target | examples **match** the target |

This is a crossover design. Each language is a match in one cell and a mismatch in another cell. Therefore the transfer effect does not confound with the difficulty of the language. A result such as "Go is harder than TypeScript" moves both Go cells together, and it cancels in the comparison.

Two comparisons come out of the table:

- `tdd-examples-ts` minus the control gives the value of the artifact as its author published it.
- match minus mismatch gives the transfer penalty. The transfer penalty is the part of the value that depends on examples in the language of the reader.

### Paired design

Every condition runs against the same task pack, the same seed repository, and the same prompt. The summary computes each effect size inside one task pack. This method gives the largest available decrease in variance, and it costs nothing.

### Activation gate

In some trials the agent never activates the artifact. The summary excludes these trials from the effect calculation. The summary gives the activation rate as a separate metric.

### Metric tiers

| Tier | Metrics | Source |
|---|---|---|
| Outcome | The withheld reference tests pass. `pass^k` reliability across repetitions. | `reward.json` |
| Process | Test-first order. Red-to-green order. TDD loop. Test count. Assertion density. Mock density. | The trial record, through `replay`, `agent-runs`, and `trajectory` |
| Cost | Input tokens, output tokens, and reasoning tokens. Cost in USD. Duration. Turn count. **Cost for each solved task pack.** | The trial record |
| Quality | Mutation score of the tests that the agent wrote. Coverage delta. Lint and type check are clean. Diff size. | `reward.json` |

### How Assay measures the order of actions

The trial record holds each tool call of the agent in order. For Claude Code, Harbor writes `agent/trajectory.json` in ATIF, the Agent Trajectory Interchange Format, and the Claude Code reader reads it. Each step holds a sequential `step_id`, an ISO-8601 `timestamp`, a list of `tool_calls`, and an `observation`.

Each tool call holds `function_name` and `arguments`. For Claude Code the arguments are complete and verbatim. A `Write` call holds the file path and the full content. An `Edit` call holds the old string and the new string. A `Bash` call holds the command, and the observation holds the output and a pass or fail flag. A `Skill` call appears as a tool call with that name. The agent can also read a skill with a `Read` call on its `SKILL.md`, and the activation gate counts both.

Therefore `trajectory` reads the order of the tool calls directly from the trial record.

Two limits apply:

- One step holds every tool call of one agent turn. Inside a step, the order is the order of the array. The timestamp belongs to the turn and not to each call.
- A `Bash` call can write a file, and ATIF does not show which file. A `Write` or `Edit` call can fail and change no file. Therefore `trajectory` finds the file writes in the history, and not in the arguments. A file-writing `Bash` call is a `Bash` call whose trace line has `changed` set to `true`. The status and the class of the path have no effect on this rule. `trajectory` marks each trial that has a file-writing `Bash` call. Offline replay cannot rebuild that trial.

#### Test-first order

Test-first order looks at the order of writes only. It does not look at the test state. The red-to-green order gives the test state.

Use these rules:

1. A write is a tool call whose trace line gives a path with the status `A` (added) or `M` (modified). The tool has no effect, and thus a `Bash` call can make a write. A path with the status `D` (deleted) is not a write. ATIF gives the order of the writes (`step_id` and the position in the array). The trace gives the paths. The content of the write has no effect. A stub is a write. The content of the seed repository is not a write.
2. Only a path inside the seed repository counts as an implementation write. A test write can also come from the `file_path` of a `Write`, `Edit` or `MultiEdit` call that did not fail, or from a redirection (`>`, `>>`, `tee`) in a `Bash` command. These sources find a test file outside the seed repository, such as `/tmp/try.test.ts`, and a test file that one `Bash` call writes and deletes. The redirection source is a heuristic: it misses a file that a command writes in another way. A test file is kept when the last snapshot of the trace holds it. A test file that is not kept is a throwaway test.
3. The language of the task pack sets the class of each path:

   | Language | Test file | Implementation file | Neutral |
   |---|---|---|---|
   | TypeScript | `*.test.ts`, `*.spec.ts` | Each other `*.ts` file, but not `*.config.*` | All other files |
   | Go | `*_test.go` | Each other `*.go` file | All other files |

4. Find the first write to a kept test file and the first write to an implementation file. Only these two writes decide the verdict. Writes after them have no effect. Throwaway tests decide the verdict only when there is no kept test file.
5. The deciding point is the step of the earlier of the two writes. If one of the two writes does not occur, the deciding point is the last step of the trial.
6. Give the trial one verdict:

   | Verdict | Rule |
   |---|---|
   | `test-first` | The first test write is in an earlier step than the first implementation write. |
   | `implementation-first` | The first implementation write is in an earlier step than the first test write. |
   | `same-turn` | The two writes have the same `step_id`. In one turn, the agent cannot run the test before the implementation exists. |
   | `throwaway-tests` | The agent writes an implementation file and keeps no test file, but writes one or more throwaway tests. The test anchor is the first throwaway test, with `kept: false` and its source (`trace`, `tool` or `bash`). |
   | `no-test` | The agent writes an implementation file and writes no test file. |
   | `no-implementation` | The agent writes no implementation file. |

**How a person checks `trajectory`.** Phase 0 compares `trajectory` with a person on the ten hosted trials:

1. A `jq` command, kept separate from `trajectory`, prints a neutral listing of each trial. Each line gives the `step_id`, the position in the array, the `function_name`, the path or the `Bash` command, and the `paths` value of the trace line for that tool call (joined by `tool_use_id`). The listing gives no class and no verdict.
2. The person labels all ten trials from the listing before `trajectory` runs. The person can read `trajectory.json` when the listing is not sufficient. For each trial, the labeling sheet records the first test write and the first implementation write as anchors (`step_id`, position, and path), the verdict, and a note. An anchor can be a `Bash` call.
3. `trajectory` then runs on the ten trials. `assay compare-labels` compares the labels with the result of `trajectory`. The two agree on a trial when the verdict and the two anchors are the same.
4. For each difference, the person finds the cause. If the script is wrong, fix `trajectory` and run it again on all ten. If the person is wrong, correct the label and write the cause in the note. If a rule is not clear, correct the rule here, and then both sides apply it again.
5. "Agrees every time" means one full pass over the ten trials with no difference. The sheet keeps a record of each correction.

### How Assay measures red and green

A trajectory shows what the agent wrote. It does not show the state of the tests after each write. Harbor runs the verifier one time, after the agent stops.

A test run that does not compile is red.

The **test state** is the result of the tests of the agent on one state of the repository. It has four values: `pass`, `fail`, `red-compile` (the tests do not compile), and `no-tests`. The value `no-tests` is not green.

Three ways can recover the test state over time:

1. **The agent runs the tests.** A `Bash` call that runs the test command gives a pass or fail flag in the observation. A failed run sets `tool_result_is_error`, and its content starts with `Exit code N`. This way is free. It works only when the agent chooses to run the tests.
2. **Offline replay.** The trajectory holds the full content of every write. A script can rebuild the repository at each step and run the tests on each rebuilt state. This way fails for a trial with a file-writing `Bash` call. Assay does not build this way.
3. **Replay of the trace snapshots.** The recorder keeps a snapshot of the repository after each tool call that changed it. The `replay` evaluation runs the tests on each snapshot after the trial. This way also works for a trial that writes files through `Bash`.

Replay of the trace snapshots is the only source of the test state, for every trial. All conditions thus use the same method. The test runs of the agent are a cross-check only.

#### Replay of the trace snapshots

For each trial, `replay` does these steps on each snapshot in `trace.git`:

1. It starts a new container from the image of the task pack (pinned by digest), with no network. The timeout is the `timeout_sec` value of the verifier.
2. It puts the snapshot in `/app` and runs `tests/test.sh` of the task pack without change. Both passes run.
3. It keeps all the fields of the `reward.json` file that `test.sh` writes. The fields of the agent pass give the test state:

   | Test state | Rule |
   |---|---|
   | `no-tests` | `agent_tests_total` is 0 |
   | `red-compile` | `agent_tests_compile` is 0 |
   | `fail` | `agent_tests_passed` is less than `agent_tests_total` |
   | `pass` | All the tests of the agent pass |

   Apply the rules from the top. The first rule that is true gives the state.

Replay works on a trial when all of these conditions are true:

1. Each snapshot gives a test state. A replay timeout or an error of the container or the infrastructure is a failure. A test that does not compile is not a failure, because `red-compile` is a test state.
2. The replay of the `final` snapshot gives a `reward.json` file that is the same, field for field, as the `reward.json` file of the verifier in the trial.
3. `replay` runs two times on all the trials of the job. The two runs give the same test state and the same fields for each snapshot.

Replay runs on the laptop host. It needs the images of the task packs only, and not the model server.

**The output.** The value of `replay` holds one entry for each snapshot: `seq` and `commit` from `trace.jsonl`, the `tool_use_id` and the `step_id` of the tool call that made the snapshot, all the fields of `reward.json`, the test state, the duration, and an `error` field when the replay failed. It also holds whether replay works on the trial. The verifier logs of each snapshot go in its `out/` folder, one folder for each snapshot.

#### The cross-check with the test runs of the agent

A `Bash` call is a test run when its command agrees with the pattern for the language of the task pack:

| Language | Test run |
|---|---|
| TypeScript | `jest`, `npx jest`, `npm test`, `npm run test`, `yarn test`, `pnpm test`. Make this list agree with the test runner of the task pack. |
| Go | `go test` |

Use these rules:

1. A test run that selects some of the tests (for example `go test -run X`, `jest <file>`, or `-t`) is `partial`.
2. A test run that does not run in the seed repository (for example after `cd /tmp/...`) is not a test run.
3. Each test run applies to the last snapshot before it.
4. Each test run has a **run result**: `red`, `green` or `unknown`. The result comes from the summary of the test framework in the output of the call, or from the exit code:
   - A test run is piped when a `|` follows the simple command that starts the run (for example `yarn jest 2>&1 | tail -20`). The exit code of a piped run is the exit code of `tail`, `head` or `grep`, not of the tests. Thus the output alone gives the result of a piped run.
   - A run that is not piped gets its result from the summary in the output when there is one, and from the exit code when there is no summary. Exit code 0 is `green`, and any other exit code is `red`.
   - When neither the output nor the exit code shows red or green, the result is `unknown`.
   - The summary patterns are data in the language rules, next to the test-run patterns. TypeScript (jest): `red` when the summary gives failed tests or failed suites, or the output gives "Test suite failed to run". `green` when the summary gives passed tests and no failure. Go (`go test`): `red` when the output gives a `--- FAIL` or `FAIL` line, a `[build failed]` line, or a compile-error header (`# <package>`). `green` when the package lines are `ok` and there is no failure. A `?` line (no test files) gives neither.
5. The run agrees with the replay when a `green` result meets a `pass`, or a `red` result meets a test state that is not `pass`. Thus `fail` and `red-compile` are the same for this check. An `unknown` result is not compared.

The value of `agent-runs` holds one entry for each test run: `tool_use_id`, the `partial` flag, the exit code, the result and its source (`output` or `exit_code`), the snapshot, the test state of the snapshot from `replay`, and the agreement. The exit code stays as raw data. A `partial` run, and a run with an `unknown` result, have no agreement value.

Phase 0 gives two values for this way:

- **Coverage.** The share of snapshots that have a test run after them and before the next snapshot.
- **Agreement.** The share of test runs that are not `partial` and agree with the replay.

For each difference, a person finds the cause. The cause can be the pattern, the observation, or the replay. Only a replay that does not give the environment of the trial is a failure of the replay.

#### Red-to-green order and the TDD loop

These two metrics use the test runs of the agent together with the test state of each snapshot. Each metric needs a test that the agent ran, and not only a test that the agent wrote. `trajectory` calculates the two metrics from the values of `replay` and `agent-runs`, and from the trial record.

**A seen state.** A seen state is a test run of the agent that agrees with the replay. A `partial` test run can give a seen state.

| Seen state | Rule |
|---|---|
| Seen red | The result of the run is `red`, and the test state of the snapshot is `fail` or `red-compile`. |
| Seen green | The result of the run is `green`, and the test state of the snapshot is `pass`. |

The result of the run is the result in the value of `agent-runs` (see "The cross-check"), not the exit code. A test run that does not agree with the replay is not a seen state. For example, `go test -run TestNew` passes, but the replay of the snapshot gives `fail`. A test run on a `no-tests` snapshot is not a seen state, whatever its result. A test run with an `unknown` result is not a seen state.

**Red-to-green order.** Only the first seen states decide the verdict. Give the trial one verdict:

| Verdict | Rule |
|---|---|
| `red-to-green` | The first seen state is seen red, and a later seen state is seen green. |
| `green-first` | The first seen state is seen green. The agent did not see the tests fail. |
| `never-green` | The trial has seen states, and all of them are seen red. |
| `not-observed` | The trial has no seen state. |

Red-to-green order and test-first order are two different metrics. No rule connects them. For example, a trial can be `implementation-first` and `red-to-green`. The analysis can compare the two.

**The TDD loop.** The TDD loop looks at all the seen states of the trial, in order. Two or more seen states of the same color, one after the other, count as one. The trial gives three counts:

1. **Cycles.** The count of the changes from seen red to seen green.
2. **Tests never seen red.** Find each two seen green states, one after the other, with no seen red between them. Add the increase of `agent_tests_total` between them. A test that was red when the agent did not run the tests counts here.
3. **Refactor steps.** Find each two seen green states, one after the other, with no seen red between them. Count the gap when it has a write to a test file or an implementation file (see "Test-first order"), and `agent_tests_total` does not change. A gap that adds tests is not a refactor step.

For example, the seen states red, green with 1 test, green with 1 test after an edit of the implementation, red, green with 2 tests, green with 2 tests after an edit of the test file, give 2 cycles, 0 tests never seen red, and 2 refactor steps.

These metrics use the test state of the whole suite, and not of each test. Thus, when the agent adds two failing tests and makes them both pass, this counts as one cycle. The snapshots stay in `trace.git`. Thus a later version of `test.sh` can give the result of each test, and replay can run again with no new trial.

**How a person checks the two metrics.** Phase 0 compares `trajectory` with a person on the ten hosted trials. The person labels these metrics in the same pass as test-first order, and uses the same procedure (see "How a person checks `trajectory`"), with these changes:

1. The `jq` listing also gives the `partial` flag and the exit code of each test run of the agent. For each tool call that made a snapshot, it gives the test state from the replay and `agent_tests_total`. The listing gives no seen state, no verdict, and no count.
2. For each trial, the labeling sheet also records the red-to-green verdict, two anchors (the `tool_use_id` of the first seen red and of the first seen green), the three counts of the TDD loop, and a note.
3. The two agree on a trial when the verdict, the two anchors, and the three counts are the same.
4. "Agrees every time" means one full pass over the ten trials with no difference, for each metric.

## 17. Phase 0: the measurement spike

### The phase 0 instrument

Phase 0 uses one instrument variant, `instrument-tdd`, for both languages. It holds a frozen copy of the `tdd` skill from `mattpocock/skills`, with changes for trials that have no user. The skill directory is `variants/instrument-tdd/tdd/`, and it holds `SKILL.md`, `tests.md`, and `mocking.md` only.

The variant folder also holds `extra-instruction.md`. The jobs of the variant give its two parts: `skills: [variants/instrument-tdd/tdd]` and `extra_instruction_paths: [variants/instrument-tdd/extra-instruction.md]`. The file `variants/instrument-tdd/variant.toml` describes it:

```toml
# variants/instrument-tdd/variant.toml
label       = "Instrument: TDD skill adapted for trials with no user"
instrument  = true
published   = false
source      = "mattpocock/skills"
source_path = "skills/engineering/tdd/SKILL.md"
source_hash = "535d1a6f3bd5bded8971e7e4ea76538907cbff6b6d32c39cf97b669869dcd383"
edits       = [
  "seams: the agent selects the seams and writes them down; no user confirms them",
  "removed the paragraph that refers to codebase-design",
  "removed the reference to code-review; the rule against refactoring in the loop stays",
  "description: use for every task that adds or changes code",
  "removed agents/openai.yaml",
]
```

The record of the source and the changes stays in `variant.toml`, outside the skill directory. A file in the skill directory goes into the container, and the agent can read it.

The examples stay in TypeScript for the Go trials too. Phase 0 checks `trajectory`, and it does not measure the value of the skill in each language.

The description alone did not activate the skill on the smoke trial. Thus each job of the instrument variant also gives an extra instruction that names the skill. Each instrument trial records whether the skill loaded.

### The smoke gate

The smoke trial runs through `assay run jobs/phase0-smoke.yaml`, and not through the experiment. The smoke gate passes on three criteria, all from the trajectory analysis of the smoke trial:

1. The skill loads before the first file write.
2. The trial is not flagged for web access.
3. Red-to-green order is not `not-observed` when the trial has an agent test run with a red or green result.

The reward is not a criterion: the gate checks the setup, not the agent. Run the gate again after a change to a task pack, to the recorder, or to the evaluations, before the paid Phase 0 jobs. The trials that ran on the task packs before the Interface sections and the Exercism scrub (spec #36) are superseded. Do not use them in a Phase 0 figure.

### The `phase0-tdd` experiment

`experiments/phase0-tdd/experiment.toml` is the example in section 5. It has four jobs:

| Job | Condition | Trials |
|---|---|---|
| `phase0-cross-control` | `control` | 4: Haiku and Sonnet, TypeScript and Go |
| `phase0-cross-tdd` | `instrument-tdd` | 4: Haiku and Sonnet, TypeScript and Go |
| `phase0-extra` | `instrument-tdd` | 2: Haiku, TypeScript and Go |
| `phase0-local` | `instrument-tdd` | 1: the local tier, TypeScript |

`phase0-local` is last. It runs on the host of the local server, with `--job phase0-local`. Before that job runs, the other jobs give a short cell for the local tier.

The summary is experiment-local, `experiments/phase0-tdd/summary.py`. It writes `analysis/phase0-tdd/summary/phase0-summary.md` and `phase0-summary.json`. It gives each acceptance number of Phase 0, and also:

- For each cell, the counts of discarded, halted, and kept trials against the expected trials. It marks short cells.
- The cost of the hosted trials against the limit of £15. This cost includes the cost of each discarded trial.
- The values of the local trial from the trial record. The values that come from the server log stay by hand.

There is no `paired-delta` in Phase 0, because each cell has one trial.

### Phase 0 acceptance

Over ten trials on the hosted model tiers:

1. `trajectory` finds the test-first order, and a person who reads the same trajectory agrees every time (see "Test-first order").
2. The summary gives the share of trials with a file-writing `Bash` call, and the share of trials in which a `Bash` call writes a test file or an implementation file.
3. Every trial passes the validity check.
4. Replay of the trace snapshots works on all eleven trials. For each failure, find the cause, fix it, and replay all eleven trials again.
5. The summary gives the coverage and the agreement of the test runs of the agent.
6. `trajectory` finds the red-to-green order and the three counts of the TDD loop, and a person agrees every time.
7. The hosted trials cost £15 or less, and this includes each trial that runs again.

One more trial runs Claude Code against a local model server, and its trajectory holds verbatim tool arguments. That trial also records its time, the prefix cache hits for each turn, the count of background requests, and the tool calls after a system message in the middle of the conversation.

**Phase 0 blocks all other phases of this experiment.**

**The Claude Code version in Phase 0.** On the day of the smoke trial, read the version of the `stable` channel of Claude Code. Write this version as `kwargs.version` in all the job files, in one commit, before the smoke trial runs. Do not change it for the remaining trials of Phase 0.

**A change of the Claude Code version in Phase 0.** Use the rule in "Version pins". Run again each Phase 0 trial that used the old version. These trials count against the limit of £15. For a failure of the local route, Risk P2 applies.

## 18. TDD build plan, success criteria, and risks

### Build plan

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 0 | Measurement spike | Section 17. |
| 1 | Corpus and conditions | Six task packs in two languages. Two variant folders. The comparison between the two variants is controlled (one different part), and it passes every comparability rule. `tests/test.sh` returns the full reward for `solution/solve.sh`. It returns zero for an empty repository. An `experiment.toml` for the full matrix. |
| 2 | Matrix run | `assay experiment` completes 360 hosted trials inside the budget. |
| 3 | Analysis | The summary gives effect sizes with confidence intervals for four tiers. It also gives activation rates, cost for each solved task pack, and `UNSTABLE` marks. |
| 4 | Write-up | A published result. The corpus is published with it. |

Phase 0 comes first because it tests the assumption under all later phases.

### Success criteria

1. A measured answer, with confidence intervals, to this question: does the value of the artifact change with the language and with the model tier?
2. A measured answer to this question: which task packs does a local open-weight model solve as well as a hosted model?
3. A cost for each solved task pack, in money and in seconds, reported for each model tier and each kind of task.

### Risks

| # | Risk | Validation | Fallback |
|---|---|---|---|
| 1 | Red-to-green state is not recoverable. Write order is visible in ATIF, but the test state between writes is not. | Phase 0 replays the trace snapshots of all eleven trials. It also gives the coverage and the agreement of the test runs of the agent, and the share of trials where offline replay can work. | If the replay cannot give the environment of the trial, and the cause cannot be fixed, make the mutation score the primary process metric. |
| 2 | Agents write code through `Bash` instead of `Write`, and offline replay fails | Phase 0 reports the share of trials with a file-writing `Bash` call, from the history | No fallback is necessary. Replay of the trace snapshots is the method for the whole matrix, and it does not use offline replay. |
| 3 | Frontier models solve Exercism task packs too easily | Measure the control in Phase 1 | The withheld tests already make the task harder. Write one or two packs from unpublished work as a control for contamination. |
| 4 | The agent never activates the artifact, and the result is a silent false null | The activation rate is a reported metric from Phase 2 | Gate the effect calculation on activation. Report the rate as a result. |
| 5 | The matched token count does not remove the length confound | Compare the variant against a placebo variant of the same length | Add a variant that holds neutral filler text. |
| 6 | The effects are smaller than the noise between trials at five repetitions | Measure the power of the Phase 2 output | Add repetitions to the cells that show an effect, and not to the whole matrix. |
| 7 | The language toolchains drift, and the results do not reproduce | Pinned images, no network access, and a dependency cache inside each image | Publish the images with the results. |

**Kill criterion.** If Phase 3 shows every effect inside the noise band on all four tiers, then the instrumentation is wrong. Correct the metrics. Do not add cells to the matrix.

### Open items

| # | Item | Needed by |
|---|---|---|
| 1 | The second language. Go is further from the assumptions of the artifact. Python is closer to real use. The specification gives Go today. | Phase 1 |
| 2 | Publication of the task packs. Publication invites replication. It also invites contamination of future training sets. | Phase 4 |
| 3 | The comparison between model tiers in the full matrix: against one baseline tier, or between each pair. | Phase 1 |
| 4 | The Phase 1 items: a network allow-list, mutation testing and coverage, and the install route of Claude Code with no network. | Phase 1 |

## 19. Sketches of the next experiments

Each sketch fits the platform as it is. Each sketch gets its own map before it is built. The open items of each sketch are not decided.

### Refactoring

- **Question.** Does an artifact make the agent refactor safely and improve quality, compared with the control?
- **Factors.** `condition`. The summary compares each variant with the control. The harness and the model tier are fixed or varied as usual.
- **Pack recipe.** The seed is a working codebase with its own tests and known smells. The prompt asks for a refactoring and fixes the public interface, so the reference tests at their seed version still apply. The reference tests are the tests of the seed plus characterization tests.
- **Evaluations.** `reference-replay` (the share of green snapshots, the longest run of broken snapshots, and whether the trial ended broken), `sonar` (`seed` against `final`: complexity, duplication, smells), and whether the agent edited the visible tests (from the history).
- **Outcome.** The reference pass of the verifier on the final repository. Each snapshot is a process metric and not a gate, because a correct rename passes through states that do not compile.
- **Summary.** `paired-delta` on the outcome, the green share, and the Sonar deltas.
- **Open.** The source of the packs. How the recipe enforces the interface rule.

### Code quality

- **Question.** Does a quality-focused artifact give better code than the control?
- **Factors.** `condition`. The summary compares each variant with the control.
- **Pack recipe.** Any packs that meet the contract. Exercism stubs work, because all code is new code. Real codebases give a stronger signal.
- **Evaluations.** `sonar` (the `new_*` measures, `seed` against `final`, one project per trial), with ESLint, golangci-lint, and jscpd as standalone fallbacks.
- **Summary.** `paired-delta` on the Sonar measures and the outcome.
- **Open.** The source of the packs. The TDD experiment can also list `sonar`, to ask whether TDD changes quality, at no model cost.

### Security

- **Question.** Does an artifact decrease the security findings that the agent adds?
- **Factors.** `condition`. The summary compares each variant with the control.
- **Pack recipe.** Seeds with a real attack surface (input handling, dependencies, secrets) and their own tests.
- **Evaluations.** Scanner diffs, `seed` against `final`: semgrep, gosec, gitleaks, osv-scanner or govulncheck, and `npm audit`. The online scanners record `data_version` and run again for every trial together.
- **Summary.** `paired-delta` on new findings by severity, and the outcome. Thus "secure because it did nothing" is visible.
- **Open.** The source of the packs. The source of the semgrep rules.

### Bug fixing on a large codebase with limited context

- **Question.** Does an artifact (such as guidance for navigation or search) help the agent fix bugs in a large codebase when the context is limited?
- **Factors.** `condition`. The summary compares each variant with the control. The context limit is a fixed setting, recorded in the job files.
- **Pack recipe.** Real repositories and bugs, vendored into `tasks/` by an import step. The reference tests are the hidden tests of the fix plus the suite of the seed.
- **Evaluations.** The outcome, tokens and cost, and exploration metrics from the trial record (files read and shell searches before the first file write).
- **Summary.** `paired-delta` on the outcome, the cost, and the exploration.
- **Open.** The repositories and bugs. What "limited context" means in operation (a cap on the context window, compaction, or limits on tools). The import step for a SWE-bench-style source.

### Harness comparison

- **Question.** How do Claude Code, opencode, and pi compare on the same tasks and model tier, under the control?
- **Factors.** `harness`. The summary compares each harness with Claude Code. The condition is fixed at the control. The model tier is fixed or varied. One job can mix harnesses.
- **Pack recipe.** The TDD packs, or any other packs.
- **Evaluations.** Only the evaluations that the recorder of each harness can feed: the outcome, tokens, cost, time, file writes, and test-first order. The red-to-green evaluations come back when the opencode recorder records failed calls.
- **Summary.** `paired-delta` across harnesses, with the model tier fixed.
- **Open.** The recorders (Part I, open item 1). A local model tier for Codex depends on support for `/v1/responses`.
