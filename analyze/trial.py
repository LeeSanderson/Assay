"""The trial reader: loads one Harbor trial folder into plain data.

No other analyzer module parses Harbor's layout. The folder holds:

    lock.json, result.json                  TrialLock, TrialResult
    agent/trajectory.json                   ATIF
    verifier/reward.json                    written by the task pack's test.sh
    artifacts/logs/artifacts/trace/         the trace hook's output:
        trace.jsonl, trace.git/, instruments.json

A missing file reads as None (or an empty list), so the trace check can
report it instead of the reader failing.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

TRACE_FOLDER = Path("artifacts", "logs", "artifacts", "trace")


@dataclass(frozen=True)
class ToolCall:
    """One ATIF tool call, with its observation joined by tool_use_id."""

    step_id: int
    position: int  # index in the step's tool_calls array
    tool_use_id: str
    function_name: str
    arguments: dict
    result: str | None  # observation content; None when the call has no result
    is_error: bool | None  # extra.tool_result_is_error; None when not given


@dataclass(frozen=True)
class PathChange:
    status: str  # "A", "M" or "D"
    path: str  # relative to the seed repository


@dataclass(frozen=True)
class TraceLine:
    seq: int
    event: str | None  # "seed", "PostToolUse" or "PostToolUseFailure"
    tool_name: str | None
    tool_use_id: str | None
    changed: bool | None
    commit: str | None
    paths: tuple[PathChange, ...]
    error: str | None
    raw: dict


@dataclass(frozen=True)
class Trial:
    path: Path
    name: str
    language: str | None  # from the task path tasks/<language>/<slug>
    trajectory: dict | None  # the raw ATIF document
    tool_calls: tuple[ToolCall, ...]  # in ATIF order: step_id, then position
    last_step_id: int | None
    agent_version: str | None  # ATIF agent.version: the Claude Code that ran
    requested_version: str | None  # lock.json agent.kwargs.version: the pin
    lock: dict | None
    result: dict | None
    reward: dict | None
    instruments: dict | None
    trace: tuple[TraceLine, ...]
    trace_dir: Path  # holds trace.git

    @property
    def trace_git(self) -> Path:
        return self.trace_dir / "trace.git"

    def trace_lines_for(self, tool_use_id: str) -> list[TraceLine]:
        return [line for line in self.trace if line.tool_use_id == tool_use_id]

    def snapshot_before(self, line: TraceLine) -> str | None:
        """The commit of the last snapshot taken before this line, or None."""
        commits = [l.commit for l in self.trace if l.seq < line.seq and l.commit]
        return commits[-1] if commits else None

    def snapshot_file(self, commit: str, path: str) -> bytes | None:
        """A file's content in a snapshot of trace.git; None when it has no such file."""
        done = subprocess.run(
            ["git", "-c", "safe.directory=*", "--git-dir", str(self.trace_git),
             "cat-file", "blob", f"{commit}:{path}"],
            capture_output=True,
        )
        return done.stdout if done.returncode == 0 else None


def read_trial(path: Path | str) -> Trial:
    path = Path(path)
    trajectory = _json(path / "agent" / "trajectory.json")
    lock = _json(path / "lock.json")
    steps = (trajectory or {}).get("steps", [])
    trace_dir = path / TRACE_FOLDER
    return Trial(
        path=path,
        name=path.name,
        language=_language(lock),
        trajectory=trajectory,
        tool_calls=tuple(_tool_calls(steps)),
        last_step_id=max((s["step_id"] for s in steps), default=None),
        agent_version=((trajectory or {}).get("agent") or {}).get("version"),
        requested_version=(((lock or {}).get("agent") or {}).get("kwargs") or {}).get("version"),
        lock=lock,
        result=_json(path / "result.json"),
        reward=_json(path / "verifier" / "reward.json"),
        instruments=_json(trace_dir / "instruments.json"),
        trace=tuple(_trace(trace_dir / "trace.jsonl")),
        trace_dir=trace_dir,
    )


def _json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _language(lock: dict | None) -> str | None:
    task_path = ((lock or {}).get("task") or {}).get("path")
    if not task_path:
        return None
    # Harbor keeps host separators, so a Windows path uses backslashes.
    parts = PureWindowsPath(task_path).parts
    return parts[-2] if len(parts) >= 2 else None


def _tool_calls(steps: list[dict]):
    for step in sorted(steps, key=lambda s: s["step_id"]):
        results = {
            r.get("source_call_id"): r
            for r in (step.get("observation") or {}).get("results", [])
        }
        for position, call in enumerate(step.get("tool_calls") or []):
            result = results.get(call["tool_call_id"])
            yield ToolCall(
                step_id=step["step_id"],
                position=position,
                tool_use_id=call["tool_call_id"],
                function_name=call["function_name"],
                arguments=call.get("arguments") or {},
                result=None if result is None else result.get("content"),
                is_error=None if result is None
                else (result.get("extra") or {}).get("tool_result_is_error"),
            )


def _trace(path: Path):
    if not path.is_file():
        return
    for text in path.read_text(encoding="utf-8").splitlines():
        if not text.strip():
            continue
        raw = json.loads(text)
        yield TraceLine(
            seq=raw.get("seq"),
            event=raw.get("event"),
            tool_name=raw.get("tool_name"),
            tool_use_id=raw.get("tool_use_id"),
            changed=raw.get("changed"),
            commit=raw.get("commit"),
            paths=tuple(PathChange(p["status"], p["path"]) for p in raw.get("paths") or []),
            error=raw.get("error"),
            raw=raw,
        )
