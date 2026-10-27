# Assay

Assay measures how context artifacts, model tiers and harnesses change a coding agent's work and cost, as controlled experiments.

## Language

### What is measured

**Artifact**:
A skill, rules file, instruction file, or hook for a coding agent, whose value Assay measures.
_Avoid_: Context file, prompt pack

**Artifact under test**:
The specific artifact an experiment measures, held as a frozen snapshot inside a variant and never as a reference to a live copy.
_Avoid_: The skill, the installed skill

**Instrument skill**:
A skill used to make agent behavior happen so a measurement can be checked, with no claim made about its value.
_Avoid_: Stand-in artifact, test skill

**Dev skill**:
A skill in the repository's own agent configuration that helps build Assay, and that is never part of an experiment.
_Avoid_: Installed skill

### Experiment design

**Experiment**:
One question Assay answers, defined by the factors it varies, the baseline it compares against, its task packs, its repetitions and its evaluations.
_Avoid_: Study, benchmark, suite

**Factor**:
One axis an experiment varies (harness, model tier or condition), each with a declared baseline level that every comparison is made against.
_Avoid_: Arm, dimension

**Harness**:
The agent program that drives the model in a trial, with its own system prompt and tools, such as Claude Code or opencode; its prompts and tools are part of what a harness comparison measures.
_Avoid_: Adapter, runner, agent

**Condition**:
What the agent receives in addition to the task prompt in one trial: either the control or one variant.

**Control**:
The condition in which the agent receives the task prompt and nothing else; the measurement instruments still run, because they run in every condition.
_Avoid_: None condition, baseline

**Measurement instrument**:
Something that records what happens in a trial, runs identically in every condition, stays outside every variant, and never enters the agent's context.
_Avoid_: Probe, monitor, tracer

**Variant**:
A named, complete bundle of agent configuration (skills, settings, MCP servers, extra instructions) that is one non-control condition.
_Avoid_: Treatment, arm

**Task pack**:
One self-contained task with its prompt, seed repository, pinned toolchain image, gold solution, and withheld reference tests.
_Avoid_: Task, exercise, benchmark item

**Seed repository**:
The files an agent starts from in a trial: the task's public interface as a stub and the toolchain configuration, with no tests.
_Avoid_: Starter code, scaffold, template

**Trial**:
One run of one agent, under one condition, on one task pack, at one model tier.
_Avoid_: Run, episode

**Model tier**:
One model on the model axis of the matrix, hosted or local.
_Avoid_: Arm

**Cell**:
One combination of harness, model tier, condition, and language, holding the trials across task packs and repetitions.
_Avoid_: Arm, slot

**Local setup**:
The hardware, inference server, model file, and settings that together serve a local model tier, recorded in full beside its results.
_Avoid_: Local stack, local config

**Reference setup**:
The one local setup that Assay documents as guidance; any other local setup may differ from it, provided it is recorded in the same way.
_Avoid_: Required setup, default setup

### Telemetry and evaluation

**Trial record**:
The fixed, harness-neutral telemetry of one trial: every tool call in order, tokens, cost, time, and the repository's history through the trial; every supported harness produces it in full, and states how finely it captured that history.
_Avoid_: Logs, trace, results

**Evaluation**:
An experiment-specific step that turns trial records and the final repository into higher-level metrics, such as test-first order or new security findings.
_Avoid_: Analyzer, grader, scorer

**Summary**:
The optional last step of an experiment, which combines the evaluation results of all its trials into comparisons against the baseline.
_Avoid_: Report generator, aggregation

**Infrastructure failure**:
A trial whose outcome does not reflect the agent working on the task under its declared conditions, such as one cut short by a model service outage, a crashed container or a broken trial record; it is discarded and run again in its place, unlike a trial in which the agent ran out of time or simply failed the task.
_Avoid_: Failed trial, error

**Halt**:
An infrastructure failure that running the trial again would only repeat, such as an exhausted quota or a pinned version that drifted; it stops the experiment until a person fixes the cause.
_Avoid_: Abort, fatal error

**Experiment log**:
The running record of everything that happened to one experiment across all its invocations, including each discarded trial and what it cost.
_Avoid_: Discard list, run history

### Process metrics

**File write**:
A change that a tool call makes to the content of a file in the seed repository, whichever tool made it; a call that leaves the content unchanged makes no file write, and deleting a file is not one.
_Avoid_: Write call

**Test-first order**:
Whether the agent wrote a test file before it wrote an implementation file in one trial, judged from the order of file writes alone and not from whether the test failed.
_Avoid_: Failing test first, test before implementation

**Test state**:
The result of the agent's own tests on one state of the repository: they pass, they fail, they do not compile, or there are none; a state with no tests is not green.
_Avoid_: Test result, red/green status

**Run result**:
What one of the agent's own test runs showed: red, green or unknown, read from the test framework's summary in the run's output or, for an unpiped run with no summary, from its exit code; it belongs to the run, not to a state of the repository.
_Avoid_: Exit code, test outcome

**Seen state**:
A test state the agent saw: the agent ran its tests, and what the run showed agrees with the test state of the repository at that moment; it is either seen red or seen green.
_Avoid_: Observation, observed state

**Red-to-green order**:
Whether the first test state the agent saw in one trial was red and a later one was green, so that the tests were seen failing before they were seen passing.
_Avoid_: Red-green, failing test first

**TDD loop**:
How often one trial repeats the red, green, refactor cycle, given as counts of cycles, of tests never seen red, and of refactor steps, all judged from seen states.
_Avoid_: TDD cycle score, red-green-refactor rate
