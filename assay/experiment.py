"""`assay experiment <name>`: the plan and the run of an experiment (PRD v3
sections 5, 7 and 11; issues #60 and #61).

    uv run assay experiment <name> [--job J]... [--dry-run] [--from-scratch] [--retries N] [--debug]

`<name>` is `experiments/<name>/experiment.toml`, from the current directory
(the repository root). The plan reads the experiment's job files, and from
each agent of each job file the factor levels: the harness from the agent
class, the model tier as `model_name` unchanged, and the condition from the
variant folder that the agent's parts come from. It counts the expected
trials of each cell (task packs x agents x `n_attempts`), runs the plan-time
checks, and prints the plan. A dry run calls no Harbor and no container, and
writes and deletes nothing; it also prints what resume would keep and rerun.

The plan also loads the listed evaluations and checks them
(assay/evaluations.py); the dry run prints them and what they would reuse.

Without --dry-run, the selected jobs run in the listed order, one at a time,
each through the `assay run` path with `--jobs-dir results/<name> -y`, and
`--debug` when given (no other option reaches Harbor). Each invocation
appends to the experiment log `analysis/<name>/experiment-log.jsonl`. Resume
is the default: Harbor keeps each finished trial and runs the rest. A job
that Harbor does not finish (Ctrl-C, or a non-zero exit) stops the
invocation. After the last job, the evaluations run over every trial of
the experiment, whichever jobs ran, and then the summary (assay/summary.py)
runs again into `analysis/<name>/summary/` and logs `summary-written`. The
plan loads the summary and checks its options. --from-scratch first deletes `results/<name>` and
`analysis/<name>`, the log included.

After each run of a job, each finished trial gets the validity check and a
class (assay.trial_outcomes, issue #63). An infrastructure failure is logged
as `trial-discarded` and deleted, and --retries N runs the job again for them
up to N times. A halt is logged as `halt` and kept; the invocation stops
after that job as `halted`, and the next invocation deletes the trial (after
a `trial-discarded` with `after_halt`) and runs it again. A job file must
leave Harbor's own retry.max_retries at 0.

Before each run of a job whose agents talk to a local model server (an
`ANTHROPIC_BASE_URL` under `env:`), the server gets a health check
(assay.local_server). A server that does not answer is logged as
`server-unreachable` and stops the invocation as `error`, before Harbor
starts a trial.
"""

from __future__ import annotations

import json
import os
import re
import sys
import subprocess
import time
import tomllib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

import yaml
from harbor.models.job.config import JobConfig

from analyze.trace_check import HALT, INFRASTRUCTURE_FAILURE
from analyze.trial import read_jsonl
from assay.cli import INTERRUPTED, delete_folder, job_config, run
from assay.digests import files_digest
from assay.evaluation import Containers
from assay.evaluations import (
    EvaluationPlanError, plan_evaluations, print_evaluation_plan, print_evaluation_reuse,
    run_evaluations,
)
from assay.experiment_files import ExperimentLog, ExperimentPaths, TrialId
from assay.local_server import check_server
from assay.summary import (PlannedSummary, SummaryPlanError, plan_summary, plan_view,
                           run_summary)
from assay.trial_outcomes import TrialOutcome, agent_index, classify, logged_digests
from instruments.agent import IMPORT_PATH

EXPERIMENTS_DIR = Path("experiments")
VARIANTS_DIR = Path("variants")
HALTED = 3  # the exit code of an invocation that a halt stopped
CONTROL = "control"
# The harness level of an agent class (PRD section 5, "Factors"); any other
# agent's level is its name or import path.
HARNESSES = {IMPORT_PATH: "claude-code"}
# A pinned harness version: an exact X.Y.Z, never a channel such as `stable`.
PINNED_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# Where a job file mounts a variant's environment tools, and the tag of the
# tools image of variant <name> (PRD section 7, "Environment tools").
TOOLS_TARGET = "/opt/assay-tools"
TOOLS_TAG = "assay-tools/"
# Harbor's `${VAR}` and `${VAR:-default}` (harbor/utils/env.py).
ENV_TEMPLATE = re.compile(r"\$\{([^}:]+)(?::-(.*))?\}")
# An agent that sets this under `env:` talks to a local model server (L10).
BASE_URL_KEY = "ANTHROPIC_BASE_URL"

EXPERIMENT_KEYS = {"jobs", "evaluations", "evaluation-options", "summary"}
SUMMARY_KEYS = {"use", "options"}


class PlanError(Exception):
    """A plan-time check failed; the experiment stops at no cost."""


@dataclass(frozen=True)
class Cell:
    harness: str
    model_tier: str
    condition: str
    language: str


@dataclass
class AgentPlan:
    harness: str
    model_tier: str
    condition: str
    condition_digest: str | None  # None for the control


@dataclass
class JobPlan:
    name: str
    file: Path
    selected: bool
    agents: list[AgentPlan]
    expected: Counter[Cell] = field(default_factory=Counter)
    # The local model servers its agents talk to: each ANTHROPIC_BASE_URL,
    # with its ${VAR} filled from the environment.
    servers: list[str] = field(default_factory=list)


@dataclass
class Plan:
    experiment: str
    jobs: list[JobPlan]
    evaluations: list[str]
    summary: str | None
    planned_evaluations: list = field(default_factory=list)  # assay.evaluations
    planned_summary: PlannedSummary | None = None

    @property
    def paths(self) -> ExperimentPaths:
        return ExperimentPaths(self.experiment)

    @property
    def expected(self) -> Counter[Cell]:
        total: Counter[Cell] = Counter()
        for job in self.jobs:
            total.update(job.expected)
        return total


def read_experiment(name: str) -> dict:
    path = EXPERIMENTS_DIR / name / "experiment.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise PlanError(f"cannot read {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise PlanError(f"{path} is not valid TOML: {e}") from e
    unknown = [key for key in data if key not in EXPERIMENT_KEYS]
    summary = data.get("summary", {})
    if not isinstance(summary, dict):
        raise PlanError(f"{path}: `summary` must be a table")
    unknown += [f"summary.{key}" for key in summary if key not in SUMMARY_KEYS]
    if unknown:
        raise PlanError(f"{path}: unknown key {', '.join(unknown)} (in TOML, a key "
                        f"belongs to the last table header above it)")
    jobs = data.get("jobs")
    if not jobs or not isinstance(jobs, list) or not all(isinstance(j, str) for j in jobs):
        raise PlanError(f"{path}: `jobs` must list the job files in run order")
    evaluations = data.get("evaluations", [])
    if not isinstance(evaluations, list) or not all(isinstance(e, str) for e in evaluations):
        raise PlanError(f"{path}: `evaluations` must list the evaluations in run order")
    if repeated := sorted({e for e in evaluations if evaluations.count(e) > 1}):
        raise PlanError(f"{path}: evaluation {', '.join(repeated)} is listed more than once")
    options = data.get("evaluation-options", {})
    if unlisted := [e for e in options if e not in evaluations]:
        raise PlanError(f"{path}: [evaluation-options.{unlisted[0]}] is for an evaluation "
                        f"that `evaluations` does not list")
    return data


def env_templates(value) -> list[tuple[str, str | None]]:
    """Each `${VAR}` (with its default, or None) in the strings of a parsed YAML value."""
    if isinstance(value, str):
        return [(m.group(1), m.group(2)) for m in ENV_TEMPLATE.finditer(value)]
    if isinstance(value, dict):
        return [t for v in value.values() for t in env_templates(v)]
    if isinstance(value, list):
        return [t for v in value for t in env_templates(v)]
    return []


def fill_env(value: str) -> str:
    """The string with each `${VAR}` and `${VAR:-default}` filled, as Harbor fills it."""
    return ENV_TEMPLATE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)


def content_digest(paths: Sequence[Path], inline: Sequence[object]) -> str:
    """`sha256:<hex>` over each part file's path and content, and each inline part."""
    files = sorted({f for p in paths for f in ([p] if p.is_file() else p.rglob("*"))
                    if f.is_file() and "__pycache__" not in f.parts})
    return files_digest(((f.as_posix(), f) for f in files),
                        (json.dumps(part, sort_keys=True).encode("utf-8") + b"\n"
                         for part in inline))


def variant_folder(part: Path, job: str, what: str) -> str:
    """The name of the variant folder that holds the part, or refuse the plan."""
    root = VARIANTS_DIR.resolve()
    try:
        relative = part.resolve().relative_to(root)
    except ValueError:
        raise PlanError(f"{job}: {what} {part.as_posix()} is outside {VARIANTS_DIR}/; a "
                        f"variant part must be in its variant folder") from None
    if not relative.parts:
        raise PlanError(f"{job}: {what} {part.as_posix()} is not inside a variant folder")
    return relative.parts[0]


def agent_parts(config: JobConfig, agent, job: str) -> tuple[dict[Path, str], list[object]]:
    """The variant parts the agent receives: each part path with what it is, and
    each inline part (PRD section 7, "Variants")."""
    paths: dict[Path, str] = {}
    inline: list[object] = []
    for skill in agent.skills:
        if isinstance(skill, str):
            paths[Path(skill)] = "skill"
        else:
            inline.append(skill.model_dump(mode="json") if hasattr(skill, "model_dump")
                          else skill)
    for extra in config.extra_instruction_paths:
        paths[Path(extra)] = "extra instruction"
    inline += list(config.extra_instructions)
    settings = agent.kwargs.get("config")
    if isinstance(settings, str) and not settings.lstrip().startswith("{"):
        paths[Path(settings)] = "settings"
    elif settings is not None:
        inline.append(settings)
    if instruction_file := agent.kwargs.get("instruction_file"):
        paths[Path(instruction_file)] = "instruction file"
    inline += [server.model_dump(mode="json") for server in agent.mcp_servers]
    for mount in config.environment.mounts or []:
        mount = mount if isinstance(mount, dict) else mount.model_dump(mode="json")
        if str(mount.get("target", "")).rstrip("/") != TOOLS_TARGET:
            continue
        source = str(mount.get("source", ""))
        if not source.startswith(TOOLS_TAG):
            raise PlanError(f"{job}: the tools mount {source} is not a tools image "
                            f"{TOOLS_TAG}<variant>")
        paths[VARIANTS_DIR / source.removeprefix(TOOLS_TAG) / "tools" / "tools.lock"] = \
            "tools lock"
    return paths, inline


def plan_agent(config: JobConfig, agent, job: str) -> AgentPlan:
    harness = HARNESSES.get(agent.import_path or "", agent.name or agent.import_path or "")
    version = agent.kwargs.get("version")
    if not (isinstance(version, str) and PINNED_VERSION.fullmatch(version)):
        raise PlanError(f"{job}: the harness version of {agent.model_name} "
                        f"(kwargs.version) is {version!r}, not a pinned X.Y.Z")
    paths, inline = agent_parts(config, agent, job)
    folders = {variant_folder(path, job, what) for path, what in paths.items()}
    if len(folders) > 1:
        raise PlanError(f"{job}: the parts of {agent.model_name} come from more than one "
                        f"variant folder: {', '.join(sorted(folders))}")
    if not folders and inline:
        raise PlanError(f"{job}: {agent.model_name} has inline parts and no variant folder "
                        f"to name its condition")
    if not folders:
        return AgentPlan(harness, agent.model_name or "", CONTROL, None)
    return AgentPlan(harness, agent.model_name or "", folders.pop(),
                     content_digest(list(paths), inline))


def plan_job(file: Path, experiment: str, selected: set[str] | None) -> JobPlan:
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        config = job_config(file, ["--jobs-dir", ExperimentPaths(experiment).results.as_posix()])
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise PlanError(f"cannot read job file {file.as_posix()}: {e}") from e
    name = config.job_name
    if config.retry.max_retries != 0:
        raise PlanError(f"{name}: retry.max_retries is {config.retry.max_retries} in "
                        f"{file.as_posix()}; it must stay 0, so that only Assay retries, "
                        f"after a validity check (--retries)")
    is_selected = selected is None or name in selected
    if is_selected:
        unset = sorted({var for var, default in env_templates(raw)
                        if default is None and var not in os.environ})
        if unset:
            raise PlanError(f"{name}: {', '.join('${' + v + '}' for v in unset)} in "
                            f"{file.as_posix()} is not set")
    agents = [plan_agent(config, agent, name) for agent in config.agents]
    servers = sorted({fill_env(url) for agent in config.agents
                      if (url := agent.env.get(BASE_URL_KEY))})
    job = JobPlan(name, file, is_selected, agents, servers=servers)
    for agent in agents:
        for task in config.tasks:
            language = Path(task.path).parts[-2] if task.path else "unknown"
            cell = Cell(agent.harness, agent.model_tier, agent.condition, language)
            job.expected[cell] += config.n_attempts
    return job


def make_plan(name: str, selected_jobs: Sequence[str] = ()) -> Plan:
    data = read_experiment(name)
    selected = set(selected_jobs) or None
    jobs = [plan_job(Path(file), name, selected) for file in data["jobs"]]
    if selected and (unknown := sorted(selected - {job.name for job in jobs})):
        raise PlanError(f"--job {', '.join(unknown)}: no such job in experiment {name} "
                        f"(its jobs: {', '.join(job.name for job in jobs)})")
    plan = Plan(name, jobs, list(data.get("evaluations", [])),
                data.get("summary", {}).get("use"))
    try:
        plan.planned_evaluations = plan_evaluations(
            EXPERIMENTS_DIR / name, plan.evaluations, data.get("evaluation-options", {}),
            {agent.harness for job in jobs for agent in job.agents})
    except EvaluationPlanError as e:
        raise PlanError(str(e)) from e
    if plan.summary is not None:
        try:
            plan.planned_summary = plan_summary(EXPERIMENTS_DIR / name, plan.summary,
                                                data["summary"].get("options", {}),
                                                plan_view(plan))
        except SummaryPlanError as e:
            raise PlanError(str(e)) from e
    return plan


def print_plan(plan: Plan) -> None:
    print(f"experiment {plan.experiment} "
          f"({(EXPERIMENTS_DIR / plan.experiment / 'experiment.toml').as_posix()})")
    print(f"\njobs, in run order (results in "
          f"{plan.paths.results.as_posix()}/<job>/):")
    for job in plan.jobs:
        mark = "" if job.selected else "   (not selected)"
        print(f"  {job.name:<22} {job.file.as_posix():<34} "
              f"trials {sum(job.expected.values())}{mark}")
        for agent in job.agents:
            print(f"    {agent.harness}  {agent.model_tier}  {agent.condition}")
    print("\nconditions:")
    digests: dict[str, set[str]] = {}
    for job in plan.jobs:
        for agent in job.agents:
            digests.setdefault(agent.condition, set())
            if agent.condition_digest:
                digests[agent.condition].add(agent.condition_digest)
    for condition, found in digests.items():
        print(f"  {condition:<22} {', '.join(sorted(found)) or 'no parts'}")
    expected = plan.expected
    print("\nexpected trials by cell (trials, harness, model tier, condition, language):")
    for cell, n in sorted(expected.items(), key=lambda item: (
            item[0].condition, item[0].model_tier, item[0].language)):
        print(f"  cell {n} {cell.harness} {cell.model_tier} {cell.condition} {cell.language}")
    print(f"  {sum(expected.values())} expected trials")
    print_evaluation_plan(plan.planned_evaluations)
    print(f"summary: {plan.summary} (runs again on every invocation)" if plan.summary
          else "summary: none")


def experiment_folders(plan: Plan) -> list[Path]:
    """What --from-scratch deletes: the results and the analysis, the log included."""
    return [plan.paths.results, plan.paths.analysis]


def print_resume(plan: Plan, from_scratch: bool) -> None:
    """What the next invocation deletes, keeps and runs (PRD section 11, "Resume")."""
    print()
    if from_scratch:
        for folder in experiment_folders(plan):
            print(f"from scratch: would delete {folder.as_posix()}" if folder.exists()
                  else f"from scratch: nothing to delete, {folder.as_posix()} does not exist")
    print("resume (finished trials are kept; Harbor runs the rest):")
    halted = {} if from_scratch else halted_trials(plan)
    for job in plan.jobs:
        if not job.selected:
            continue
        finished = [] if from_scratch else [t for t in plan.paths.finished_trials(job.name)
                                            if TrialId(job.name, t) not in halted]
        to_run = max(sum(job.expected.values()) - len(finished), 0)
        noun = "trial" if len(finished) == 1 else "trials"
        print(f"  {job.name:<22} {len(finished)} finished {noun} kept, {to_run} to run")
        for trial in [] if from_scratch else plan.paths.unfinished_trials(job.name):
            print(f"    {trial} (unfinished, Harbor deletes it)")
        for trial, event in halted.items():
            if trial.job == job.name:
                cause = event["cause"]
                what = cause.get("exception") or ", ".join(cause.get("failed_checks", []))
                print(f"    {trial.trial} (halted: {what}, Assay deletes it)")
    if not from_scratch:
        print_evaluation_reuse(plan, plan.planned_evaluations, excluded=set(halted))


def assay_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def harbor_version() -> str | None:
    try:
        return metadata.version("harbor")
    except metadata.PackageNotFoundError:
        return None


def agent_fields(agents: Sequence[AgentPlan]) -> list[dict]:
    return [asdict(agent) for agent in agents]


def run_job(plan: Plan, job: JobPlan, log: ExperimentLog, debug: bool,
            run_harbor: Callable[[Sequence[str]], int], retry: int = 0) -> int:
    """Run one job through the `assay run` path; return its exit code."""
    # The trials finished before the run, so that check 8 can tell which run
    # finished each trial (trial_outcomes.logged_digests).
    log.write("job-started", job=job.name, file=job.file.as_posix(),
              agents=agent_fields(job.agents), trials=plan.paths.finished_trials(job.name),
              **({"retry": retry} if retry else {}))
    args = ["-c", job.file.as_posix(), "--jobs-dir", plan.paths.results.as_posix(),
            "-y", *(["--debug"] if debug else [])]
    print(f"\njob {job.name}: assay run {' '.join(args)}", flush=True)
    started = time.monotonic()
    try:
        exit_code = run(args, run_harbor)
    except KeyboardInterrupt:
        exit_code = INTERRUPTED
    # The digests again, so that a part edited during the job shows
    # (validity check 8 compares them with the plan's).
    try:
        agents = agent_fields(plan_job(job.file, plan.experiment, None).agents)
    except PlanError as e:
        print(f"error: assay experiment: {e}", file=sys.stderr)
        agents, exit_code = [], exit_code or 2
    log.write("job-finished", job=job.name, exit_code=exit_code,
              trials=plan.paths.finished_trials(job.name),
              duration_sec=round(time.monotonic() - started, 3), agents=agents)
    return exit_code


def job_agents(plan: Plan, job: JobPlan) -> list[dict]:
    """The agents of the job file as Harbor writes them in each trial's
    config.json: without the fields that have their default value."""
    config = job_config(job.file, ["--jobs-dir", plan.paths.results.as_posix()])
    return [agent.model_dump(mode="json", exclude_defaults=True) for agent in config.agents]


@dataclass(frozen=True)
class MatchedAgent:
    index: int  # the agent's place in the job file
    plan: AgentPlan


def trial_agent(job: JobPlan, trial_dir: Path, agents: list[dict]) -> MatchedAgent | None:
    """The plan's agent that ran the trial (trial_outcomes.agent_index); None
    when no agent of the job file matches."""
    index = agent_index(trial_dir, agents)
    return MatchedAgent(index, job.agents[index]) if index is not None else None


def check_job(plan: Plan, job: JobPlan, log: ExperimentLog) -> list[TrialOutcome]:
    """The validity check and class of each finished trial of the job."""
    agents = job_agents(plan, job)
    events = log.events()
    outcomes = []
    for name in plan.paths.finished_trials(job.name):
        trial = TrialId(job.name, name)
        trial_dir = plan.paths.trial_results(trial)
        matched = trial_agent(job, trial_dir, agents)
        index = matched.index if matched else None
        outcomes.append(classify(trial_dir, job.name, asdict(matched.plan) if matched else None,
                                 logged_digests(events, job.name, name, index),
                                 plan.paths.trial_analysis(trial)))
    return outcomes


def servers_answer(job: JobPlan, log: ExperimentLog) -> bool:
    """The health check of each local server of the job, before each run of
    it; a server that does not answer is logged and stops the invocation."""
    for server in job.servers:
        if (problem := check_server(server)) is not None:
            log.write("server-unreachable", job=job.name, server=server, problem=problem)
            print(f"error: assay experiment: job {job.name} needs the local model server, "
                  f"and {problem}. Start the server (or fix ASSAY_LOCAL_BASE_URL) and run "
                  f"again; finished trials are kept.", file=sys.stderr)
            return False
    return True


def discard_trial(plan: Plan, fields: dict, cause: dict, log: ExperimentLog,
                  **extra) -> None:
    """Log the trial as discarded, then delete its results and analysis folders."""
    log.write("trial-discarded", **fields, cause=cause, **extra)
    trial = TrialId(fields["job"], fields["trial"])
    for folder in (plan.paths.trial_results(trial), plan.paths.trial_analysis(trial)):
        if folder.exists():
            delete_folder(folder)
    print(f"  discarded {fields['job']}/{fields['trial']}: {json.dumps(cause)}")


def settle_job(plan: Plan, job: JobPlan, log: ExperimentLog) -> tuple[int, int]:
    """After a run of the job: discard its infrastructure failures and log its
    halts, which stay until the next invocation. Returns (discarded, halts)."""
    discarded = halts = 0
    for outcome in check_job(plan, job, log):
        if outcome.kind == INFRASTRUCTURE_FAILURE:
            discard_trial(plan, outcome.fields, outcome.cause, log)
            discarded += 1
        elif outcome.kind == HALT:
            log.write("halt", **outcome.fields, cause=outcome.cause,
                      message=halt_message(outcome.cause))
            print(f"  halt {job.name}/{outcome.trial}: {halt_message(outcome.cause)}")
            halts += 1
    return discarded, halts


def halt_message(cause: dict) -> str:
    what = cause.get("exception") or f"failed validity check {', '.join(cause['failed_checks'])}"
    return (f"{what}: running again would repeat it. Fix the cause; the next invocation "
            f"deletes the trial and runs it again.")


def halted_trials(plan: Plan) -> dict[TrialId, dict]:
    """The halt event of each trial that an earlier invocation halted and that
    is still there."""
    halts: dict[TrialId, dict] = {}
    for event in read_jsonl(plan.paths.log):
        trial = TrialId(event.get("job"), event.get("trial"))
        if event["event"] == "halt":
            halts[trial] = event
        elif event["event"] == "trial-discarded":
            halts.pop(trial, None)
    return {trial: e for trial, e in halts.items() if plan.paths.trial_results(trial).exists()}


def discard_halted_trials(plan: Plan, log: ExperimentLog) -> None:
    """Resume: delete each trial of an earlier halt, after logging it."""
    for event in halted_trials(plan).values():
        fields = {k: v for k, v in event.items()
                  if k not in ("at", "invocation", "event", "cause", "message")}
        discard_trial(plan, fields, event["cause"], log, after_halt=True)


def run_experiment(plan: Plan, argv: Sequence[str], debug: bool,
                   run_harbor: Callable[[Sequence[str]], int], containers: Containers,
                   retries: int = 0) -> int:
    """Run the selected jobs in order, one at a time, and log the invocation.
    After each run of a job, check its trials, discard the infrastructure
    failures and run the job again for them, up to `retries` times. Stops at
    the first job that Harbor did not finish, and after a job with a halt.
    When every job completes, run the evaluations over every trial of the
    experiment."""
    log = ExperimentLog(plan.paths)
    log.write("invocation-started", command=["assay", "experiment", *argv],
              assay_commit=assay_commit(), harbor_version=harbor_version())
    outcome, code = "complete", 0
    try:
        discard_halted_trials(plan, log)
        for job in plan.jobs:
            if not job.selected:
                continue
            retry = 0
            while True:
                if not servers_answer(job, log):
                    exit_code = 2
                    break
                exit_code = run_job(plan, job, log, debug, run_harbor, retry)
                if exit_code != 0:
                    break
                discarded, halts = settle_job(plan, job, log)
                if halts or not discarded or retry == retries:
                    break
                retry += 1
            if exit_code == INTERRUPTED:
                outcome, code = "interrupted", INTERRUPTED
                break
            if exit_code != 0:
                outcome, code = "error", exit_code
                break
            if halts:
                outcome, code = "halted", HALTED
                break
        if outcome == "complete":
            run_evaluations(plan, plan.planned_evaluations, containers, log)
            if plan.planned_summary is not None:
                try:
                    run_summary(plan, plan.planned_summary, log)
                except Exception as e:  # the summary's own failure
                    print(f"error: assay experiment: summary {plan.summary}: "
                          f"{type(e).__name__}: {e}", file=sys.stderr)
                    outcome, code = "error", 2
    except KeyboardInterrupt:
        outcome, code = "interrupted", INTERRUPTED
    log.write("invocation-finished", outcome=outcome)
    print(f"\nexperiment {plan.experiment}: {outcome}")
    return code


def error(message: str) -> int:
    print(f"error: assay experiment: {message}", file=sys.stderr)
    return 2


USAGE = "usage: assay experiment <name> [--job J]... [--dry-run] [--from-scratch] [--retries N] [--debug]"


def experiment(args: Sequence[str], run_harbor: Callable[[Sequence[str]], int],
               containers: Containers | None = None) -> int:
    """The `experiment` subcommand. `run_harbor` runs `harbor run` and
    `containers` starts the evaluations' containers (Docker when None); a dry
    run calls neither."""
    argv = list(args)
    args = list(args)
    names, jobs = [], []
    dry_run = from_scratch = debug = False
    retries = 0
    while args:
        arg = args.pop(0)
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--from-scratch":
            from_scratch = True
        elif arg == "--debug":
            debug = True  # the one option that reaches Harbor
        elif arg == "--job":
            if not args:
                return error("--job needs a job name")
            jobs.append(args.pop(0))
        elif arg.startswith("--job="):
            jobs.append(arg.split("=", 1)[1])
        elif arg == "--retries" or arg.startswith("--retries="):
            value = arg.split("=", 1)[1] if "=" in arg else (args.pop(0) if args else "")
            if not value.isdigit():
                return error(f"--retries needs a whole number of 0 or more, not {value!r}")
            retries = int(value)
        elif arg.startswith("-"):
            return error(f"unknown option {arg} (no option but --debug reaches Harbor)\n{USAGE}")
        else:
            names.append(arg)
    if len(names) != 1:
        return error(f"give one experiment name\n{USAGE}")
    try:
        plan = make_plan(names[0], jobs)
    except PlanError as e:
        return error(str(e))
    print_plan(plan)
    if dry_run:
        print_resume(plan, from_scratch)
        print("\ndry run: no job runs, and nothing is written or deleted.")
        return 0
    if from_scratch:
        for folder in experiment_folders(plan):
            if folder.exists():
                delete_folder(folder)
                print(f"deleted {folder.as_posix()}")
    if containers is None:
        from assay.containers import DockerContainers

        containers = DockerContainers()
    return run_experiment(plan, argv, debug, run_harbor, containers, retries)
