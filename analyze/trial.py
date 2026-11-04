"""The Claude Code reader: builds the trial record of one Harbor trial folder
(PRD v3 section 8, ADR 0005).

No other analyzer module parses Harbor's layout. The folder holds:

    lock.json, result.json                  TrialLock, TrialResult
    agent/trajectory.json                   ATIF
    verifier/reward.json                    written by the task pack's test.sh
    artifacts/logs/artifacts/trace/         the recorder's trace folder:
        trace.jsonl, trace.git/, instruments.json

The record is a view, built in memory; Assay writes no copy of it. It holds
the steps with their tool calls, the history (the trace lines and trace.git)
joined to the calls, the totals and the identity: the required core, which
`Trial.missing_core()` checks. An optional part (a call's result, error flag,
exit code and duration, and a step's cost) is given or is ABSENT, never
guessed.

A missing file reads as None (or an empty list), so the validity check can
report it instead of the reader failing.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACE_FOLDER = Path("artifacts", "logs", "artifacts", "trace")

# The kind of each Claude Code tool (PRD v3 section 8, "The record"). There is
# no edit kind: file writes come from the history only.
SHELL_TOOLS = ("Bash",)
WEB_TOOLS = ("WebFetch", "WebSearch")
SKILL_TOOLS = ("Skill",)
# A failed Bash call's content starts with "Exit code N"; a call that passes
# has no exit code field.
_EXIT_CODE = re.compile(r"Exit code (\d+)")


# The optional parts of the record (assay.evaluation.OPTIONAL_PARTS) that this
# reader gives. Claude Code's ATIF never gives a call's duration or a step's
# cost, so an evaluation that needs one cannot be fed by the claude-code
# harness.
GIVES = frozenset({"result", "error_flag", "exit_code"})


class Absent:
    """The mark of an optional part that the reader cannot give. Falsy."""

    _instance: Absent | None = None

    def __new__(cls) -> Absent:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "ABSENT"


ABSENT = Absent()


@dataclass(frozen=True)
class ToolCall:
    """One ATIF tool call, with its observation joined by tool_use_id."""

    step_id: int
    position: int  # index in the step's tool_calls array
    tool_use_id: str
    function_name: str  # verbatim
    arguments: dict  # verbatim
    result: str | Absent  # observation content
    is_error: bool | Absent  # extra.tool_result_is_error
    exit_code: int | Absent = ABSENT  # from "Exit code N" of a failed call
    duration_sec: float | Absent = ABSENT  # Claude Code's ATIF never gives it

    @property
    def name(self) -> str:
        return self.function_name

    @property
    def kind(self) -> str:
        """shell, web, skill or other."""
        if self.function_name in SHELL_TOOLS:
            return "shell"
        if self.function_name in WEB_TOOLS:
            return "web"
        if self.function_name in SKILL_TOOLS:
            return "skill"
        return "other"

    @property
    def command(self) -> str | None:
        """The command of a shell call; None for any other kind."""
        command = self.arguments.get("command")
        return command if self.kind == "shell" and isinstance(command, str) else None


@dataclass(frozen=True)
class Step:
    """One ATIF step. Tokens are None when the step has no metrics (a user
    or system step); the cost is ABSENT when the harness does not give it."""

    step_id: int
    source: str | None  # agent, user or system
    timestamp: str | None
    input_tokens: int | None
    cached_tokens: int | None
    output_tokens: int | None
    cost_usd: float | Absent
    tool_calls: tuple[ToolCall, ...]


@dataclass(frozen=True)
class PathChange:
    status: str  # "A", "M" or "D"
    path: str  # relative to the seed repository


@dataclass(frozen=True)
class TraceLine:
    seq: int
    event: str | None  # "seed", "call" or "final"
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
class Totals:
    input_tokens: int | None
    cached_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    duration_sec: float | None


@dataclass(frozen=True)
class Identity:
    harness: str | None  # ATIF agent.name: the harness that ran
    pinned_version: str | None  # lock.json agent.kwargs.version
    version: str | None  # ATIF agent.version: the version that ran
    model_tier: str | None  # lock.json agent.model_name
    task_pack: str | None  # lock.json task.path, with / separators
    task_pack_digest: str | None  # lock.json task.digest
    # A digest of the part digests Harbor locked (skills, extra instructions,
    # agent kwargs other than the version, MCP servers); "" for the control.
    # It is not the plan-time condition digest: check 8 reads that from the
    # experiment log.
    variant_digest: str | None
    instruments_digest: str | None
    harbor_version: str | None


@dataclass(frozen=True)
class Trial:
    path: Path
    name: str
    task_path: tuple[str, ...]  # lock.json task.path: tasks/<language>/<slug>
    steps: tuple[Step, ...]  # in ATIF order
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
    identity: Identity
    reward: dict | None
    instruments: dict | None
    trace: tuple[TraceLine, ...]
    trace_git: Path

    @property
    def language(self) -> str | None:
        return self.task_path[-2] if len(self.task_path) >= 2 else None

    @property
    def granularity(self) -> str | None:
        """per-tool-call or per-turn, as instruments.json declares it."""
        return (self.instruments or {}).get("granularity")

    @property
    def calls_may_overlap(self) -> bool | None:
        """Whether the tool calls of one step can run in parallel."""
        return (self.instruments or {}).get("calls_may_overlap")

    @property
    def totals(self) -> Totals:
        u = self.usage
        return Totals(u.input_tokens, u.cache_tokens, u.output_tokens, u.cost_usd,
                      self.duration_sec)

    def history_for(self, call: ToolCall) -> list[TraceLine]:
        """The trace lines of a tool call: exactly one for a sound per-tool-call trace."""
        return self.trace_lines_for(call.tool_use_id)

    def trace_lines_for(self, tool_use_id: str) -> list[TraceLine]:
        return [line for line in self.trace if line.tool_use_id == tool_use_id]

    def missing_core(self) -> list[str]:
        """The required-core fields the reader could not build; empty when complete."""
        missing = []
        if not self.steps:
            missing.append("steps")
        for i, call in enumerate(self.tool_calls):
            if not call.tool_use_id:
                missing.append(f"tool_calls[{i}].id")
            if not call.function_name:
                missing.append(f"tool_calls[{i}].name")
        if not self.trace:
            missing.append("history.trace")
        if self.granularity is None:
            missing.append("history.granularity")
        if self.calls_may_overlap is None:
            missing.append("history.calls_may_overlap")
        for part, record in (("totals", self.totals), ("identity", self.identity)):
            missing += [f"{part}.{f.name}" for f in fields(record)
                        if getattr(record, f.name) is None]
        return missing

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

    def root_commits(self) -> list[str]:
        """The commits of trace.git with no parent: one, the seed, when sound."""
        done = subprocess.run(
            ["git", "-c", "safe.directory=*", "--git-dir", str(self.trace_git),
             "rev-list", "--max-parents=0", "HEAD"],
            capture_output=True, text=True,
        )
        return done.stdout.split() if done.returncode == 0 else []

    def head_commit(self) -> str | None:
        """The last commit of trace.git."""
        done = subprocess.run(
            ["git", "-c", "safe.directory=*", "--git-dir", str(self.trace_git),
             "rev-parse", "-q", "--verify", "HEAD"],
            capture_output=True, text=True,
        )
        return done.stdout.strip() if done.returncode == 0 else None


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
    raw_steps = sorted(trajectory.get("steps", []), key=lambda s: s["step_id"])
    steps = tuple(_step(s) for s in raw_steps)
    agent_steps = [s for s in raw_steps if s.get("source") == "agent"]
    task = lock.get("task") or {}
    # Harbor keeps host separators, so a Windows path uses backslashes.
    task_path = PureWindowsPath(task["path"]).parts if task.get("path") else ()
    trace_dir = path / TRACE_FOLDER
    instruments = read_json(trace_dir / "instruments.json")
    ran = trajectory.get("agent") or {}
    pinned = (agent.get("kwargs") or {}).get("version")
    return Trial(
        path=path,
        name=path.name,
        task_path=task_path,
        steps=steps,
        tool_calls=tuple(call for step in steps for call in step.tool_calls),
        turns=len(agent_steps),
        system_step_ids=tuple(s["step_id"] for s in raw_steps if s.get("source") == "system"),
        cached_tokens=tuple((s.get("metrics") or {}).get("cached_tokens") for s in agent_steps),
        agent_version=ran.get("version"),
        requested_version=pinned,
        model_tier=agent.get("model_name"),
        local="ANTHROPIC_BASE_URL" in (agent.get("env") or {}),
        usage=Usage(usage.get("cost_usd"), usage.get("n_input_tokens"),
                    usage.get("n_cache_tokens"), usage.get("n_output_tokens")),
        duration_sec=_seconds(result.get("started_at"), result.get("finished_at")),
        identity=Identity(
            harness=ran.get("name"),
            pinned_version=pinned,
            version=ran.get("version"),
            model_tier=agent.get("model_name"),
            task_pack="/".join(task_path) if task_path else None,
            task_pack_digest=task.get("digest"),
            variant_digest=_variant_digest(lock) if lock else None,
            instruments_digest=(instruments or {}).get("digest"),
            harbor_version=(instruments or {}).get("harbor_version"),
        ),
        reward=read_json(path / "verifier" / "reward.json"),
        instruments=instruments,
        trace=tuple(_trace_line(raw) for raw in read_jsonl(trace_dir / "trace.jsonl")),
        trace_git=trace_dir / "trace.git",
    )


def record_digest(path: Path | str) -> str:
    """The resume digest of a trial record: `sha256:<hex>` over the files the
    reader reads, each by its path in the trial folder and its content."""
    path = Path(path)
    trace_dir = path / TRACE_FOLDER
    files = [path / "lock.json", path / "result.json", path / "agent" / "trajectory.json",
             path / "verifier" / "reward.json", trace_dir / "instruments.json",
             trace_dir / "trace.jsonl",
             *(sorted((trace_dir / "trace.git").rglob("*")) if (trace_dir / "trace.git").is_dir()
               else [])]
    outer = hashlib.sha256()
    for file in files:
        if file.is_file():
            content = hashlib.sha256(file.read_bytes()).hexdigest()
            outer.update(f"{file.relative_to(path).as_posix()}\0{content}\n".encode("utf-8"))
    return f"sha256:{outer.hexdigest()}"


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


def _variant_digest(lock: dict) -> str:
    """A digest of the variant parts Harbor locked; "" when there are none."""
    agent = lock.get("agent") or {}
    kwargs = {k: v for k, v in (agent.get("kwargs") or {}).items() if k != "version"}
    parts = {
        "skills": sorted(s.get("digest") or "" for s in lock.get("skills") or []),
        "extra_instructions": sorted(e.get("digest") or ""
                                     for e in lock.get("extra_instructions") or []),
        "kwargs": kwargs,
        "mcp_servers": agent.get("mcp_servers") or [],
    }
    if not any(parts.values()):
        return ""
    text = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _step(step: dict) -> Step:
    metrics = step.get("metrics")
    return Step(
        step_id=step["step_id"],
        source=step.get("source"),
        timestamp=step.get("timestamp"),
        input_tokens=None if metrics is None else metrics.get("prompt_tokens"),
        cached_tokens=None if metrics is None else metrics.get("cached_tokens"),
        output_tokens=None if metrics is None else metrics.get("completion_tokens"),
        cost_usd=(metrics or {}).get("cost_usd", ABSENT),
        tool_calls=tuple(_tool_calls(step)),
    )


def _tool_calls(step: dict):
    results = {
        r.get("source_call_id"): r
        for r in (step.get("observation") or {}).get("results", [])
    }
    for position, call in enumerate(step.get("tool_calls") or []):
        result = results.get(call["tool_call_id"])
        content = ABSENT if result is None else result.get("content", ABSENT)
        is_error = ABSENT if result is None \
            else (result.get("extra") or {}).get("tool_result_is_error", ABSENT)
        if is_error is None:
            is_error = ABSENT
        found = _EXIT_CODE.match(content) if is_error is True and isinstance(content, str) \
            else None
        yield ToolCall(
            step_id=step["step_id"],
            position=position,
            tool_use_id=call["tool_call_id"],
            function_name=call["function_name"],
            arguments=call.get("arguments") or {},
            result=content,
            is_error=is_error,
            exit_code=int(found[1]) if found else ABSENT,
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
