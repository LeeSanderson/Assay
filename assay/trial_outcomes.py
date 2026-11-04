"""After each job of an experiment: the class of each trial (PRD v3 section
11, "Infrastructure failures"; issue #63).

A trial is a result, an infrastructure failure, or a halt. Harbor's exception
type decides first; a trial whose exception (if any) is a result then goes
through the ten-check validity check (PRD v3 section 8). Check 8 compares the
plan's condition digest of the trial's agent with the digests the experiment
log recorded for the run of the job in which the trial ran.

Harbor 0.24 records a trial's exception in its result.json and goes on; `harbor
run` exits 0 when trials fail. A non-zero exit means the job itself did not
run or finish (a bad config, a preflight failure, a crash), so the experiment
stops with an error and checks no trial.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from analyze.trace_check import (HALT, INFRASTRUCTURE_FAILURE, ConditionDigests,
                                 validity_check, write_trial_check)
from analyze.trial import read_json, read_trial

RESULT = "result"

# Harbor exception types, by class (PRD v3 section 11). Any type that is not
# listed is an infrastructure failure that the summary lists by type.
RESULT_EXCEPTIONS = frozenset({
    "AgentTimeoutError", "ContextWindowExceededError", "OutputTokenExceededError",
    "AgentSafetyRefusalError", "VerifierTimeoutError"})
HALT_EXCEPTIONS = frozenset({"ApiUsageLimitError", "AgentAuthenticationError",
                             "ModelNotFoundError"})
INFRASTRUCTURE_EXCEPTIONS = frozenset({
    "ApiRateLimitError", "ApiOverloadedError", "ApiInternalServerError",
    "ApiConnectionClosedError", "ApiResponseStalledError", "NetworkConnectionError",
    "SandboxBuildFailedError", "EnvironmentStartTimeoutError", "HealthcheckError",
    "AgentSetupTimeoutError", "CancelledError",
    "RewardFileNotFoundError", "RewardFileEmptyError", "VerifierOutputParseError",
    "AddTestsDirError", "DownloadVerifierDirError",
    "NonZeroAgentExitCodeError", "UnknownApiError"})


@dataclass(frozen=True)
class TrialOutcome:
    trial: str
    kind: str  # RESULT, INFRASTRUCTURE_FAILURE or HALT
    cause: dict  # {"exception": type} or {"failed_checks": [...]}; {} for a result
    fields: dict  # the trial's fields of a trial-discarded or halt event

    @property
    def kept(self) -> bool:
        return self.kind == RESULT


def exception_class(exception_type: str) -> tuple[str, dict]:
    """The class of a Harbor exception type, and the cause to log."""
    cause = {"exception": exception_type}
    if exception_type in RESULT_EXCEPTIONS:
        return RESULT, {}
    if exception_type in HALT_EXCEPTIONS:
        return HALT, cause
    if exception_type not in INFRASTRUCTURE_EXCEPTIONS:
        cause["unlisted"] = True  # a person classifies each new type
    return INFRASTRUCTURE_FAILURE, cause


def read_log(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def logged_digests(events: list[dict], job: str, trial: str,
                   agent: int | None) -> tuple[str | None, ...]:
    """The condition digests of the agent that the log recorded for the run of
    the job in which the trial ran: the job-started before the first event that
    lists the trial, and that event when it is the job-finished of the run.

    A job-started lists the trials that were finished before it, so a trial
    finished by a run that ended without a job-finished (a killed process) is
    still put in that run. A trial-discarded of the trial starts again."""
    if agent is None:
        return ()
    runs = [e for e in events if e.get("job") == job]
    discards = [i for i, e in enumerate(runs)
                if e["event"] == "trial-discarded" and e.get("trial") == trial]
    runs = runs[discards[-1] + 1:] if discards else runs
    for i, event in enumerate(runs):
        if event["event"] in ("job-started", "job-finished") and trial in event.get("trials", []):
            break
    else:
        return ()
    started = [e for e in runs[:i] if e["event"] == "job-started"]
    if not started:
        return ()
    run = [started[-1]] + ([event] if event["event"] == "job-finished" else [])
    digests = []
    for e in run:
        agents = e.get("agents") or []
        digests.append(agents[agent].get("condition_digest") if agent < len(agents) else "")
    return tuple(digests)


def agent_index(trial_dir: Path, agents: list[dict]) -> int | None:
    """Which agent of the job file ran the trial, from Harbor's trial config."""
    config = read_json(trial_dir / "config.json") or {}
    agent = config.get("agent")
    for i, candidate in enumerate(agents):
        if candidate == agent:
            return i
    return None


def event_fields(trial_dir: Path, job: str, agent: dict | None, result: dict) -> dict:
    usage = result.get("agent_result") or {}
    trial = read_trial(trial_dir) if (trial_dir / "lock.json").is_file() else None
    cell = None if agent is None else {
        "harness": agent["harness"], "model_tier": agent["model_tier"],
        "condition": agent["condition"], "language": trial.language if trial else None}
    return {
        "job": job,
        "trial": trial_dir.name,
        "cell": cell,
        "task_pack": trial.identity.task_pack if trial else None,
        "tokens": {"input": usage.get("n_input_tokens"), "cache": usage.get("n_cache_tokens"),
                   "output": usage.get("n_output_tokens")},
        "cost_usd": usage.get("cost_usd"),
        "duration_sec": trial.duration_sec if trial else None,
    }


def classify(trial_dir: Path, job: str, agent: dict | None, logged: tuple[str | None, ...],
             analysis_dir: Path) -> TrialOutcome:
    """The class of one finished trial, run by the agent of the plan (an
    AgentPlan as a dict; None when no agent of the job file matches). A trial
    that reaches the validity check gets its trial-check.json in analysis_dir."""
    result = read_json(trial_dir / "result.json") or {}
    fields = event_fields(trial_dir, job, agent, result)
    planned = agent["condition_digest"] if agent else None
    exception = (result.get("exception_info") or {}).get("exception_type")
    if exception:
        kind, cause = exception_class(exception)
        if kind != RESULT:
            return TrialOutcome(trial_dir.name, kind, cause, fields)
    check = validity_check(read_trial(trial_dir), ConditionDigests(planned, logged))
    write_trial_check(check, analysis_dir)
    if check.passed:
        return TrialOutcome(trial_dir.name, RESULT, {}, fields)
    return TrialOutcome(trial_dir.name, check.failure_class, {"failed_checks": check.failed},
                        fields)
