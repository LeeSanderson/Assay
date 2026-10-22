"""Snapshot replay: the test state of each snapshot in a trial's trace.git.

PRD section 5, "Replay of the trace snapshots". For each snapshot, the task
pack's unchanged test.sh runs in a fresh container from the pack's image,
with no network and the verifier timeout. The agent-pass fields of the
reward.json it writes give the test state.

The PRD pins the replay image by digest. Harbor deletes each trial's task
image, so replay cannot run that exact image: it rebuilds it from the
pack's Dockerfile, whose base image is pinned by digest, and records both
the rebuilt image ID and that base image in replay-works.json.

    uv run assay replay results/<job-id>
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import time
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from analyze.trial import REPO_ROOT, Trial, read_job, read_jsonl, write_jsonl

REPLAY_FILE = "replay.jsonl"

NO_TESTS = "no-tests"
RED_COMPILE = "red-compile"
FAIL = "fail"
PASS = "pass"
AGENT_PASS_FIELDS = ("agent_tests_compile", "agent_tests_passed", "agent_tests_total")


class RunnerError(Exception):
    """A replay failure: a timeout, or an error of the container or the infrastructure."""


class Runner(Protocol):
    def run(self, image: str, snapshot: Path, timeout: float) -> dict:
        """Runs test.sh on the snapshot tree in a fresh container from the image.

        Returns the fields of the reward.json that test.sh writes. Raises
        RunnerError on a timeout or a container error.
        """
        ...

    def image(self, pack: Path) -> str:
        """The image of a task pack (its folder), ready to run."""
        ...


class DockerRunner:
    """The real runner: `docker run --network none` on the laptop host.

    Harbor deletes the task image after each trial, so image() builds it
    again from the pack's Dockerfile (whose base image is pinned by digest),
    and adds the pack's tests/ at /tests, where Harbor uploads them for the
    verifier. A built image is kept and reused, tagged by a hash of the
    pack's environment/ and tests/ folders.
    """

    def image(self, pack: Path) -> str:
        name = f"{pack.parent.name}-{pack.name}:{_folder_hash(pack)}"
        tag = f"assay-replay-{name}"
        found = _docker("image", "inspect", "--format", "{{.Id}}", tag)
        if found.returncode == 0:
            return found.stdout.strip()
        task_tag = f"assay-task-{name}"
        task = _docker("build", "-q", "-t", task_tag, str(pack / "environment"), timeout=3600)
        if task.returncode != 0:
            raise RunnerError(f"docker build of {pack / 'environment'} failed: {task.stderr}")
        dockerfile = f"FROM {task_tag}\nCOPY tests/ /tests/\n"
        replay = _docker("build", "-q", "-t", tag, "-f", "-", str(pack),
                         input=dockerfile, timeout=600)
        if replay.returncode != 0:
            raise RunnerError(f"docker build of the replay image failed: {replay.stderr}")
        return replay.stdout.strip()

    def run(self, image: str, snapshot: Path, timeout: float) -> dict:
        name = f"assay-replay-{uuid.uuid4().hex[:12]}"
        # /app becomes the snapshot. The trace leaves out .git/ and every
        # node_modules/ (Yarn's .yarn/unplugged/*/node_modules too), so the
        # image's own copies of those stay; any other file not in the
        # snapshot goes.
        script = (
            "set -e; cd /app; "
            "find . -path ./.git -prune -o -name node_modules -prune -o ! -type d -print0"
            " | while IFS= read -r -d '' f; do [ -e \"/snapshot/$f\" ] || rm -f -- \"$f\"; done; "
            "cp -a /snapshot/. /app/; set +e; "
            f"timeout {int(timeout)} bash /tests/test.sh >/dev/null 2>&1; "
            "if [ $? -eq 124 ]; then exit 124; fi; cat /logs/verifier/reward.json"
        )
        try:
            done = _docker(
                "run", "--rm", "--name", name, "--network", "none",
                "-v", f"{snapshot.resolve()}:/snapshot:ro", image, "bash", "-c", script,
                timeout=timeout + 120,
            )
        except subprocess.TimeoutExpired:
            _docker("rm", "-f", name)
            raise RunnerError(f"timeout after {timeout:g} s") from None
        if done.returncode == 124:
            raise RunnerError(f"timeout after {timeout:g} s")
        if done.returncode != 0:
            raise RunnerError(f"container exited {done.returncode}: {done.stderr.strip()}")
        try:
            return json.loads(done.stdout)
        except json.JSONDecodeError:
            raise RunnerError(f"reward.json is not JSON: {done.stdout.strip()!r}") from None


def _docker(*args: str, input: str | None = None, timeout: float | None = 120):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          input=input, timeout=timeout)


def _folder_hash(pack: Path) -> str:
    digest = hashlib.sha256()
    for folder in ("environment", "tests"):
        for path in sorted((pack / folder).rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(pack).as_posix().encode() + b"\0")
                digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]


def test_state(reward: dict) -> str:
    """The test state from the agent-pass fields; the first rule that is true wins."""
    if reward["agent_tests_total"] == 0:
        return NO_TESTS
    if reward["agent_tests_compile"] == 0:
        return RED_COMPILE
    if reward["agent_tests_passed"] < reward["agent_tests_total"]:
        return FAIL
    return PASS


def replay_trial(trial: Trial, runner: Runner, image: str, timeout: float) -> list[dict]:
    """One replay.jsonl line for each snapshot in the trial's trace, in seq order."""
    step_ids = {call.tool_use_id: call.step_id for call in trial.tool_calls}
    lines = []
    for trace_line in trial.trace:
        if not trace_line.commit:
            continue
        start = time.monotonic()
        fields: dict = {}
        state = error = None
        try:
            with tempfile.TemporaryDirectory(prefix="assay-snapshot-") as tmp:
                snapshot = Path(tmp)
                _export(trial.trace_git, trace_line.commit, snapshot)
                fields = runner.run(image, snapshot, timeout)
            missing = [f for f in AGENT_PASS_FIELDS if not isinstance(fields.get(f), (int, float))]
            if missing:
                raise RunnerError(f"reward.json lacks numeric {', '.join(missing)}")
            state = test_state(fields)
        except (RunnerError, subprocess.CalledProcessError) as exc:
            error = str(exc)
        line = {
            "seq": trace_line.seq,
            "commit": trace_line.commit,
            "tool_use_id": trace_line.tool_use_id,
            "step_id": step_ids.get(trace_line.tool_use_id),
            **(fields if error is None else {}),
            "test_state": state,
            "duration_sec": round(time.monotonic() - start, 3),
        }
        if error is not None:
            line["error"] = error
        lines.append(line)
    return lines


@dataclass(frozen=True)
class ReplayVerdict:
    works: bool
    causes: list[str]  # empty when replay works


def replay_works(trial: Trial, first: list[dict], second: list[dict]) -> ReplayVerdict:
    """Whether replay works on the trial, from two replay runs of it.

    1. Each snapshot gives a test state (a red-compile state is not a failure).
    2. The last snapshot's reward.json equals the verifier's, field for field.
    3. The two runs give the same test state and fields for each snapshot.
    """
    causes = []
    if not first:
        causes.append("the trace has no snapshots")
    for line in first:
        if line["test_state"] is None:
            causes.append(f"snapshot seq {line['seq']} gives no test state: {line.get('error')}")
    if trial.reward is None:
        causes.append("the trial has no verifier reward.json")
    elif first and first[-1]["test_state"] is not None:
        replayed = _reward_fields(first[-1])
        if replayed != trial.reward:
            diffs = [f"{k} {replayed.get(k)} != {trial.reward.get(k)}"
                     for k in sorted(set(replayed) | set(trial.reward))
                     if replayed.get(k) != trial.reward.get(k)]
            causes.append("last snapshot reward.json differs from the verifier's: "
                          + ", ".join(diffs))
    for a, b in zip(first, second):
        if _comparable(a) != _comparable(b):
            causes.append(f"the two runs differ at snapshot seq {a['seq']}")
    if len(first) != len(second):
        causes.append(f"the two runs give {len(first)} and {len(second)} snapshots")
    return ReplayVerdict(works=not causes, causes=causes)


_LINE_KEYS = ("seq", "commit", "tool_use_id", "step_id", "test_state", "duration_sec", "error")


def _reward_fields(line: dict) -> dict:
    return {k: v for k, v in line.items() if k not in _LINE_KEYS}


def _comparable(line: dict) -> dict:
    return {k: v for k, v in line.items() if k != "duration_sec"}


def replay_job(
    job_dir: Path | str, analysis_root: Path | str, runner: Runner,
    *, tasks_root: Path | str = REPO_ROOT,
) -> dict[str, ReplayVerdict]:
    """Replays each trial of a job two times and writes the results.

    For each trial it writes analysis/<job-id>/<trial>/replay.jsonl (the first
    run) and replay-works.json (the verdict). It never writes in job_dir.
    """
    job_dir = Path(job_dir)
    verdicts = {}
    for trial in read_job(job_dir):
        if not trial.task_path:
            raise ValueError(f"{trial.path}: lock.json gives no task path")
        pack = Path(tasks_root).joinpath(*trial.task_path)
        image = runner.image(pack)
        config = tomllib.loads((pack / "task.toml").read_text(encoding="utf-8"))
        timeout = float(config["verifier"]["timeout_sec"])
        first = replay_trial(trial, runner, image, timeout)
        second = replay_trial(trial, runner, image, timeout)
        verdict = replay_works(trial, first, second)
        out = Path(analysis_root) / job_dir.name / trial.name
        write_replay(out, first)
        # Provenance: the image replay ran, and the pack's base image pinned by digest.
        (out / "replay-works.json").write_text(json.dumps({
            "works": verdict.works, "causes": verdict.causes, "image": image,
            "base_image": config.get("metadata", {}).get("base_image"),
        }, indent=2) + "\n", encoding="utf-8")
        verdicts[trial.name] = verdict
    return verdicts


def write_replay(trial_out: Path, lines: list[dict]) -> Path:
    """Writes replay.jsonl into a trial's analysis folder."""
    trial_out.mkdir(parents=True, exist_ok=True)
    write_jsonl(trial_out / REPLAY_FILE, lines)
    return trial_out / REPLAY_FILE


def read_replay(trial_out: Path | str) -> list[dict]:
    """The lines of analysis/<job-id>/<trial>/replay.jsonl, in seq order.

    Each line: seq, commit, tool_use_id, step_id (None for the seed snapshot),
    the reward.json fields, test_state (None on a failure), duration_sec, and
    error on a failure only.
    """
    return read_jsonl(Path(trial_out) / REPLAY_FILE)


def _export(git_dir: Path, commit: str, target: Path) -> None:
    """Writes the tree of a trace.git snapshot into an empty folder."""
    archive = subprocess.run(
        ["git", "-c", "safe.directory=*", "-c", "core.autocrlf=false",
         "--git-dir", str(git_dir), "archive", "--format=tar", commit],
        capture_output=True, check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="data")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="assay replay",
        description="Replay the trace snapshots of each trial in a job folder.")
    parser.add_argument("job_dir", type=Path, help="results/<job-id>")
    parser.add_argument("--analysis", type=Path, default=REPO_ROOT / "analysis",
                        help="output root; files go to <analysis>/<job-id>/<trial>/")
    args = parser.parse_args(argv)
    verdicts = replay_job(args.job_dir, args.analysis, DockerRunner())
    for name, verdict in verdicts.items():
        print(f"{name}: replay {'works' if verdict.works else 'does not work'}")
        for cause in verdict.causes:
            print(f"  - {cause}")
    return 0 if all(v.works for v in verdicts.values()) else 1
