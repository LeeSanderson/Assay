# Assay — Product Requirements Document

**Owner:** Lee Sanderson · Version 2.0 · 18 October 2026

*This document uses Simplified Technical English (ASD-STE100). Spelling is American, as Rule 1.14 requires.*

---

## 1. What Assay is

**The name.** An assay is a test that measures the strength or the purity of a substance. A metallurgist assays an ore to find how much metal it holds, because the claim on the label is not the measurement. Assay does the same for a context artifact.

Assay measures the value of a context artifact. A context artifact is a skill, a rules file, an instruction file, or a hook for a coding agent. This document uses the short form "artifact".

Assay measures two effects of an artifact. The first effect is the change in the work of the agent. The second effect is the change in cost. Assay also measures how these two effects change with the model tier and with the target language.

Assay answers questions of this form. Does the TDD skill improve the output of Haiku in Go? Does it improve the output of Sonnet in TypeScript by the same amount? Is an open-weight model on local hardware sufficient for either? What does each result cost?

Assay has three parts:

- A corpus of task packs in more than one language.
- A protocol that runs the task packs as a controlled experiment.
- An analyzer that converts agent trajectories into effect sizes.

Assay is not a runner. Assay is not a harness. Assay is not a benchmark platform. [Harbor](https://www.harborframework.com/) runs every trial.

## 2. How Assay works

Assay is a pipeline of three stages around Harbor.

```
  assay/tasks/**              assay/conditions/**
  (task packs)                (control + variant bundles)
        │                            │
        └──────────┬─────────────────┘
                   ▼
         ┌───────────────────────┐
         │  HARBOR               │   -m model   -k repetitions
         │  runs the matrix      │   --skill    -n concurrency
         └───────────┬───────────┘   one image for each task pack
                     ▼
         results/<job-id>/<trial>/
           agent/trajectory.json     ATIF: every tool call, in order
           verifier/reward.json      outcome and quality metrics
           artifacts/logs/artifacts/ files collected from /logs/artifacts
           lock.json                 resolved inputs, with skill digests
           result.json               tokens, cost, duration
                     ▼
         ┌───────────────────────┐
         │  assay/analyze        │   trajectory to process metrics
         │                       │   trials to paired deltas and CIs
         └───────────┬───────────┘
                     ▼
              report.md / report.json
```

### Stage 1: Harbor runs the matrix

The task packs use the native `task.toml` format of Harbor. Therefore Assay needs no adapter layer.

Harbor supplies each condition to the agent through the `--skill` flag and the `--extra-instruction-path` flag. One job configuration expands into the full matrix. The matrix is model, condition, language, task pack, and repetition.

### Stage 2: The verifier writes metrics

Each task pack contains a `tests/test.sh` script. Harbor copies `tests/` to `/tests/` after the agent stops, and therefore the agent cannot read the reference tests. The script runs inside the container of the agent. Then the script writes `reward.json`.

`reward.json` holds a dictionary of metrics. It does not hold one pass value or one fail value. Harbor records the complete agent trajectory beside it. Harbor also records the token count, the cost, and the duration of each trial.

### Stage 3: The analyzer produces the report

The analyzer reads the output tree of Harbor. It produces two results that Harbor cannot produce. The first result is a set of process metrics from the trajectory. The second result is a set of paired effect sizes with confidence intervals.

### Division of responsibility

| Harbor owns | Assay owns |
|---|---|
| The sandbox and one container image for each task pack | The task packs and their withheld reference tests |
| Model selection, agent selection, and matrix expansion | The condition set and the construction of each condition |
| Repetitions, `pass@k`, retries, and concurrency | Pairs, effect sizes, and confidence intervals |
| Capture of the trajectory and the cost | Interpretation of the trajectory into process metrics |
| The result tree on disk | The report |

## 3. Why Assay is necessary

Two decisions occur every day across the industry. The first decision is the choice of model tier for a kind of work. The second decision is the choice of artifact. No measurement supports either decision today.

The published evidence shows that a simple measurement gives a false result. Three studies from 2026 examined repository context files ([arXiv 2602.11988](https://arxiv.org/abs/2602.11988), [2601.20404](https://arxiv.org/abs/2601.20404), [2607.27250](https://arxiv.org/html/2607.27250)). The studies found a small change in the success rate of tasks. The studies also found a large change in cost. One study measured a decrease of 29% in runtime and 17% in output tokens. Another study measured an increase of more than 20% in cost.

A harness that measures only the success rate therefore reports no effect. The real effect is large. Assay measures both.

No current tool closes this gap:

- `skill-creator` from Anthropic runs paired trials with a skill and without a skill. It uses one language only. It has no model tier axis. An agent grades the output instead of a real test suite.
- The test-generation benchmarks use Python only. Three examples are SWT-Bench, TDD-Bench-Verified, and TestGenEval. Therefore no current corpus can measure transfer between languages.
- Harbor supplies the execution matrix. Harbor has no concept of an experimental condition. Harbor computes `pass@k`, and `pass@k` is not an effect size.

## 4. Scope

Version 1 includes these items:

- Six task packs in TypeScript and Go. The packs come from Exercism specifications. Each pack withholds its reference tests, and therefore the agent must write its own tests.
- One control condition and two artifact variants. Section 5 defines a condition and a variant.
- Three model tiers. Two tiers are hosted models. One tier is an open-weight model that runs on local hardware.
- Four metric tiers for every trial: outcome, process, cost, and quality.
- A report that gives paired effect sizes with confidence intervals for each cell.

Version 1 excludes these items:

- All execution code, sandbox code, and scheduler code.
- A plugin interface, a web interface, and a hosted service.
- Public leaderboards and rankings of frontier models.
- A harness axis. Every trial of version 1 uses one harness, and therefore the token counts stay comparable.

## 5. Experiment specification

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

### Task packs

A task pack comes from one Exercism exercise. The same exercise gives one pack in TypeScript and one pack in Go. The phase 0 packs are `tasks/typescript/split-second-stopwatch/` and `tasks/go/split-second-stopwatch/`, and they go into the corpus without change.

**The seed repository.** The seed repository holds the stub file of the exercise and the toolchain configuration. It holds no test file. The Dockerfile copies it to the image and makes it a git repository with one commit, `seed`. The image holds the installed dependencies.

| Language | Seed repository |
|---|---|
| TypeScript | The stub `.ts` file, `package.json`, `yarn.lock`, `.yarnrc.yml`, `tsconfig.json`, `jest.config.cjs`, `babel.config.cjs`, `eslint.config.mjs` |
| Go | The stub `.go` file, `go.mod` |

Do not copy these parts of the Exercism directory: `.meta/` (it holds the solution), `.docs/`, `.exercism/`, `.vscode/`, `test-runner.mjs`, and each test file. A seed repository holds no `.claude/` directory, and a task image holds no `~/.claude/skills`.

**The prompt.** `instruction.md` is the `.docs/instructions.md` file of the exercise without change. One footer follows it. The footer is the same in each pack, and only the file name changes:

> Implement the solution in `<stub file>`. Keep the exported names and signatures as they are. Tests that you cannot see will check your solution.

The footer does not tell the agent to write tests. The prompt is the same in each condition, and an instruction about tests would change the control too.

**The sources.** The reference tests and the gold solution come from the Exercism track without change, at one pinned commit. Only mechanical changes are permitted: `xit` becomes `it`, and the reference test files get the prefix `assay_reference_` (Go) or `assay-reference.` (TypeScript). `solution/solve.sh` copies `.meta/proof.ci.ts` or `.meta/example.go` over the stub.

**The image.** `environment/Dockerfile` starts from `node:<LTS>-bookworm` or `golang:<version>-bookworm`, pinned by digest. The versions agree with the pinned Exercism commit. A change of digest is a change of the task pack.

**The provenance.** The `[metadata]` table of `task.toml` records the source repository, the commit, and the path of each copied file, each mechanical change, the file list of the seed repository, and the image digest.

**The limits.** The agent timeout is 1800 seconds, and a job for a slow model tier can make it longer. The verifier timeout is 600 seconds. Each container has 2 CPUs and 4096 MB of memory. The network is open, because the agent must reach the model API.

**The verifier.** `tests/test.sh` runs two passes:

1. **The outcome pass.** The script copies the repository to a scratch directory and removes each test file of the agent from the copy. Then it adds the reference tests and runs them. In Go, all test files of one package compile together, and one bad test of the agent would make each reference test fail. If the agent changed a signature of the stub, the reference tests do not compile, and the reward is 0.
2. **The agent pass.** The script runs the tests of the agent in the repository without change.

In phase 0, `reward.json` holds these metrics. Each value is a number.

| Metric | Value |
|---|---|
| `reward` | 1 if each reference test passes, else 0 |
| `reference_compiles` | 1 or 0 |
| `reference_passed`, `reference_total` | Counts from the outcome pass |
| `agent_tests_compile` | 1 or 0 |
| `agent_tests_passed`, `agent_tests_total` | Counts from the agent pass. 0 if the agent wrote no test. |

Phase 1 adds the metrics of the quality tier.

### Conditions

A condition controls one thing only. It controls what the agent receives in addition to the task prompt. The task prompt, the seed repository, the model, and the language are the same across all conditions.

An experiment has one control condition and one or more artifact variants.

**The control.** The agent receives the task prompt and nothing else. Harbor runs the control with none of the flags in the table below. Every effect size in the report is a difference from the control.

**A variant.** A variant is a named bundle of agent configuration. A bundle holds any combination of these four parts:

| Part | Harbor flag | Content |
|---|---|---|
| Skills | `--skill <dir>`, repeatable | One or more skill directories. A directory of directories injects all of them. |
| Hooks and settings | `--ak config=<path or JSON>` | A settings object for Claude Code. Harbor uploads it and starts the agent with `--settings`. |
| MCP servers | `--mcp-config <path>`, repeatable | An `.mcp.json` file. |
| Extra instructions | `--extra-instruction-path <path>` | Text that Harbor adds to the prompt. |

Assay sets no limit on the number of variants. Assay also sets no limit on which parts a variant uses. A variant with skills only tests a skill. A variant with a settings object only tests a hook. A variant with both tests the combination of the two.

A variant is a complete configuration. It is not a rule that modifies another configuration. Therefore an artifact with no code examples needs no special treatment, and a change of any kind becomes a new variant.

### The variant manifest

The file `variants/variants.toml` declares every variant. Each entry names the parts of the bundle. An entry also gives the relation of that variant to another variant.

```toml
[tdd-examples-ts]
label     = "TDD skill, TypeScript examples"
skills    = ["variants/tdd-examples-ts"]
published = true                        # the artifact as its author released it

[tdd-examples-go]
label        = "TDD skill, Go examples"
skills       = ["variants/tdd-examples-go"]
derived_from = "tdd-examples-ts"
differs_in   = "code-examples"

[tdd-ts-with-gate]
label        = "TDD skill and a pre-tool hook"
skills       = ["variants/tdd-examples-ts"]
settings     = "variants/gate/settings.json"
derived_from = "tdd-examples-ts"
differs_in   = "settings"
```

`assay/analyze/variants.py` reads the manifest. It builds the Harbor flags for each variant, and it tests the comparability rules.

The analyzer uses `derived_from` for two purposes.

First, the analyzer tests the comparability rules below. A variant that declares `derived_from` must obey every rule.

Second, the analyzer labels each comparison in the report. A comparison between a variant and the control is always valid. A comparison between two variants is controlled only when one variant declares `derived_from` for the other. For every other pair, the report marks the comparison `UNCONTROLLED`.

An entry can also declare `instrument = true`. An instrument variant holds an instrument skill. The skill makes a behavior occur, so that a person can check a measurement. The report gives no effect size for an instrument variant. The report never shows an instrument variant as an artifact under test.

### Comparability rules for a derived variant

- The bundle is identical to the base bundle, part for part, except for the part that `differs_in` names.
- Where the changed part is a file, the content is identical byte for byte outside the declared change.
- The token counts of the two bundles differ by 5% or less. Without this rule, the length of the prompt confounds the measured effect. The study from ETH found that long context files can decrease the success rate.
- The file name, the front matter, and the description of each skill are the same in both bundles. Therefore both variants have the same chance to activate.
- Skill directory names are unique inside one bundle. Harbor removes a duplicate name and keeps the last copy, and a duplicate therefore changes the result with no error.
- A person writes the changed part. Code examples compile, and they pass the linter of their language.

### Where hook scripts live

A hook command is a shell string. A short hook needs no file. A long hook needs a script, and that script must reach the container on every trial.

Put the script inside a skill directory. Harbor uploads each skill directory to `/harbor/skills/<name>/` for each trial. The directory stays there for the full trial. This route holds the script independent of the task image, which is the property Assay needs.

The execute bit of a file stays only if the file on the host has it. Harbor does not add it, and the skill digest does not include file modes. Therefore the hook command starts the script through the shell: `bash /harbor/skills/<name>/hook.sh`.

Put the settings object inline in the job configuration, and not as a file path. For a file path, the lock records the path only and not the content. Inline settings put the exact hook declaration into the `config.json` and the `lock.json` of each trial.

### Limits of Harbor for this purpose

| Need | State |
|---|---|
| Two or more skills in one trial | Supported. `--skill` repeats. Harbor records the name, the source, and the digest of each skill in the job lock, and the analyzer reads the lock to confirm the correct bundle ran. |
| Hooks | Harbor has no hook flag. Harbor uploads the settings object without inspection, and Claude Code reads the `hooks` key from it. Phase 0 tests that a hook fires. |
| A plugin as one unit | Not supported. Split the plugin into skills, an MCP file, and a settings object. |
| Slash commands from a plugin | No mechanism exists. An experiment that needs commands needs a different runner. |
| The ACP agent path (`--agent acp:<id>`) | This path does not copy skills. Use a native adapter for every Assay trial. |
| A terminal recording | Only the Terminus-2 agent writes `recording.cast`. The Claude Code adapter does not write one. |
| The version of Claude Code | Harbor installs the latest Claude Code in each trial. Set `--ak version=<x.y.z>` to pin it. All model tiers use the same version. |
| Skills or settings from the task | The adapter also copies any `~/.claude/skills` in the task image. Claude Code also reads a `.claude/settings.json` in the seed repository. A task image and a seed repository must hold neither. |
| Per-test results | `ctrf.json` is a convention of the task and not a product of Harbor. The task writes it from the test runner. |
| More than one verifier pass | Harbor runs `tests/test.sh` one time. The script itself runs the tests as many times as the task needs, and it writes one file for each pass. |

### Adapter choice and trajectory fidelity

Harbor records what the adapter converts, and the adapters do not convert the same detail. This table gives the detail that Assay needs:

| Adapter | ATIF | Verbatim tool arguments | Exit code in the observation |
|---|---|---|---|
| `claude-code` | yes | Yes. A write holds the path and the full content. | Pass or fail only. For a failed call, `extra.tool_result_is_error` on the observation result is true, and the content starts with `Exit code N`. A call that passes has no exit code field. |
| `opencode` | yes | Yes. A write holds the path and the full content. | No. The result is one flat string. |
| `mini-swe-agent` | yes | No. The only tool is `bash`, and file content arrives inside a shell command. | No. |
| `terminus-2` | yes | No. The agent drives a terminal, and file content arrives inside a shell command. | No. |
| `aider` | no | — | — |

Two rules come out of the table:

- Assay uses an adapter that gives verbatim tool arguments. A terminal-only adapter breaks the process tier and offline replay together.
- Red-to-green method 1 needs a pass or fail signal for each test run. Under `opencode`, use offline replay instead.

### Model tiers, and the local tier

Assay runs three model tiers. Two tiers are hosted models. One tier is an open-weight model on the local machine or on the local network.

The local tier gives three things. It removes the money cost from one model tier, and therefore it buys repetitions. It extends the central question below the cheapest hosted model: is a model on your own hardware sufficient for this work? It also runs against a private codebase with no data that leaves the network.

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
| Fallback model | Qwen3-Coder-30B-A3B, if the phase 0 time breaks the Risk 10 limit. It is a different local setup with its own L6 record. A Qwen model needs a changed chat template, because its default template rejects a system message in the middle of the conversation. |

*Source: Harbor v0.24.0, research in [issue #2](https://github.com/LeeSanderson/Assay/issues/2) and [issue #3](https://github.com/LeeSanderson/Assay/issues/3), and the decision in [issue #4](https://github.com/LeeSanderson/Assay/issues/4).*

#### Requirements

| # | Requirement |
|---|---|
| L1 | One adapter serves every model tier. Two adapters confound the model with the harness, and the comparison between tiers is then void. |
| L2 | The adapter records verbatim tool arguments, as the fidelity table above requires. The preferred adapter is `claude-code` against a server that speaks the Anthropic format, because it keeps the trajectory of the hosted tiers unchanged. The tested alternative is `opencode` for every model tier, and it loses the pass or fail signal. Phase 0 selects between the two. |
| L3 | The local tier declares a `concurrency_group` with `n_concurrent = 1`. One local server answers one request at a time. The hosted tiers keep their parallel trials. |
| L4 | The local tier runs with a higher `timeout_multiplier`. This key applies to the full job and not to one agent, so the local tier runs as a separate job. The report gives the timeout rate for each model tier. A trial that reaches the timeout is not a failure of capability. |
| L5 | The report gives seconds for each solved task pack beside the figure in USD. Harbor takes the cost from the `total_cost_usd` value of Claude Code. For a local model this value can be wrong, so the analyzer sets the money cost of the local tier to zero. The token counts stay correct. |
| L6 | The results record the model file, the quantization, the chat template, the inference server with its version, the full server command line with its environment flags, the thinking setting, the hardware, and the operating system. The agent configuration rejects unknown keys, so this record goes in a file beside the job configuration. A model name alone is not a stable identifier. A different quantization, build option, or thinking setting is a different model. |
| L7 | The container reaches the server at its network address, and not through `host.docker.internal`. In WSL2, `host.docker.internal:host-gateway` goes to the WSL2 virtual machine and not to the Windows host. Thus the reference setup adds no `extra_hosts` overlay and changes no networking on the `main` service. This also keeps the egress sidecar correct. If the address cannot be reached, use WSL2 mirrored networking and `127.0.0.1`. |
| L8 | The local tier is one model tier of the same matrix. It uses the same task packs, the same variants, and the same verifiers as the hosted tiers. |
| L9 | Every model tier sets `DISABLE_NON_ESSENTIAL_MODEL_CALLS=1` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` under `env:`. Background requests (titles and summaries) use the one server slot and remove the prefix cache. Every model tier sets them, so the harness stays the same (L1). |
| L10 | One setting, `ASSAY_LOCAL_BASE_URL`, holds the server address. No other file contains the address. To use a different local setup, change this one setting. |

```yaml
# jobs/v1.yaml — the local tier
timeout_multiplier: 3.0             # job level; no agent has this key
agents:
  - name: claude-code
    model_name: laguna-s-2.1        # the server receives this exact name
    concurrency_group: local-llm
    n_concurrent: 1
    env:
      ANTHROPIC_BASE_URL: <value of ASSAY_LOCAL_BASE_URL>   # one setting only (L10)
      ANTHROPIC_API_KEY: dummy
      DISABLE_NON_ESSENTIAL_MODEL_CALLS: "1"                # every model tier (L9)
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"
    kwargs:
      version: "<pinned Claude Code version>"
```

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

A later experiment uses the same machinery for hooks, for MCP servers, and for combinations. Such an experiment declares variants that differ in another part of the bundle.

### The phase 0 instrument

Phase 0 uses one instrument variant, `instrument-tdd`, for both languages. It holds a frozen copy of the `tdd` skill from `mattpocock/skills`, with changes for trials that have no user. The skill directory is `variants/instrument-tdd/tdd/`, and it holds `SKILL.md`, `tests.md`, and `mocking.md` only.

```toml
[instrument-tdd]
label       = "Instrument: TDD skill adapted for trials with no user"
skills      = ["variants/instrument-tdd/tdd"]
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

The record of the source and the changes stays in the manifest. A file in the skill directory goes into the container, and the agent can read it.

The examples stay in TypeScript for the Go trials too. Phase 0 checks `trajectory.py`, and it does not measure the value of the skill in each language.

The new description must activate the skill on a prompt that does not name TDD. The smoke trial tests this: its trajectory must hold a `Skill` call for `tdd` before the first file write. If it does not, add an instruction file that names the skill (`--extra-instruction-path`), and run the smoke trial again. Each instrument trial records whether the skill loaded.

### Paired design

Every condition runs against the same task pack, the same seed repository, and the same prompt. The analyzer computes each effect size inside one task pack. This method gives the largest available decrease in variance, and it costs nothing.

### Activation gate

In some trials the agent never activates the artifact. The analyzer excludes these trials from the effect calculation. The report gives the activation rate as a separate metric.

### Metric tiers

| Tier | Metrics | Source |
|---|---|---|
| Outcome | The withheld reference tests pass. `pass^k` reliability across repetitions. | `reward.json` |
| Process | Test-first order. Red-to-green order. Test count. Assertion density. Mock density. | `trajectory.json` (ATIF), through the analyzer |
| Cost | Input tokens, output tokens, and reasoning tokens. Cost in USD. Duration. Turn count. **Cost for each solved task pack.** | `result.json` and the analyzer |
| Quality | Mutation score of the tests that the agent wrote. Coverage delta. Lint and type check are clean. Diff size. | `reward.json` |

### How Assay measures the order of actions

Harbor writes `agent/trajectory.json` in ATIF, the Agent Trajectory Interchange Format. ATIF is one schema that 35 Harbor agents share. Each step holds a sequential `step_id`, an ISO-8601 `timestamp`, a list of `tool_calls`, and an `observation`.

Each tool call holds `function_name` and `arguments`. For Claude Code the arguments are complete and verbatim. A `Write` call holds the file path and the full content. An `Edit` call holds the old string and the new string. A `Bash` call holds the command, and the observation holds the output and a pass or fail flag. A `Skill` call appears as a tool call with that name. The agent can also read a skill with a `Read` call on its `SKILL.md`, and the activation gate counts both.

Therefore the analyzer reads the order of file writes directly from the trajectory. This metric needs no extra instrumentation.

ATIF also makes the analyzer agent-independent. A later experiment that adds a harness axis reads the same schema.

Two limits apply:

- One step holds every tool call of one agent turn. Inside a step, the order is the order of the array. The timestamp belongs to the turn and not to each call.
- A `Bash` call can write a file, and that write is not a `Write` call. The analyzer counts file-writing `Bash` calls and marks any trial that contains one.

#### Test-first order

Test-first order looks at the order of writes only. It does not look at the test state. The red-to-green order gives the test state.

Use these rules:

1. A write is a `Write`, `Edit`, or `MultiEdit` call. The content of the write has no effect. A stub is a write. The content of the seed repository is not a write.
2. Only a path inside the seed repository counts. A path outside it, such as `/tmp/try.ts`, is neutral.
3. The language of the task pack sets the class of each path:

   | Language | Test file | Implementation file | Neutral |
   |---|---|---|---|
   | TypeScript | `*.test.ts`, `*.spec.ts` | Each other `*.ts` file, but not `*.config.*` | All other files |
   | Go | `*_test.go` | Each other `*.go` file | All other files |

4. Find the first write to a test file and the first write to an implementation file. Only these two writes decide the verdict. Writes after them have no effect.
5. The deciding point is the step of the earlier of the two writes. If one of the two writes does not occur, the deciding point is the last step of the trial.
6. Give the trial one verdict:

   | Verdict | Rule |
   |---|---|
   | `undetermined` | A file-writing `Bash` call occurs at the deciding point or before it. This rule comes before all other rules. |
   | `test-first` | The first test write is in an earlier step than the first implementation write. |
   | `implementation-first` | The first implementation write is in an earlier step than the first test write. |
   | `same-turn` | The two writes have the same `step_id`. In one turn, the agent cannot run the test before the implementation exists. |
   | `no-test` | The agent writes an implementation file and writes no test file. |
   | `no-implementation` | The agent writes no implementation file. |

**How a person checks `trajectory.py`.** Phase 0 compares `trajectory.py` with a person on the ten hosted trials:

1. A `jq` command, kept separate from `trajectory.py`, prints a neutral listing of each trial. Each line gives the `step_id`, the position in the array, the `function_name`, and the path or the `Bash` command. The listing gives no class and no verdict.
2. The person labels all ten trials from the listing before `trajectory.py` runs. The person can read `trajectory.json` when the listing is not sufficient. For each trial, the labeling sheet records the first test write and the first implementation write as anchors (`step_id`, position, and path), the file-writing `Bash` calls before the deciding point, the verdict, and a note.
3. `trajectory.py` then runs on the ten trials. The two agree on a trial when the verdict and the two anchors are the same.
4. For each difference, the person finds the cause. If the script is wrong, fix `trajectory.py` and run it again on all ten. If the person is wrong, correct the label and write the cause in the note. If a rule is not clear, correct the rule here, and then both sides apply it again.
5. "Agrees every time" means one full pass over the ten trials with no difference. The sheet keeps a record of each correction.

### How Assay measures red and green

A trajectory shows what the agent wrote. It does not show the state of the tests after each write. Harbor runs the verifier one time, after the agent stops.

A test run that does not compile is red.

Assay recovers the test state over time in three ways. The analyzer uses the cheapest way that works for each trial.

1. **The agent runs the tests.** A `Bash` call that runs the test command gives a pass or fail flag in the observation. A failed run sets `tool_result_is_error`, and its content starts with `Exit code N`. This way is free. It works only when the agent chooses to run the tests.
2. **Offline replay.** The trajectory holds the full content of every write. `replay.py` rebuilds the repository at each step and runs the tests on each rebuilt state. This way changes nothing inside the trial. It fails for a trial that writes files through `Bash`.
3. **A trace hook.** A `PostToolUse` hook appends one record to `/logs/artifacts/` after each write. Harbor collects that directory into the trial tree. This way gives the most complete record, and it also changes the agent environment.

**Rule for the trace hook.** The hook runs in every condition, and the control is one of them. An instrument that is present in some conditions only confounds the result. The hook returns no output to the agent, and therefore it does not steer the agent.

Phase 0 measures how often each way works. The result of phase 0 selects the method for the matrix.

### Reporting rules

- Every value carries a confidence interval. The report gives no bare point estimates.
- If the spread of a cell is larger than its effect, the report marks that cell `UNSTABLE`. It does not give a mean value for that cell.
- Verification is deterministic where this is possible. If a metric needs a model to grade it, the analyzer repeats the grade and reports the rate of agreement.

## 6. Architecture

```
assay/
  tasks/<language>/<exercism-slug>/
    instruction.md               prompt for the agent
    task.toml                    [verifier] [agent] [environment]
    environment/Dockerfile       pinned language toolchain
    solution/solve.sh            gold solution, to calibrate the verifier
    tests/test.sh                withheld reference tests, two passes, writes reward.json
  variants/
    variants.toml                bundle parts and relation for each variant
    tdd-examples-ts/SKILL.md     artifact as published, TypeScript examples
    tdd-examples-go/SKILL.md     identical prose, Go examples
    gate/settings.json           hook declaration for a combination variant
  jobs/
    v1.yaml                      Harbor job configuration for the full matrix
  analyze/
    trajectory.py                ATIF trajectory to process metrics
    replay.py                    rebuilds the repository at each step, runs the tests
    variants.py                  reads variants.toml, builds Harbor flags, tests comparability
    pairs.py                     paired deltas and bootstrap CIs
    report.py                    metric table, UNSTABLE marks, cost for each solve
  results/<job-id>/              output tree of Harbor, committed without change
```

A skill directory holds a `SKILL.md` file, because the `--skill` flag of Harbor takes a directory. The control names no parts. Harbor runs the control with none of the variant flags.

The task packs are native to Harbor. Therefore any user of Harbor can run the corpus without an installation of Assay. This property gives the replication path, and it also prevents the growth of an adapter layer.

The repository commits the raw trajectories and not only the totals. Results in this field come from a second analysis with a metric that was not obvious at first. A second run costs money. A second analysis is free.

The analyzer is the only large piece of code. Its budget is 400 to 600 lines of Python. If the analyzer becomes larger than this budget, then a function of Harbor is inside Assay.

## 7. Build plan

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| 0 | Measurement spike | Over ten manual trials on the hosted model tiers: `trajectory.py` finds the test-first order, and a person who reads the same trajectory agrees every time (see "Test-first order" for the rules and the check). The report gives the share of trials that write a file through `Bash`. Every trial of this phase carries the trace hook. The hook writes a marker file, and the marker reaches the trial tree. The hosted trials cost £15 or less, and this includes each trial that runs again. One more trial runs the preferred adapter against a local model server, and its trajectory holds verbatim tool arguments. That trial also records its time, the prefix cache hits for each turn, the count of background requests, and the tool calls after a system message in the middle of the conversation. **This phase blocks all other phases.** |
| 1 | Corpus and conditions | Six task packs in two languages. Two variant directories and a manifest. The analyzer passes every comparability test for the derived variant. `tests/test.sh` returns the full reward for `solution/solve.sh`. It returns zero for an empty repository. |
| 2 | Matrix run | Harbor completes 360 trials inside the budget. The repository holds the results. |
| 3 | Analysis | `report.md` gives effect sizes with confidence intervals for four tiers. It also gives activation rates, cost for each solved task pack, and `UNSTABLE` marks. |
| 4 | Write-up | A published result. The corpus is published with it. |

Phase 0 comes first because it tests the assumption under all later phases.

## 8. Risks to validate

| # | Risk | Validation | Fallback |
|---|---|---|---|
| 1 | Red-to-green state is not recoverable. Write order is visible in ATIF, but the test state between writes is not. | Phase 0 measures all three recovery methods on ten trials | Use the trace hook in every condition. If the hook also fails, make the mutation score the primary process metric. |
| 2 | Agents write code through `Bash` instead of `Write`, and offline replay fails | Phase 0 reports the share of trials with a file-writing `Bash` call | Use the trace hook for the whole matrix. |
| 3 | Frontier models solve Exercism task packs too easily | Measure the `none` condition in phase 1 | The withheld tests already make the task harder. Write one or two packs from unpublished work as a control for contamination. |
| 4 | The agent never activates the artifact, and the result is a silent false null | The activation rate is a reported metric from phase 2 | Gate the effect calculation on activation. Report the rate as a result. |
| 5 | The matched token count does not remove the length confound | Compare the derived variant against a placebo variant of the same length | Add a variant that holds neutral filler text. |
| 6 | The effects are smaller than the noise between trials at five repetitions | Measure the power of the phase 2 output | Add repetitions to the cells that show an effect, and not to the whole matrix. |
| 7 | The language toolchains drift, and the results do not reproduce | Pinned images, no network access, and a dependency cache inside each image | Publish the images with the results. |
| 8 | The hook route depends on behavior that the Harbor documents do not describe. A new version of Harbor can inspect or reject the settings object. | Phase 0 runs one trial with a hook that writes a marker file. The verifier tests for the marker. | Pin the version of Harbor. Record the version with the results. If Harbor closes this route, write the settings file with a 15-line subclass of the agent. |
| 9 | The Anthropic-format route for the local tier is not tested. | Phase 0 runs one local trial against `/v1/messages` of the local server and inspects the trajectory | Use `opencode` for every model tier, including the hosted tiers, and recover red-to-green by offline replay only. |
| 10 | The local tier is slow, and wall clock replaces money as the binding constraint. | Time one local trial in phase 0, and multiply by 180 | Cut the local tier to one language, or reduce its repetitions and widen its confidence intervals. |
| 11 | A combination study multiplies the variant axis. Four bundle parts with two states each give 16 variants. | Count the trials before each job, and compare the count against the budget | Use a fractional design. Test each part against the control first, and test only the pairs that show an effect. |

**Kill criterion.** If phase 3 shows every effect inside the noise band on all four tiers, then the instrumentation is wrong. Correct the metrics. Do not add cells to the matrix.

## 9. Success criteria

1. A measured answer, with confidence intervals, to this question: does the value of the artifact change with the language and with the model tier?
2. A measured answer to this question: which task packs does a local open-weight model solve as well as a hosted model?
3. A cost for each solved task pack, in money and in seconds, reported for each model tier and each kind of task.
4. A published corpus that another person can run under Harbor without an installation of Assay.
5. No execution code, sandbox code, or scheduler code in the repository.

## 10. Open items

| # | Item | Needed by |
|---|---|---|
| 1 | The second language. Go is further from the assumptions of the artifact. Python is closer to real use. The specification gives Go today. | Phase 1 |
| 2 | Publication of the task packs. Publication invites replication. It also invites contamination of future training sets. | Phase 4 |
| 3 | Closed. The reference setup gives the open-weight model and the hardware ([issue #4](https://github.com/LeeSanderson/Assay/issues/4)). | Phase 0 |
