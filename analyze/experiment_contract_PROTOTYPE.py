"""PROTOTYPE (wayfinder #49): throwaway, on branch prototype/experiment-contracts.

The evaluation contract, the summary contract, where resume state lives, and the
experiment log, as stubs. The bottom half ports today's chain (replay ->
agent-runs -> trajectory) onto the contract, on paper: the bodies are not real.

On disk, for experiment E:

    experiments/E/experiment.toml           committed: factors, jobs, evaluations, summary
    experiments/E/summary.py, evaluations/  committed: experiment-local code
    results/E/<job>/<trial>/                Harbor's tree (assay passes --jobs-dir results/E)
    analysis/E/experiment-log.jsonl         the experiment log, appended across invocations
    analysis/E/<job>/<trial>/trial-check.json          the trial-record check (today's trace check)
    analysis/E/<job>/<trial>/<evaluation>/result.json  envelope + value (resume state)
    analysis/E/<job>/<trial>/<evaluation>/...          the evaluation's own files (replay-logs/)
    analysis/E/summary/                     whatever the summary writes; rewritten every time

`--from-scratch` deletes results/E and analysis/E, the log too.
Discarding a trial (an infrastructure failure) deletes results/E/<job>/<trial> and
analysis/E/<job>/<trial>, after its experiment-log event is written.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

# What #50 decides: a normalized file, or a view over Harbor's tree. The contract
# only needs it to be one object per trial; today that is analyze.trial.Trial.
TrialRecord = Any
Json = Any  # a value json.dumps accepts


# --------------------------------------------------------------------------- #
# The cell and the trial an evaluation sees
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Cell:
    harness: str        # from the trial record
    model_tier: str     # from the trial record
    condition: str      # from experiment.toml [[jobs]] condition
    language: str       # from the task pack path


Network = Literal["none", "internal", "online"]


class Containers(Protocol):
    """The one way an evaluation starts containers. Network is "none" by default;
    "online" is refused unless the evaluation is declared online."""

    def pack_image(self, task_pack: Path) -> str:
        """The task pack's image, built from its Dockerfile and cached by pack digest."""
        ...

    def run(self, image: str, command: Sequence[str], *, mounts: Mapping[Path, str] = {},
            network: Network = "none", timeout: float | None = None) -> RunResult:
        ...

    def service(self, image: str, *, ports: Sequence[int] = (),
                network: Network = "internal") -> AbstractContextManager[str]:
        """A long-running container (a local Sonar server) for the length of a
        `with` block; yields its address on the internal network."""
        ...


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None    # None on a timeout
    stdout: str
    stderr: str


@dataclass(frozen=True)
class TrialInput:
    """Everything an evaluation gets for one trial. Read-only except `out`."""

    job: str
    trial: str
    cell: Cell
    task_pack: Path                  # tasks/<language>/<slug>
    record: TrialRecord              # passed the trial-record check
    deps: Mapping[str, Json]         # the result value of each evaluation in depends_on
    options: Mapping[str, Json]      # [[evaluations]] options from experiment.toml
    out: Path                        # empty folder for the evaluation's own files
    containers: Containers
    checkout: Callable[[str], Path]  # a commit of the repository history -> a temp tree

    def seed(self) -> Path: ...      # checkout of the seed commit
    def final(self) -> Path: ...     # checkout of the last snapshot


# --------------------------------------------------------------------------- #
# The evaluation contract
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Evaluation:
    """A module exposes one of these as EVALUATION. Built-ins are found by name in
    BUILT_INS; an experiment-local one by its path from experiment.toml."""

    name: str
    evaluate: Callable[[TrialInput], Json]
    """Metrics for one trial. Seed and final are evaluated in this one call, so
    the two always see the same data. Raise to record an error result."""

    depends_on: tuple[str, ...] = ()
    """Hard dependencies. A trial whose dependency has an error result gets an
    error result for this evaluation too, without a call."""

    pins: Callable[[TrialInput], Mapping[str, str]] = lambda _: {}
    """Pinned external inputs that are not files in this repository: tool image
    digests, a rule set's hash, a vulnerability-DB snapshot date. They count in
    the input digest, so a new pin reruns the evaluation."""

    online: bool = False
    """Reads a live service. Its value must hold `data_version` (a DB timestamp,
    a response hash). It runs for every trial of the experiment together or not
    at all: reused only when every trial has a reusable result; otherwise every
    trial runs again, never a subset."""


@dataclass(frozen=True)
class ResultEnvelope:
    """analysis/E/<job>/<trial>/<evaluation>/result.json. Written by Assay, not by
    the evaluation."""

    evaluation: str
    digest: str                  # sha256 over code + inputs; the resume key
    code: str                    # digest of the evaluation module and every repository
                                 # module it imports, found by walking its imports
    inputs: Mapping[str, str]    # each part's digest: record, task_pack, options,
                                 # deps.<name> (of the dependency's value), pins.<key>
    started_at: str
    duration_sec: float
    value: Json | None           # evaluate()'s return; None with an error
    error: str | None = None     # an error result is never reused


# Resume, per trial x evaluation, in run order:
#   1. compute the input digests (a dependency's part is the digest of its *value*,
#      so a dependency that reruns and gives the same value reruns nothing after it);
#   2. reuse result.json when its digest equals the new one and it holds no error;
#   3. otherwise empty the folder and call evaluate().
# An online evaluation does 1-2 for every trial first, and 3 for all of them or none.


# --------------------------------------------------------------------------- #
# The summary contract
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Factor:
    name: str
    baseline: str
    levels: tuple[str, ...]


@dataclass(frozen=True)
class TrialView:
    job: str
    trial: str
    cell: Cell
    task_pack: str
    record: TrialRecord
    results: Mapping[str, Json]          # evaluation name -> value
    errors: Mapping[str, str]            # evaluation name -> error


@dataclass(frozen=True)
class ExperimentView:
    name: str
    factors: Mapping[str, Factor]        # varied factors only
    trials: Sequence[TrialView]          # kept trials that passed the record check
    expected: Mapping[Cell, int]         # trials per cell from the job configs
    log: Sequence[Mapping[str, Json]]    # every experiment-log event, in order

    def cell_counts(self) -> Mapping[Cell, int]: ...   # short cell: count < expected


@dataclass(frozen=True)
class Summary:
    """A module exposes one of these as SUMMARY."""

    summarize: Callable[[ExperimentView, Mapping[str, Json], Path], None]
    """(experiment, options, out folder). Writes its files to analysis/E/summary/.
    The only place that crosses trials: paired deltas, CIs, UNSTABLE marks, spend."""


# --------------------------------------------------------------------------- #
# The experiment log: analysis/E/experiment-log.jsonl
# --------------------------------------------------------------------------- #
# One JSON object per line. Every line: "at" (ISO time), "invocation" (an id per
# `assay experiment` call), "event". The other fields per event:

LOG_EVENTS: dict[str, dict[str, str]] = {
    "invocation-started": {"argv": "list", "assay_commit": "git HEAD, '-dirty' if so",
                           "harbor_version": "str"},
    "job-started":        {"job": "job_name", "file": "jobs/....yaml", "condition": "str"},
    "job-finished":       {"job": "str", "exit_code": "int", "trials": "int",
                           "duration_sec": "float"},
    "trial-discarded":    {"job": "str", "trial": "str", "cell": "Cell as an object",
                           "task_pack": "str",
                           "cause": "{exception: type} or {failed_checks: [...]}",
                           "input_tokens": "int|null", "cache_tokens": "int|null",
                           "output_tokens": "int|null", "cost_usd": "float|null",
                           "duration_sec": "float|null"},
    "halt":               {"job": "str", "trial": "str", "cause": "as trial-discarded",
                           "message": "what a person must fix"},
    "evaluation-finished": {"evaluation": "str", "ran": "int", "reused": "int",
                            "errors": "int", "duration_sec": "float"},
    "summary-written":    {"files": "list"},
    "invocation-finished": {"outcome": "complete | halted | interrupted | error"},
}


# =========================================================================== #
# On paper: today's chain on the contract (bodies are not real)
# =========================================================================== #

# --- replay (analyze/replay.py) ------------------------------------------------
# Fits. Its Runner protocol becomes Containers.pack_image + run(network="none").
# replay-logs/<seq>/ go to inp.out. replay-works.json and replay.jsonl merge into
# the value. The pack digest it makes today is now the task_pack input part.

def _replay(inp: TrialInput) -> Json:
    image = inp.containers.pack_image(inp.task_pack)
    snapshots = []  # for each commit in the record's history: checkout, run test.sh
    return {"works": True, "causes": [], "image": image, "snapshots": snapshots}


REPLAY = Evaluation(
    name="replay", evaluate=_replay,
    # The base image is pinned by digest in the pack's Dockerfile, which the
    # task_pack part already covers; Docker's own version is not pinned.
    pins=lambda inp: {},
)

# --- agent-runs (analyze/agent_runs.py) -----------------------------------------
# Fits. Reads deps["replay"]["snapshots"] instead of replay.jsonl; agent-runs.jsonl
# and cross-check.json merge into the value.

AGENT_RUNS = Evaluation(
    name="agent-runs", depends_on=("replay",),
    evaluate=lambda inp: {"runs": [], "cross_check": {"snapshots": 0, "covered_snapshots": 0,
                                                      "compared_runs": 0, "agreeing_runs": 0}},
)

# --- trajectory (analyze/trajectory.py) -----------------------------------------
# Fits, with one friction: today replay and agent-runs are optional (red-to-green
# and the TDD loop are null without them). The contract has hard dependencies
# only; the thin `assay trajectory` entry point keeps the optional form by
# passing no deps. Test-first order, bash, skill load, ad-hoc runs and web
# access need only the record.

TRAJECTORY = Evaluation(
    name="trajectory", depends_on=("replay", "agent-runs"),
    evaluate=lambda inp: {"test_first_order": {}, "red_to_green_order": {}, "tdd_loop": {},
                          "bash": {}, "skill_load": {}, "ad_hoc_runs": {}, "web_access": {}},
)

BUILT_INS: dict[str, Evaluation] = {e.name: e for e in (REPLAY, AGENT_RUNS, TRAJECTORY)}

# --- the trial-record check (analyze/trace_check.py) ------------------------------
# Not an Evaluation: it runs after each job, sorts each trial (pass / infrastructure
# failure / halt, per #48), and writes trial-check.json. Only passing trials get
# a TrialInput. `assay trace-check results/E/<job>` stays as its thin entry point.

# --- compare-labels (analyze/compare_labels.py) -----------------------------------
# Not an evaluation (it compares a person's sheet with trajectory's values). It
# reads analysis/E/<job>/<trial>/trajectory/result.json instead of
# analysis/trajectory.jsonl.
