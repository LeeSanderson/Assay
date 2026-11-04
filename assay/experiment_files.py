"""The files of an experiment: its local modules, where its results and
analysis are, and its experiment log (PRD v3 sections 11 and 12).

    experiments/<experiment>/<file>.py             an experiment-local module
    results/<experiment>/<job>/<trial>/            Harbor's trial folder
    analysis/<experiment>/<job>/<trial>/           the trial's analysis folder
    analysis/<experiment>/experiment-log.jsonl     the experiment log
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from analyze.trial import read_jsonl

RESULTS_DIR = Path("results")
ANALYSIS_DIR = Path("analysis")
LOG_FILE = "experiment-log.jsonl"
FINISHED = "result.json"  # Harbor writes it when it finishes a trial


@dataclass(frozen=True, order=True)
class TrialId:
    """One trial of an experiment: its job and its folder name."""

    job: str
    trial: str


@dataclass(frozen=True)
class ExperimentPaths:
    experiment: str
    results_root: Path = RESULTS_DIR
    analysis_root: Path = ANALYSIS_DIR

    @property
    def results(self) -> Path:
        return self.results_root / self.experiment

    @property
    def analysis(self) -> Path:
        return self.analysis_root / self.experiment

    @property
    def log(self) -> Path:
        return self.analysis / LOG_FILE

    def job_results(self, job: str) -> Path:
        return self.results / job

    def trial_results(self, trial: TrialId) -> Path:
        return self.results / trial.job / trial.trial

    def trial_analysis(self, trial: TrialId) -> Path:
        return self.analysis / trial.job / trial.trial

    def finished_trials(self, job: str) -> list[str]:
        """The trials of the job that Harbor finished: those with a result.json."""
        folder = self.job_results(job)
        if not folder.is_dir():
            return []
        return sorted(t.name for t in folder.iterdir() if (t / FINISHED).is_file())

    def unfinished_trials(self, job: str) -> list[str]:
        """The trial folders with no result.json, which Harbor's resume deletes and reruns."""
        folder = self.job_results(job)
        if not folder.is_dir():
            return []
        return sorted(t.name for t in folder.iterdir()
                      if t.is_dir() and not (t / FINISHED).is_file())


class LocalModuleError(Exception):
    """An experiment-local module is missing or does not load."""


def load_local_module(experiment_dir: Path, listed: str, what: str) -> ModuleType:
    """The module of a `./<file>.py` in the experiment's folder, as
    experiment.toml lists it; `what` ("evaluation", "summary") names it in an
    error."""
    path = experiment_dir / listed
    if not path.is_file():
        raise LocalModuleError(f"{what} {listed}: no file {path.as_posix()}")
    module_name = f"assay_local_{experiment_dir.name}_{path.stem}".replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise LocalModuleError(f"{what} {listed} does not load: {e}") from e
    return module


def timestamp() -> str:
    """Now, in UTC, to the second: the time of a log event or a result."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExperimentLog:
    """`analysis/<experiment>/experiment-log.jsonl`, appended across
    invocations (PRD section 11, "The experiment log")."""

    def __init__(self, paths: ExperimentPaths):
        self.path = paths.log
        self.invocation = uuid.uuid4().hex

    def write(self, event: str, **fields) -> None:
        line = {"at": timestamp(), "invocation": self.invocation, "event": event, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    def events(self) -> list[dict]:
        """Every event of the log, in order."""
        return read_jsonl(self.path)
