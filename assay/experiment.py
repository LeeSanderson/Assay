"""`assay experiment <name>`: the plan of an experiment (PRD v3 sections 5, 7
and 11; issue #60).

    uv run assay experiment <name> [--job J]... --dry-run

`<name>` is `experiments/<name>/experiment.toml`, from the current directory
(the repository root). The plan reads the experiment's job files, and from
each agent of each job file the factor levels: the harness from the agent
class, the model tier as `model_name` unchanged, and the condition from the
variant folder that the agent's parts come from. It counts the expected
trials of each cell (task packs x agents x `n_attempts`), runs the plan-time
checks, and prints the plan. A dry run calls no Harbor and no container, and
writes and deletes nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from harbor.models.job.config import JobConfig

from instruments.agent import IMPORT_PATH

EXPERIMENTS_DIR = Path("experiments")
VARIANTS_DIR = Path("variants")
RESULTS_DIR = Path("results")
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


@dataclass
class Plan:
    experiment: str
    jobs: list[JobPlan]
    evaluations: list[str]
    summary: str | None

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


def content_digest(paths: Sequence[Path], inline: Sequence[object]) -> str:
    """`sha256:<hex>` over each part file's path and content, and each inline part."""
    files = sorted({f for p in paths for f in ([p] if p.is_file() else p.rglob("*"))
                    if f.is_file() and "__pycache__" not in f.parts})
    outer = hashlib.sha256()
    for f in files:
        content = hashlib.sha256(f.read_bytes()).hexdigest()
        outer.update(f"{f.as_posix()}\0{content}\n".encode("utf-8"))
    for part in inline:
        outer.update(json.dumps(part, sort_keys=True).encode("utf-8") + b"\n")
    return f"sha256:{outer.hexdigest()}"


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
    from assay.cli import job_config  # assay.cli imports this module

    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        config = job_config(file, ["--jobs-dir", (RESULTS_DIR / experiment).as_posix()])
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise PlanError(f"cannot read job file {file.as_posix()}: {e}") from e
    name = config.job_name
    is_selected = selected is None or name in selected
    if is_selected:
        unset = sorted({var for var, default in env_templates(raw)
                        if default is None and var not in os.environ})
        if unset:
            raise PlanError(f"{name}: {', '.join('${' + v + '}' for v in unset)} in "
                            f"{file.as_posix()} is not set")
    agents = [plan_agent(config, agent, name) for agent in config.agents]
    job = JobPlan(name, file, is_selected, agents)
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
    return Plan(name, jobs, list(data.get("evaluations", [])),
                data.get("summary", {}).get("use"))


def print_plan(plan: Plan) -> None:
    print(f"experiment {plan.experiment} "
          f"({(EXPERIMENTS_DIR / plan.experiment / 'experiment.toml').as_posix()})")
    print(f"\njobs, in run order (results in "
          f"{(RESULTS_DIR / plan.experiment).as_posix()}/<job>/):")
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
    print(f"\nevaluations, in run order: {', '.join(plan.evaluations) or 'none'}")
    print(f"summary: {plan.summary or 'none'}")


def error(message: str) -> int:
    print(f"error: assay experiment: {message}", file=sys.stderr)
    return 2


USAGE = "usage: assay experiment <name> [--job J]... --dry-run"


def experiment(args: Sequence[str], run_harbor: Callable[[Sequence[str]], int]) -> int:
    """The `experiment` subcommand. `run_harbor` runs `harbor run`; the plan never calls it."""
    args = list(args)
    names, jobs, dry_run = [], [], False
    while args:
        arg = args.pop(0)
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--job":
            if not args:
                return error("--job needs a job name")
            jobs.append(args.pop(0))
        elif arg.startswith("--job="):
            jobs.append(arg.split("=", 1)[1])
        elif arg.startswith("-"):
            return error(f"unknown option {arg}\n{USAGE}")
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
        print("\ndry run: no job runs, and nothing is written or deleted.")
        return 0
    return error("running an experiment is not built yet; use --dry-run")
