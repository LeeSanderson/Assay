# Assay

Assay measures how much a context artifact changes a coding agent's work and cost, across model tiers and target languages, as a controlled experiment.

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

**Condition**:
What the agent receives in addition to the task prompt in one trial: either the control or one variant.

**Control**:
The condition in which the agent receives the task prompt and nothing else.
_Avoid_: None condition, baseline

**Variant**:
A named, complete bundle of agent configuration (skills, settings, MCP servers, extra instructions) that is one non-control condition.
_Avoid_: Treatment, arm

**Task pack**:
One self-contained task with its prompt, seed repository, pinned toolchain image, gold solution, and withheld reference tests.
_Avoid_: Task, exercise, benchmark item

**Trial**:
One run of one agent, under one condition, on one task pack, at one model tier.
_Avoid_: Run, episode

**Model tier**:
One model on the model axis of the matrix, hosted or local.
_Avoid_: Arm

**Cell**:
One combination of model tier, condition, and language, holding the trials across task packs and repetitions.
_Avoid_: Arm, slot

**Local setup**:
The hardware, inference server, model file, and settings that together serve a local model tier, recorded in full beside its results.
_Avoid_: Local stack, local config

**Reference setup**:
The one local setup that Assay documents as guidance; any other local setup may differ from it, provided it is recorded in the same way.
_Avoid_: Required setup, default setup

### Process metrics

**Test-first order**:
Whether the agent wrote a test file before it wrote an implementation file in one trial, judged from the order of writes alone and not from whether the test failed.
_Avoid_: Failing test first, test before implementation
