"""Builds fake Harbor trial folders for analyzer tests (spec #15, seam 1).

A trial folder has the layout Harbor 0.24.0 writes, with the Assay trace
folder under artifacts/logs/artifacts/trace/:

    <trial>/lock.json, result.json
    <trial>/agent/trajectory.json          ATIF
    <trial>/verifier/reward.json
    <trial>/artifacts/logs/artifacts/trace/trace.jsonl, trace.git/, instruments.json

The builder keeps a seed repository in a scratch folder and a real trace.git.
Each tool call can change files; the builder then makes a snapshot the way
the trace hook does (real git, own index, --no-renames) and appends the trace
line, joined to the ATIF tool call by tool_use_id.

    b = TrialBuilder(tmp_path, language="go")
    b.seed({"stopwatch.go": "package stopwatch\n"})
    step = b.step()
    step.call("Write", {"file_path": "/app/stopwatch_test.go"},
              files={"stopwatch_test.go": "package stopwatch\n"})
    trial_dir = b.build()
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

APP = "/app"


class StepBuilder:
    def __init__(self, trial: TrialBuilder, step: dict):
        self._trial = trial
        self._step = step

    @property
    def step_id(self) -> int:
        return self._step["step_id"]

    def call(
        self,
        function_name: str,
        arguments: dict | None = None,
        *,
        files: dict[str, str] | None = None,
        delete: list[str] | None = None,
        result: str | None = "ok",
        is_error: bool | None = False,
        trace: dict | None = None,
        traced: bool = True,
        tool_use_id: str | None = None,
    ) -> str:
        """Adds one tool call to this step and returns its tool_use_id.

        files/delete change the seed repository (paths relative to it) before
        the hook fires. trace overrides fields of the trace line; traced=False
        writes no trace line. result=None gives a call with no observation.
        """
        trial = self._trial
        tool_use_id = tool_use_id or trial._next_id()
        tool_call: dict[str, Any] = {
            "tool_call_id": tool_use_id,
            "function_name": function_name,
            "arguments": arguments or {},
        }
        self._step.setdefault("tool_calls", []).append(tool_call)
        if result is not None:
            observation: dict[str, Any] = {"source_call_id": tool_use_id, "content": result}
            if is_error is not None:
                observation["extra"] = {"tool_result_is_error": is_error}
            self._step.setdefault("observation", {"results": []})["results"].append(observation)

        trial._change(files or {}, delete or [])
        if traced:
            event = "PostToolUseFailure" if is_error else "PostToolUse"
            trial._fire(event, function_name, tool_use_id, trace or {})
        return tool_use_id


class TrialBuilder:
    def __init__(
        self,
        root: Path,
        *,
        language: str = "go",
        name: str = "split-second-stopwatch__abc1234",
        claude_code_version: str = "2.1.0",
    ):
        self.dir = Path(root) / name
        self.trace_dir = self.dir / "artifacts" / "logs" / "artifacts" / "trace"
        self.app = Path(root) / f"{name}-app"
        self.app.mkdir(parents=True)
        self.trace_dir.mkdir(parents=True)
        self._git_dir = self.trace_dir / "trace.git"
        self._lines: list[dict] = []
        self._ids = 0
        self.steps: list[dict] = [
            {"step_id": 1, "timestamp": _ts(1), "source": "user", "message": "Solve the task."}
        ]
        self.lock: dict[str, Any] = {
            "schema_version": 2,
            "task": {
                "name": "split-second-stopwatch",
                "type": "local",
                "path": f"tasks\\{language}\\split-second-stopwatch",
            },
            "agent": {
                "import_path": "instruments.agent:InstrumentedClaudeCode",
                "kwargs": {"version": claude_code_version},
            },
        }
        self.result: dict[str, Any] | None = {
            "trial_name": name,
            "task_name": "split-second-stopwatch",
            "verifier_result": None,
        }
        self.reward: dict[str, Any] | None = None
        self.instruments: dict[str, Any] | None = {"digest": "sha256:0", "harbor_version": "0.24.0"}
        self.agent_version = claude_code_version

    # --- building the history -------------------------------------------

    def seed(self, files: dict[str, str] | None = None, *, trace: dict | None = None) -> None:
        """Writes the seed repository and makes the seed fire."""
        self._change(files or {}, [])
        self._fire("seed", None, None, trace or {})

    def step(self, source: str = "agent") -> StepBuilder:
        step = {
            "step_id": len(self.steps) + 1,
            "timestamp": _ts(len(self.steps) + 1),
            "source": source,
            "message": "",
        }
        self.steps.append(step)
        return StepBuilder(self, step)

    def line(self, **fields: Any) -> None:
        """Appends a raw trace line, for cases the hook path does not give."""
        self._lines.append({"seq": len(self._lines), **fields})

    def build(self) -> Path:
        self._write("lock.json", self.lock)
        if self.result is not None:
            result = dict(self.result)
            if self.reward is not None:
                result["verifier_result"] = {"rewards": self.reward}
            self._write("result.json", result)
        if self.reward is not None:
            self._write("verifier/reward.json", self.reward)
        if self.instruments is not None:
            self._write("artifacts/logs/artifacts/trace/instruments.json", self.instruments)
        trajectory = {
            "schema_version": "ATIF-v1.7",
            "session_id": "session-1",
            "agent": {"name": "claude-code", "version": self.agent_version, "model_name": "m"},
            "steps": self.steps,
            "final_metrics": {"total_steps": len(self.steps)},
        }
        self._write("agent/trajectory.json", trajectory)
        (self.trace_dir / "trace.jsonl").write_text(
            "".join(json.dumps(line) + "\n" for line in self._lines), encoding="utf-8"
        )
        return self.dir

    # --- internals ---------------------------------------------------------

    def _next_id(self) -> str:
        self._ids += 1
        return f"toolu_{self._ids:04d}"

    def _write(self, rel: str, data: dict) -> None:
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _change(self, files: dict[str, str], delete: list[str]) -> None:
        for rel, content in files.items():
            path = self.app / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        for rel in delete:
            (self.app / rel).unlink()

    def _git(self, *args: str, input: str | None = None, check: bool = True) -> str:
        env = {
            **os.environ,
            "GIT_DIR": str(self._git_dir),
            "GIT_WORK_TREE": str(self.app),
            "GIT_INDEX_FILE": str(self._git_dir / "index"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "assay-trace",
            "GIT_AUTHOR_EMAIL": "trace@assay.invalid",
            "GIT_COMMITTER_NAME": "assay-trace",
            "GIT_COMMITTER_EMAIL": "trace@assay.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
        opts = ["-c", "safe.directory=*", "-c", "core.autocrlf=false", "-c", "core.fileMode=false"]
        return subprocess.run(
            ["git", *opts, *args], env=env, cwd=self.app, input=input,
            capture_output=True, text=True, check=check,
        ).stdout

    def _fire(self, event: str, tool_name: str | None, tool_use_id: str | None, override: dict) -> None:
        if not self._git_dir.exists():
            self._git("init", "-q")
        self._git("add", "-A", "-f", "--", ".")
        head = self._git("rev-parse", "-q", "--verify", "HEAD", check=False).strip()
        base = head or self._git("hash-object", "-t", "tree", os.devnull).strip()
        raw = self._git("diff", "--cached", "--name-status", "--no-renames", "-z", base)
        parts = [p for p in raw.split("\0") if p]
        paths = [{"status": parts[i], "path": parts[i + 1]} for i in range(0, len(parts), 2)]
        line: dict[str, Any] = {
            "seq": len(self._lines),
            "ts": _ts(len(self._lines)),
            "event": event,
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
        }
        if head and not paths:
            line["changed"] = False
        else:
            tree = self._git("write-tree").strip()
            parent = ["-p", head] if head else []
            commit = self._git(
                "commit-tree", tree, *parent, input=f"seq {line['seq']} {event}\n"
            ).strip()
            self._git("update-ref", "HEAD", commit)
            line["changed"] = True
            line["commit"] = commit
        line["paths"] = paths
        line.update(override)
        self._lines.append(line)


def _ts(n: int) -> str:
    return f"2026-01-01T00:{n // 60 % 60:02d}:{n % 60:02d}.000Z"
