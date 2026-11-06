"""The summary contract, its plan and its run (PRD v3 section 10; issue #66).

A summary module exposes one value:

    SUMMARY = Summary(summarize, check_options=None)

`summarize(view, options, out)` gets the ExperimentView, the `options` table
of `[summary]` in experiment.toml, and the empty folder
`analysis/<experiment>/summary/`, where it writes its files. It is the only
step that crosses trials, and it runs again on every invocation that
completes. `check_options(options, plan)` gets the options and a PlanView
(each agent of each job file, and the varied factors with their levels), so
it can check, for example, that a `baseline` matches exactly one agent (PRD
section 11, plan check 6). It raises ValueError when the options are not
valid; the plan then refuses the experiment at no cost.

`experiment.toml` names the summary with `[summary] use = "./<file>.py"`, a
path in the experiment's folder. There is no built-in summary yet
(`paired-delta` is out of scope).
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from assay.experiment_files import ExperimentLog, LocalModuleError, load_local_module

if TYPE_CHECKING:
    from assay.experiment import Cell, Plan

Json = Any
SUMMARY_FOLDER = "summary"
FACTORS = ("harness", "model_tier", "condition")  # PRD section 5; language is not a factor


@dataclass(frozen=True)
class TrialView:
    """One kept trial: its cell, task pack and record, and the value and the
    error of each evaluation (None when it has none)."""

    job: str
    trial: str
    cell: Cell | None  # None when no agent of the job file matches the trial
    task_pack: Path  # tasks/<language>/<slug>
    record: Any  # analyze.trial.Trial
    values: Mapping[str, Json]
    errors: Mapping[str, str | None]

    @property
    def pack_language(self) -> str:
        """The language of the task pack, from its path."""
        return self.task_pack.parts[-2]

    @property
    def pack_slug(self) -> str:
        """The slug of the task pack (the ladder's rung), from its path."""
        return self.task_pack.parts[-1]


@dataclass(frozen=True)
class ExperimentView:
    experiment: str
    factors: Mapping[str, tuple[str, ...]]  # the varied factors only, with their levels
    trials: Sequence[TrialView]  # the kept trials of every job
    expected: Mapping[Cell, int]  # the expected trials of each cell, from the job files
    log: Sequence[Mapping[str, Json]]  # every event of the experiment log, in order


@dataclass(frozen=True)
class PlannedAgent:
    """One agent of one job file, by its factor levels."""

    job: str
    harness: str
    model_tier: str
    condition: str


@dataclass(frozen=True)
class PlanView:
    """What `check_options` gets of the plan: each agent of each job file, and
    the varied factors with their levels."""

    agents: Sequence[PlannedAgent]
    factors: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Summary:
    summarize: Callable[[ExperimentView, Mapping[str, Json], Path], None]
    check_options: Callable[[Mapping[str, Json], PlanView], None] | None = None


class SummaryPlanError(Exception):
    """The summary cannot be planned; the experiment stops at no cost."""


@dataclass(frozen=True)
class PlannedSummary:
    listed: str  # as experiment.toml names it
    summary: Summary
    options: Mapping[str, Json]


def plan_view(plan: Plan) -> PlanView:
    agents = [PlannedAgent(job.name, a.harness, a.model_tier, a.condition)
              for job in plan.jobs for a in job.agents]
    return PlanView(agents, varied_factors(plan.expected))


def plan_summary(experiment_dir: Path, listed: str, options: Any, plan: PlanView
                 ) -> PlannedSummary:
    """Loads the summary and checks its options against the plan."""
    if not listed.startswith("./"):
        raise SummaryPlanError(f"summary {listed} is not a built-in summary (there is none "
                               f"yet) and not a ./path")
    try:
        module = load_local_module(experiment_dir, listed, "summary")
    except LocalModuleError as e:
        raise SummaryPlanError(str(e)) from e
    summary = getattr(module, "SUMMARY", None)
    if not isinstance(summary, Summary):
        raise SummaryPlanError(f"summary {listed} has no SUMMARY = Summary(...)")
    if not isinstance(options, Mapping):
        raise SummaryPlanError("summary.options must be a table")
    if summary.check_options is not None:
        try:
            summary.check_options(dict(options), plan)
        except ValueError as e:
            raise SummaryPlanError(f"summary {listed}: invalid options: {e}") from e
    return PlannedSummary(listed, summary, dict(options))


def varied_factors(expected: Mapping[Cell, int]) -> dict[str, tuple[str, ...]]:
    """Each factor that the jobs hold more than one level of, with its levels."""
    factors = {}
    for name in FACTORS:
        levels = sorted({getattr(cell, name) for cell in expected})
        if len(levels) > 1:
            factors[name] = tuple(levels)
    return factors


def experiment_view(plan: Plan, log: Sequence[Mapping[str, Json]]) -> ExperimentView:
    """The view of the experiment: its kept trials with the result of each
    evaluation from `analysis/<experiment>/<job>/<trial>/<evaluation>/`."""
    from analyze.trial import read_json, read_trial
    from assay.evaluations import RESULT_FILE, kept_trials, task_pack, trial_cell

    jobs = {job.name: job for job in plan.jobs}
    trials = []
    for kept in kept_trials(plan):
        record = read_trial(kept.path)
        values, errors = {}, {}
        for p in plan.planned_evaluations:
            result = read_json(plan.paths.trial_analysis(kept.id) / p.name / RESULT_FILE) or {}
            values[p.name] = result.get("value")
            errors[p.name] = result.get("error")
        cell = trial_cell(plan, jobs[kept.id.job], kept.path, record)
        trials.append(TrialView(kept.id.job, kept.id.trial, cell, task_pack(record), record,
                                values, errors))
    expected = plan.expected
    return ExperimentView(plan.experiment, varied_factors(expected), trials, dict(expected),
                          list(log))


def run_summary(plan: Plan, planned: PlannedSummary, log: ExperimentLog) -> list[Path]:
    """Empties the summary folder, runs the summary, and logs `summary-written`
    with the files it wrote. An exception from the summary goes to the caller."""
    out = plan.paths.analysis / SUMMARY_FOLDER
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    view = experiment_view(plan, log.events())
    planned.summary.summarize(view, dict(planned.options), out)
    files = sorted(f for f in out.rglob("*") if f.is_file())
    log.write("summary-written", files=[f.as_posix() for f in files])
    for f in files:
        print(f"summary: wrote {f.as_posix()}")
    return files
