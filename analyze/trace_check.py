"""The trace check (PRD section 5, "The trace check").

    uv run python -m analyze.trace_check <job folder>

checks each trial of one job and prints one JSON line per trial with its
failed checks. An empty list means the trial passes. A trial that fails is a
failure of the infrastructure, and it runs again in the same cell.

The analyzer stops with an error if the trials of one job do not share one
Claude Code version (L1, "Version pins").
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from analyze.trial import Trial, read_job
from instruments.digest import instruments_digest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = "/app"  # the seed repository in the container
SNAPSHOT_EXCLUDED = frozenset({".git", "node_modules"})  # the trace hook leaves these out
EDIT_TOOLS = ("Edit", "MultiEdit")


class MixedClaudeCodeVersions(Exception):
    """The trials of one job ran more than one Claude Code version (L1)."""


def trace_check(trial: Trial) -> list[str]:
    """The names of the checks the trial fails, in CHECKS order. Empty means pass."""
    return [name for name, passes in CHECKS.items() if not passes(trial)]


def _instruments(trial: Trial) -> bool:
    """1. instruments.json exists, and its digest is the committed digest."""
    return (trial.instruments or {}).get("digest") == instruments_digest(REPO_ROOT / "instruments")


def _seed(trial: Trial) -> bool:
    """2. A seed line exists."""
    return any(line.event == "seed" for line in trial.trace)


def _tool_calls(trial: Trial) -> bool:
    """3. Each ATIF tool call has exactly one trace line, joined by tool_use_id."""
    return all(len(trial.trace_lines_for(call.tool_use_id)) == 1 for call in trial.tool_calls)


def _errors(trial: Trial) -> bool:
    """4. No line has an error field (the hook writes one only when it failed)."""
    return not any("error" in line.raw for line in trial.trace)


def _changed(trial: Trial) -> bool:
    """5. At least one line has changed set to true."""
    return any(line.changed is True for line in trial.trace)


def _claude_code_version(trial: Trial) -> bool:
    """6. The Claude Code that ran (ATIF agent.version) is the pinned kwargs.version."""
    return trial.agent_version is not None and trial.agent_version == trial.requested_version


def _harbor_version(trial: Trial) -> bool:
    """7. harbor_version in instruments.json is the Harbor version in the committed uv.lock."""
    return (trial.instruments or {}).get("harbor_version") == locked_harbor_version()


def _file_writes(trial: Trial) -> bool:
    """8. Each successful Edit or MultiEdit on a seed-repository path, and each
    successful Write that changed the file's content (compared with the
    previous snapshot), has that path in its trace line."""
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


# The eight checks of PRD section 5, in order: name -> passes(trial).
CHECKS = {
    "instruments": _instruments,
    "seed": _seed,
    "tool-calls": _tool_calls,
    "errors": _errors,
    "changed": _changed,
    "claude-code-version": _claude_code_version,
    "harbor-version": _harbor_version,
    "file-writes": _file_writes,
}


def job_claude_code_version(trials: Iterable[Trial]) -> str | None:
    """The one Claude Code version the trials of a job ran (ATIF agent.version).

    Raises MixedClaudeCodeVersions if they ran more than one. A trial with no
    version is left out here; check 6 fails it.
    """
    versions = sorted({t.agent_version for t in trials if t.agent_version is not None})
    if len(versions) > 1:
        raise MixedClaudeCodeVersions(
            f"the trials of one job ran more than one Claude Code version: {', '.join(versions)}"
        )
    return versions[0] if versions else None


def main(argv: list[str]) -> int:
    """Checks every trial folder of one job folder; exit 2 on mixed versions."""
    if len(argv) != 1:
        print("usage: python -m analyze.trace_check <job folder>", file=sys.stderr)
        return 2
    trials = read_job(argv[0])
    try:
        job_claude_code_version(trials)
    except MixedClaudeCodeVersions as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for trial in trials:
        print(json.dumps({"trial": trial.name, "failed_checks": trace_check(trial)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
