"""The evaluations of an experiment: the plan, the reuse of results, and the
run (PRD v3 sections 9 and 11; issue #64).

An evaluation is listed in `experiment.toml` by built-in name (BUILT_INS) or
by a `./path` in the experiment's folder. At plan time Assay refuses an
evaluation that is unknown, online, listed before its dependency, depends on
an evaluation that is not listed, or needs an optional part of the trial
record that the reader of some harness in the experiment does not give.

After the jobs, each evaluation runs in the listed order over every kept
trial of the experiment, whichever jobs ran in this invocation. Its result
goes to `analysis/<experiment>/<job>/<trial>/<evaluation>/result.json`, with
its `out/` folder beside it:

    {"evaluation", "digest", "code", "inputs", "started_at", "duration_sec", "value", "error"}

`code` is the digest of the import closure (the evaluation's module and each
repository module it imports); `inputs` the digests of the record, the task
pack, the options, each dependency's value (`deps.<name>`) and each pin
(`pins.<key>`). A result is reused when its digest is the same and it holds
no error. A dependency with an error gives an error result without a call.
"""

from __future__ import annotations

import ast
import importlib
import json
import shutil
import tempfile
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from analyze.trace_check import TRIAL_CHECK
from analyze.trial import GIVES, Trial, read_json, read_trial, record_digest
from assay.digests import files_digest, folder_digest, json_digest
from assay.evaluation import (
    OPTIONAL_PARTS, Containers, Evaluation, GuardedContainers, TrialInput,
)
from assay.experiment_files import (
    ExperimentLog, LocalModuleError, TrialId, load_local_module, timestamp,
)

if TYPE_CHECKING:
    from assay.experiment import JobPlan, Plan

CODE_ROOT = Path(__file__).resolve().parents[1]  # the repository's code
BUILT_INS = {"replay": "analyze.replay", "agent-runs": "analyze.agent_runs",
             "trajectory": "analyze.trajectory"}
# The optional record parts that the reader of each harness gives.
READER_GIVES = {"claude-code": GIVES}
RESULT_FILE = "result.json"
OUT_FOLDER = "out"


class EvaluationPlanError(Exception):
    """An evaluation cannot be planned; the experiment stops at no cost."""


@dataclass(frozen=True)
class PlannedEvaluation:
    listed: str  # as experiment.toml lists it: a built-in name or ./path
    evaluation: Evaluation
    options: Mapping[str, Any]
    code: str  # the digest of the import closure

    @property
    def name(self) -> str:
        return self.evaluation.name


@dataclass(frozen=True)
class KeptTrial:
    id: TrialId
    path: Path  # Harbor's trial folder


# --- The plan ---------------------------------------------------------------------


def plan_evaluations(experiment_dir: Path, listed: list[str], options: Mapping[str, Any],
                     harnesses: Iterable[str]) -> list[PlannedEvaluation]:
    """Loads each listed evaluation and runs the plan-time checks on them."""
    planned = []
    for item in listed:
        evaluation, module_file = load_evaluation(experiment_dir, item)
        planned.append(PlannedEvaluation(item, evaluation, dict(options.get(item, {})),
                                         code_digest(module_file)))
    names = [p.name for p in planned]
    if repeated := sorted({n for n in names if names.count(n) > 1}):
        raise EvaluationPlanError(f"two listed evaluations are named {repeated[0]}")
    harnesses = sorted(set(harnesses))
    for i, p in enumerate(planned):
        e = p.evaluation
        if e.online:
            raise EvaluationPlanError(
                f"evaluation {e.name} is online (online=True), which Assay does not run yet")
        if unknown := [n for n in e.needs if n not in OPTIONAL_PARTS]:
            raise EvaluationPlanError(
                f"evaluation {e.name} needs {unknown[0]}, which is not an optional part of the "
                f"trial record ({', '.join(OPTIONAL_PARTS)})")
        for harness in harnesses:
            gives = READER_GIVES.get(harness, frozenset())
            if missing := [n for n in e.needs if n not in gives]:
                raise EvaluationPlanError(
                    f"evaluation {e.name} needs {', '.join(missing)} of the trial record, which "
                    f"the reader of harness {harness} does not give")
        for dep in e.depends_on:
            if dep not in names:
                raise EvaluationPlanError(
                    f"evaluation {e.name} depends on {dep}, which experiment.toml does not list")
            if names.index(dep) > i:
                raise EvaluationPlanError(
                    f"evaluation {e.name} is listed before its dependency {dep}")
    return planned


def load_evaluation(experiment_dir: Path, listed: str) -> tuple[Evaluation, Path]:
    """The EVALUATION of a built-in name or of a ./path in the experiment's folder."""
    if listed.startswith("./"):
        try:
            module = load_local_module(experiment_dir, listed, "evaluation")
        except LocalModuleError as e:
            raise EvaluationPlanError(str(e)) from e
    elif listed in BUILT_INS:
        module = importlib.import_module(BUILT_INS[listed])
    else:
        raise EvaluationPlanError(
            f"evaluation {listed} is not a built-in evaluation "
            f"({', '.join(BUILT_INS)}) and not a ./path")
    evaluation = getattr(module, "EVALUATION", None)
    if not isinstance(evaluation, Evaluation):
        raise EvaluationPlanError(f"evaluation {listed} has no EVALUATION = Evaluation(...)")
    return evaluation, Path(module.__file__)


def code_digest(module_file: Path) -> str:
    """`sha256:<hex>` over the module and each repository module it imports,
    found from the imports, transitively."""
    roots = [CODE_ROOT, module_file.resolve().parent]
    seen: set[Path] = set()
    stack = [module_file.resolve()]
    while stack:
        file = stack.pop()
        if file in seen:
            continue
        seen.add(file)
        try:
            tree = ast.parse(file.read_bytes())
        except SyntaxError:
            continue
        for name in _imported_names(tree, file, roots):
            stack += _module_files(name, roots)
    return files_digest(sorted(((_display(f, roots), f) for f in seen), key=lambda p: p[0]))


def _imported_names(tree: ast.AST, file: Path, roots: list[Path]) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = _package_of(file, roots)
                if package is None:
                    continue
                parts = package.split(".") if package else []
                parts = parts[:len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join([*parts, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            if base:
                names.append(base)
            names += [f"{base}.{alias.name}" if base else alias.name for alias in node.names]
    return names


def _package_of(file: Path, roots: list[Path]) -> str | None:
    for root in roots:
        try:
            relative = file.relative_to(root)
        except ValueError:
            continue
        return ".".join(relative.parent.parts)
    return None


def _module_files(name: str, roots: list[Path]) -> list[Path]:
    """The files of a repository module and of the packages above it; none for
    a module outside the repository."""
    parts = name.split(".")
    for root in roots:
        files = []
        for i in range(1, len(parts) + 1):
            folder = root.joinpath(*parts[:i])
            if (folder / "__init__.py").is_file():
                files.append(folder / "__init__.py")
            elif folder.with_suffix(".py").is_file() and i == len(parts):
                files.append(folder.with_suffix(".py"))
            else:
                break
        if files and ".venv" not in files[0].parts:
            return [f.resolve() for f in files]
    return []


def _display(file: Path, roots: list[Path]) -> str:
    for root in roots:
        try:
            return file.relative_to(root).as_posix()
        except ValueError:
            continue
    return file.as_posix()


# --- The trials -------------------------------------------------------------------


def kept_trials(plan: Plan, excluded: set[TrialId] = frozenset()) -> list[KeptTrial]:
    """Every finished trial of every job of the experiment, but those whose
    validity check failed and the `excluded` trials. After a run an
    infrastructure failure is already deleted; a halted trial stays until the
    next invocation, but then the invocation is halted and no evaluation
    runs."""
    paths = plan.paths
    trials = []
    for job in plan.jobs:
        for name in paths.finished_trials(job.name):
            trial = TrialId(job.name, name)
            check = read_json(paths.trial_analysis(trial) / TRIAL_CHECK)
            if check is not None and check.get("passed") is False:
                continue
            if trial in excluded:
                continue
            trials.append(KeptTrial(trial, paths.trial_results(trial)))
    return trials


def task_pack(record: Trial) -> Path:
    """The trial's task pack folder, from the repository root; a folder that
    does not exist when lock.json gives no task path."""
    return Path(*record.task_path) if record.task_path else Path("tasks", "no-task-path")


def trial_cell(plan: Plan, job: JobPlan, trial_dir: Path, record: Trial):
    """The cell of a trial: the levels of the plan's agent that ran it (matched
    as the validity check matches it, by Harbor's trial config.json), and its
    language. None when no agent of the job file matches."""
    from assay.experiment import Cell, job_agents, trial_agent

    matched = trial_agent(job, trial_dir, job_agents(plan, job))
    if matched is None:
        return None
    agent = matched.plan
    return Cell(agent.harness, agent.model_tier, agent.condition, record.language or "unknown")


# --- Reuse and the run --------------------------------------------------------------


@dataclass
class EvaluationOutcome:
    """The value and the error of one evaluation for one trial."""

    value: Any
    error: str | None


class _Unknown:
    """The value of a dependency that would run again (a dry run)."""


def _assess(p: PlannedEvaluation, inp: TrialInput, folder: Path, record: str, pack: str
            ) -> tuple[str, dict, dict | None]:
    """The digest and inputs of one trial's result, and the earlier result
    when it can be reused."""
    inputs = {"record": record, "task_pack": pack, "options": json_digest(dict(p.options))}
    for dep in p.evaluation.depends_on:
        inputs[f"deps.{dep}"] = json_digest(inp.deps[dep])
    for key, value in sorted(dict(p.evaluation.pins(inp)).items()):
        inputs[f"pins.{key}"] = json_digest(value)
    digest = json_digest({"code": p.code, "inputs": inputs})
    earlier = read_json(folder / RESULT_FILE) if (folder / RESULT_FILE).is_file() else None
    reusable = earlier if (earlier and earlier.get("digest") == digest
                           and earlier.get("error") is None) else None
    return digest, inputs, reusable


def _write(folder: Path, envelope: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RESULT_FILE).write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")


def run_evaluations(plan: Plan, planned: list[PlannedEvaluation], containers: Containers,
                    log: ExperimentLog | None, dry_run: bool = False,
                    excluded: set[TrialId] = frozenset()) -> dict[str, tuple[int, int]]:
    """Runs each evaluation over every kept trial, reusing what it can. With
    dry_run, calls nothing and writes nothing: it returns, for each
    evaluation, how many results it would reuse and how many it would run."""
    jobs = {job.name: job for job in plan.jobs}
    trials = kept_trials(plan, excluded)
    records: dict[TrialId, Trial] = {}
    cells: dict[TrialId, Any] = {}
    digests: dict[TrialId, tuple[str, str]] = {}
    outcomes: dict[TrialId, dict[str, EvaluationOutcome | _Unknown]] = {t.id: {} for t in trials}
    counts = {}
    for p in planned:
        started = time.monotonic()
        ran = reused = errors = 0
        guarded = GuardedContainers(containers, p.name, p.evaluation.online)
        for t in trials:
            if t.id not in records:
                records[t.id] = record = read_trial(t.path)
                cells[t.id] = trial_cell(plan, jobs[t.id.job], t.path, record)
                digests[t.id] = (record_digest(t.path), folder_digest(task_pack(record)))
            record = records[t.id]
            folder = plan.paths.trial_analysis(t.id) / p.name
            deps = {d: outcomes[t.id][d] for d in p.evaluation.depends_on}
            inp = TrialInput(
                job=t.id.job, trial=t.id.trial, cell=cells[t.id],
                task_pack=task_pack(record), record=record,
                deps={d: o.value for d, o in deps.items() if isinstance(o, EvaluationOutcome)},
                options=dict(p.options), out=folder / OUT_FOLDER, containers=guarded)
            if any(isinstance(o, _Unknown) for o in deps.values()):
                outcomes[t.id][p.name] = _Unknown()
                ran += 1
                continue
            failed = [d for d, o in deps.items() if o.error is not None]
            if failed:
                error = f"dependency {failed[0]} has an error"
                outcomes[t.id][p.name] = EvaluationOutcome(None, error)
                errors += 1
                if not dry_run:
                    _write(folder, {"evaluation": p.name, "digest": None, "code": p.code,
                                    "inputs": {}, "started_at": timestamp(), "duration_sec": 0.0,
                                    "value": None, "error": error})
                continue
            try:
                digest, inputs, reusable = _assess(p, inp, folder, *digests[t.id])
            except Exception as e:  # a pin that cannot be read
                digest, inputs, reusable = None, {}, None
                pin_error = f"pins: {type(e).__name__}: {e}"
            else:
                pin_error = None
            if reusable is not None:
                outcomes[t.id][p.name] = EvaluationOutcome(reusable.get("value"), None)
                reused += 1
                continue
            ran += 1
            if dry_run:
                outcomes[t.id][p.name] = _Unknown()
                continue
            outcomes[t.id][p.name] = outcome = _evaluate(p, inp, folder, digest, inputs,
                                                         pin_error)
            errors += outcome.error is not None
        counts[p.name] = (reused, ran + errors if dry_run else ran)
        if dry_run:
            continue
        duration = round(time.monotonic() - started, 3)
        print(f"evaluation {p.name}: {ran} ran, {reused} reused, {errors} errors", flush=True)
        if log is not None:
            log.write("evaluation-finished", evaluation=p.name, ran=ran, reused=reused,
                      errors=errors, duration_sec=duration)
    return counts


def _evaluate(p: PlannedEvaluation, inp: TrialInput, folder: Path, digest: str | None,
              inputs: dict, error: str | None) -> EvaluationOutcome:
    """Empties the result folder, calls evaluate() and writes the result."""
    shutil.rmtree(folder, ignore_errors=True)
    inp.out.mkdir(parents=True)
    started_at, start = timestamp(), time.monotonic()
    value = None
    if error is None:
        with tempfile.TemporaryDirectory(prefix="assay-eval-") as scratch:
            inp = TrialInput(**{**inp.__dict__, "scratch": Path(scratch)})
            try:
                value = p.evaluation.evaluate(inp)
                json.dumps(value)
            except Exception as e:
                value, error = None, f"{type(e).__name__}: {e}"
    _write(folder, {"evaluation": p.name, "digest": digest, "code": p.code, "inputs": inputs,
                    "started_at": started_at, "duration_sec": round(time.monotonic() - start, 3),
                    "value": value, "error": error})
    return EvaluationOutcome(value, error)


def print_evaluation_plan(planned: list[PlannedEvaluation]) -> None:
    print("\nevaluations, in run order:" + ("" if planned else " none"))
    for p in planned:
        source = "built-in" if p.listed == p.name else p.listed
        depends = f" depends on {', '.join(p.evaluation.depends_on)}" \
            if p.evaluation.depends_on else ""
        print(f"  {p.name} ({source}){depends}")


def print_evaluation_reuse(plan: Plan, planned: list[PlannedEvaluation],
                           excluded: set[TrialId] = frozenset()) -> None:
    """What the evaluations would reuse and run over the trials so far."""
    if not planned:
        return
    counts = run_evaluations(plan, planned, _NoContainers(), None, dry_run=True,
                             excluded=excluded)
    print("evaluation results (over the trials so far; new trials run too):")
    for p in planned:
        reused, ran = counts[p.name]
        print(f"  {p.name}: {reused} reused, {ran} to run")


class _NoContainers:
    """A dry run never starts a container."""

    def pack_image(self, task_pack):
        raise RuntimeError("a dry run starts no container")

    def run(self, *args, **kwargs):
        raise RuntimeError("a dry run starts no container")
