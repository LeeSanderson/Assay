"""The validity check of the trial record (PRD v3 section 8, "The validity
check"): ten checks on each trial, after its job and before any evaluation.

    uv run assay trace-check results/<job-id> [--analysis analysis]

checks each trial of one job folder, prints one JSON line per trial with its
failed checks, and writes <analysis>/<job-id>/<trial>/trial-check.json. An
empty list means the trial passes. A failed check makes the trial a halt
(checks 1, 6, 7, 8) or an infrastructure failure (the others). A trial in
which the agent changes no file is a result, and it passes.

Check 8 compares the condition digests that the experiment log recorded for
the trial's job (at job-started and job-finished) with the plan-time digest
of the current invocation. The experiment gives them as ConditionDigests; a
single job folder outside an experiment has none, so check 8 is skipped and
says so.

The trials of one job must share one Claude Code version (check 6): `assay
trace-check` stops with an error when they do not.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from analyze.trial import REPO_ROOT, Trial, read_job
from instruments.digest import instruments_digest

APP = "/app"  # the seed repository in the container
SNAPSHOT_EXCLUDED = frozenset({".git", "node_modules"})  # the trace hook leaves these out
EDIT_TOOLS = ("Edit", "MultiEdit")
TRIAL_CHECK = "trial-check.json"
HALT = "halt"
INFRASTRUCTURE_FAILURE = "infrastructure-failure"
NOT_IN_AN_EXPERIMENT = ("not in an experiment: the condition digests come from the "
                        "experiment log")


class MixedClaudeCodeVersions(Exception):
    """The trials of one job ran more than one Claude Code version."""


@dataclass(frozen=True)
class ConditionDigests:
    """For check 8: the plan-time condition digest of the trial's agent (None
    for the control), and the digests the experiment log recorded for it at
    job-started and job-finished."""

    planned: str | None
    logged: tuple[str | None, ...]


@dataclass(frozen=True)
class Outcome:
    passed: bool | None  # None: skipped
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TrialCheck:
    trial: str
    checks: dict[str, Outcome]  # in CHECKS order

    @property
    def failed(self) -> list[str]:
        return [name for name, outcome in self.checks.items() if outcome.passed is False]

    @property
    def passed(self) -> bool:
        return not self.failed

    @property
    def failure_class(self) -> str | None:
        """halt when a halt check failed, else infrastructure-failure; None on a pass."""
        if not self.failed:
            return None
        return HALT if any(CHECKS[name].halt for name in self.failed) else INFRASTRUCTURE_FAILURE

    def to_json(self) -> dict:
        return {
            "trial": self.trial,
            "passed": self.passed,
            "failed_checks": self.failed,
            "class": self.failure_class,
            "checks": {name: {"passed": o.passed, **o.detail} for name, o in self.checks.items()},
        }


def validity_check(trial: Trial, condition: ConditionDigests | None = None) -> TrialCheck:
    """The outcome of each of the ten checks on the trial."""
    outcomes = {}
    for name, check in CHECKS.items():
        if check.run is _condition:
            outcomes[name] = _condition(condition)
        else:
            outcomes[name] = _outcome(check.run(trial))
    return TrialCheck(trial.name, outcomes)


def write_trial_check(result: TrialCheck, folder: Path) -> Path:
    """Writes trial-check.json in the trial's analysis folder."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / TRIAL_CHECK
    path.write_text(json.dumps(result.to_json(), indent=2) + "\n", encoding="utf-8")
    return path


def _outcome(value: bool | Outcome) -> Outcome:
    return value if isinstance(value, Outcome) else Outcome(value)


def _instruments(trial: Trial) -> bool:
    """1. The digest is the digest of the committed instruments/, and
    granularity and the overlap flag are declared."""
    return (trial.identity.instruments_digest == instruments_digest(REPO_ROOT / "instruments")
            and trial.granularity in ("per-tool-call", "per-turn")
            and isinstance(trial.calls_may_overlap, bool))


def _seed(trial: Trial) -> bool:
    """2. A seed line exists, and its commit is the first commit."""
    seeds = [line for line in trial.trace if line.event == "seed"]
    return bool(seeds) and seeds[0].commit is not None \
        and trial.root_commits() == [seeds[0].commit]


def _calls(trial: Trial) -> bool:
    """3. per-tool-call: each tool call, failed calls included, has exactly one
    line, by id. per-turn: each agent step has one line."""
    if trial.granularity == "per-turn":
        calls = [line for line in trial.trace if line.event == "call"]
        return len(calls) == trial.turns
    return all(len(trial.trace_lines_for(call.tool_use_id)) == 1 for call in trial.tool_calls)


def _errors(trial: Trial) -> bool:
    """4. No line has an error field (the recorder writes one only when it failed)."""
    return not any("error" in line.raw for line in trial.trace)


def _final(trial: Trial) -> bool:
    """5. A final line exists, it found no change, and its commit is the last commit."""
    finals = [line for line in trial.trace if line.event == "final"]
    return (len(finals) == 1 and finals[0].changed is False
            and finals[0].commit is not None and finals[0].commit == trial.head_commit())


def _harness_version(trial: Trial) -> bool:
    """6. The version that ran is the pinned version."""
    return trial.identity.version is not None \
        and trial.identity.version == trial.identity.pinned_version


def _harbor_version(trial: Trial) -> bool:
    """7. The Harbor version in instruments.json is the one in the committed uv.lock."""
    return trial.identity.harbor_version == locked_harbor_version()


def _condition(condition: ConditionDigests | None) -> Outcome:
    """8. The condition digests the experiment log recorded for the trial's job
    agree with the plan-time digest."""
    if condition is None:
        return Outcome(None, {"skipped": NOT_IN_AN_EXPERIMENT})
    agrees = bool(condition.logged) and all(d == condition.planned for d in condition.logged)
    return Outcome(agrees, {"planned": condition.planned, "logged": list(condition.logged)})


def _claimed_paths(trial: Trial) -> bool:
    """9. Each path in the arguments of a successful Write, Edit or MultiEdit
    on the seed repository is in the call's line, or (for a Write) the content
    did not change from the previous snapshot."""
    for call in trial.tool_calls:
        if call.function_name not in EDIT_TOOLS + ("Write",) or call.is_error is True:
            continue
        path = seed_path(call.arguments.get("file_path"))
        if path is None:
            continue
        lines = trial.trace_lines_for(call.tool_use_id)
        if not lines:
            return False  # no line to hold the path (check 3 also fails)
        line = lines[0]
        if any(change.path == path for change in line.paths):
            continue
        if call.function_name in EDIT_TOOLS:
            return False
        before = trial.snapshot_before(line)
        content = call.arguments.get("content")
        old = before and trial.snapshot_file(before.commit, path)
        if content is None or old != content.encode("utf-8"):
            return False
    return True


def _required_core(trial: Trial) -> Outcome:
    """10. The reader built every field of the required core."""
    missing = trial.missing_core()
    return Outcome(not missing, {"missing": missing} if missing else {})


def seed_path(file_path: str | None) -> str | None:
    """The path relative to the seed repository, or None when the snapshot
    does not cover it (outside /app, or in .git/ or node_modules/)."""
    if not file_path:
        return None
    pure = PurePosixPath(file_path)
    try:
        rel = pure.relative_to(APP)
    except ValueError:
        return None
    if not rel.parts or ".." in rel.parts or SNAPSHOT_EXCLUDED.intersection(rel.parts):
        return None
    return rel.as_posix()


def locked_harbor_version(uv_lock: Path = REPO_ROOT / "uv.lock") -> str | None:
    with uv_lock.open("rb") as f:
        packages = tomllib.load(f).get("package", [])
    return next((p.get("version") for p in packages if p.get("name") == "harbor"), None)


@dataclass(frozen=True)
class Check:
    run: Callable
    halt: bool  # a failure is a halt; otherwise an infrastructure failure


# The ten checks of PRD v3 section 8, in order.
CHECKS: dict[str, Check] = {
    "instruments": Check(_instruments, halt=True),
    "seed": Check(_seed, halt=False),
    "calls": Check(_calls, halt=False),
    "errors": Check(_errors, halt=False),
    "final": Check(_final, halt=False),
    "harness-version": Check(_harness_version, halt=True),
    "harbor-version": Check(_harbor_version, halt=True),
    "condition": Check(_condition, halt=True),
    "claimed-paths": Check(_claimed_paths, halt=False),
    "required-core": Check(_required_core, halt=False),
}


def job_claude_code_version(trials: Iterable[Trial]) -> str | None:
    """The one Claude Code version the trials of a job ran (ATIF agent.version).

    Raises MixedClaudeCodeVersions if they ran more than one. A trial with no
    version is left out here; check 6 fails it.
    """
    versions = sorted({t.identity.version for t in trials if t.identity.version is not None})
    if len(versions) > 1:
        raise MixedClaudeCodeVersions(
            f"the trials of one job ran more than one Claude Code version: {', '.join(versions)}"
        )
    return versions[0] if versions else None


def main(argv: list[str] | None = None) -> int:
    """Checks every trial folder of one job folder; exit 2 on mixed versions."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="assay trace-check",
        description="Run the validity check on each trial in a job folder.")
    parser.add_argument("job_dir", type=Path, help="results/<job-id>")
    parser.add_argument("--analysis", type=Path, default=REPO_ROOT / "analysis",
                        help="output root; trial-check.json goes to <analysis>/<job-id>/<trial>/")
    args = parser.parse_args(argv)
    trials = read_job(args.job_dir)
    try:
        job_claude_code_version(trials)
    except MixedClaudeCodeVersions as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for trial in trials:
        result = validity_check(trial)
        write_trial_check(result, args.analysis / args.job_dir.name / trial.name)
        print(json.dumps({"trial": trial.name, "failed_checks": result.failed}))
    return 0
