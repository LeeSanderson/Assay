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
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
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
    tool_use_id: str | None
    changed: bool | None
    commit: str | None
    paths: tuple[PathChange, ...]
    raw: dict


@dataclass(frozen=True)
class Usage:
    """result.json agent_result: Claude Code's token counts and total_cost_usd."""

    cost_usd: float | None
    input_tokens: int | None
    cache_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class Trial:
    path: Path
    name: str
    task_path: tuple[str, ...]  # lock.json task.path: tasks/<language>/<slug>
    tool_calls: tuple[ToolCall, ...]  # in ATIF order: step_id, then position
    turns: int  # ATIF steps whose source is the agent
    system_step_ids: tuple[int, ...]  # ATIF steps whose source is "system"
    cached_tokens: tuple[int | None, ...]  # metrics.cached_tokens of each agent step
    agent_version: str | None  # ATIF agent.version: the Claude Code that ran
    requested_version: str | None  # lock.json agent.kwargs.version: the pin
    model_tier: str | None  # lock.json agent.model_name
    local: bool  # the agent points at a local model server (L10)
    usage: Usage
    duration_sec: float | None  # result.json started_at to finished_at
    reward: dict | None
    instruments: dict | None
    trace: tuple[TraceLine, ...]
    trace_git: Path

    @property
    def language(self) -> str | None:
        return self.task_path[-2] if len(self.task_path) >= 2 else None

    def trace_lines_for(self, tool_use_id: str) -> list[TraceLine]:
        return [line for line in self.trace if line.tool_use_id == tool_use_id]

    def snapshot_before(self, line: TraceLine) -> TraceLine | None:
        """The last trace line with a snapshot (a commit) before this line, or None."""
        before = [l for l in self.trace if l.seq < line.seq and l.commit]
        return before[-1] if before else None

    def snapshot_file(self, commit: str, path: str) -> bytes | None:
        """A file's content in a snapshot of trace.git; None when it has no such file."""
        done = subprocess.run(
            ["git", "-c", "safe.directory=*", "--git-dir", str(self.trace_git),
             "cat-file", "blob", f"{commit}:{path}"],
            capture_output=True,
        )
        return done.stdout if done.returncode == 0 else None


def read_job(job_dir: Path | str) -> list[Trial]:
    """Each trial folder of a job (a folder with a lock.json), in name order."""
    return [read_trial(p) for p in sorted(Path(job_dir).iterdir()) if (p / "lock.json").is_file()]


def read_trial(path: Path | str) -> Trial:
    path = Path(path)
    trajectory = read_json(path / "agent" / "trajectory.json") or {}
    lock = read_json(path / "lock.json") or {}
    result = read_json(path / "result.json") or {}
    agent = lock.get("agent") or {}
    usage = result.get("agent_result") or {}
    steps = sorted(trajectory.get("steps", []), key=lambda s: s["step_id"])
    agent_steps = [s for s in steps if s.get("source") == "agent"]
    task_path = (lock.get("task") or {}).get("path")
    trace_dir = path / TRACE_FOLDER
    return Trial(
        path=path,
        name=path.name,
        # Harbor keeps host separators, so a Windows path uses backslashes.
        task_path=PureWindowsPath(task_path).parts if task_path else (),
        tool_calls=tuple(_tool_calls(steps)),
        turns=len(agent_steps),
        system_step_ids=tuple(s["step_id"] for s in steps if s.get("source") == "system"),
        cached_tokens=tuple((s.get("metrics") or {}).get("cached_tokens") for s in agent_steps),
        agent_version=(trajectory.get("agent") or {}).get("version"),
        requested_version=(agent.get("kwargs") or {}).get("version"),
        model_tier=agent.get("model_name"),
        local="ANTHROPIC_BASE_URL" in (agent.get("env") or {}),
        usage=Usage(usage.get("cost_usd"), usage.get("n_input_tokens"),
                    usage.get("n_cache_tokens"), usage.get("n_output_tokens")),
        duration_sec=_seconds(result.get("started_at"), result.get("finished_at")),
        reward=read_json(path / "verifier" / "reward.json"),
        instruments=read_json(trace_dir / "instruments.json"),
        trace=tuple(_trace_line(raw) for raw in read_jsonl(trace_dir / "trace.jsonl")),
        trace_git=trace_dir / "trace.git",
    )


def read_json(path: Path) -> Any:
    """A JSON file's content, or None when there is no such file."""
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def read_jsonl(path: Path) -> list[dict]:
    """The lines of a JSON-lines file; an empty list when there is no such file."""
    if not path.is_file():
        return []
    return [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines() if t.strip()]


def write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def share(part: float, whole: float) -> float | None:
    """part / whole, or None when whole is 0."""
    return part / whole if whole else None


def _seconds(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _tool_calls(steps: list[dict]):
    for step in steps:
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


def _trace_line(raw: dict) -> TraceLine:
    return TraceLine(
        seq=raw.get("seq"),
        event=raw.get("event"),
        tool_use_id=raw.get("tool_use_id"),
        changed=raw.get("changed"),
        commit=raw.get("commit"),
        paths=tuple(PathChange(p["status"], p["path"]) for p in raw.get("paths") or []),
        raw=raw,
    )
