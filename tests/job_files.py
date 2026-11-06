"""Helpers for the job-file tests: a committed job file read through Harbor's
own job model, and the trials it expands to. The tests that use them run
from the repository root (the `run_from_repo_root` fixture in conftest.py),
because Harbor resolves task and skill paths against the current directory."""

import asyncio
import uuid
from pathlib import Path

import yaml
from harbor.job_plan import JobPlan
from harbor.models.job.config import JobConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = REPO_ROOT / "jobs"
INSTRUMENT_INSTRUCTION = "variants/instrument-tdd/extra-instruction.md"


def load_job(name: str) -> JobConfig:
    data = yaml.safe_load((JOBS_DIR / name).read_text(encoding="utf-8"))
    return JobConfig.model_validate(data)


def expand_trials(config: JobConfig):
    tasks = asyncio.run(JobPlan.resolve_task_configs(config))
    return JobPlan.build_trial_configs(config, tasks, job_id=uuid.uuid4())


def trial_key(trial) -> tuple[str, str, str]:
    """(model, condition, language) for one trial config."""
    condition = "instrument-tdd" if trial.agent.skills else "control"
    language = Path(trial.task.path).parts[-2]
    return trial.agent.model_name, condition, language
