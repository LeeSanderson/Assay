"""Snapshot replay: the test state of each snapshot in a trial's trace.git,
as the built-in evaluation `replay` (PRD v3 sections 9 and 16).

For each snapshot, the task pack's unchanged test.sh runs in a fresh
container from the pack's image, with no network and the verifier timeout.
The agent-pass fields of the reward.json it writes give the test state.
Each trial is replayed two times; replay works when every snapshot gives a
test state, the last one equals the verifier, and the two runs agree.

The evaluation's value merges the verdict and the first run's snapshots:

    {"works", "causes", "image", "base_image", "snapshots": [one line per snapshot]}

and the verifier's log folder of each snapshot of the first run goes to
`out/<seq>/`. The task pack's content is the evaluation's task-pack input, so
a changed pack reruns it. The `final` snapshot that the recorder makes after
the harness exits is replayed only when it changed something; otherwise it
is the last call's snapshot again.

The PRD pins the replay image by digest. Harbor deletes each trial's task
image, so replay cannot run that exact image: `Containers.pack_image`
rebuilds it from the pack's Dockerfile, whose base image is pinned by
digest, and the value records both the rebuilt image ID and that base image.

    uv run assay replay results/<job-id>

is the thin entry point for one job folder: it writes today's files,
analysis/<job-id>/<trial>/replay.jsonl, replay-works.json and replay-logs/.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from analyze.trial import REPO_ROOT, Trial, read_job, read_jsonl, write_jsonl
from assay.evaluation import Containers, Evaluation, TrialInput

REPLAY_FILE = "replay.jsonl"
LOGS_FOLDER = "replay-logs"
WORKS_FILE = "replay-works.json"
# Seconds past test.sh's own timeout before the container is removed, so
# that the verifier's logs are written first.
GRACE_SEC = 120

NO_TESTS = "no-tests"
RED_COMPILE = "red-compile"
FAIL = "fail"
PASS = "pass"
AGENT_PASS_FIELDS = ("agent_tests_compile", "agent_tests_passed", "agent_tests_total")


class ReplayError(Exception):
    """A snapshot gives no test state: a timeout, or an error of the container."""


def test_state(reward: dict) -> str:
    """The test state from the agent-pass fields; the first rule that is true wins."""
    if reward["agent_tests_total"] == 0:
        return NO_TESTS
    if reward["agent_tests_compile"] == 0:
        return RED_COMPILE
    if reward["agent_tests_passed"] < reward["agent_tests_total"]:
        return FAIL
    return PASS


def run_test_sh(containers: Containers, image: str, snapshot: Path, timeout: float,
                logs: Path) -> dict:
    """Runs test.sh on the snapshot tree in a fresh container from the image,
    and returns the fields of the reward.json it writes. The verifier's log
    folder is `logs`, so each log lands there as it is written, also when the
    run then fails."""
    # /app becomes the snapshot. The trace leaves out .git/ and every
    # node_modules/ (Yarn's .yarn/unplugged/*/node_modules too), so the
    # image's own copies of those stay; any other file not in the snapshot
    # goes. test.sh's own output goes to test-stdout.txt, as Harbor's
    # verifier keeps it.
    script = (
        "set -e; cd /app; "
        "find . -path ./.git -prune -o -name node_modules -prune -o ! -type d -print0"
        " | while IFS= read -r -d '' f; do [ -e \"/snapshot/$f\" ] || rm -f -- \"$f\"; done; "
        "cp -a /snapshot/. /app/; set +e; "
        f"timeout {int(timeout)} bash /tests/test.sh >/logs/verifier/test-stdout.txt 2>&1; "
        "if [ $? -eq 124 ]; then exit 124; fi; cat /logs/verifier/reward.json"
    )
    done = containers.run(image, ["bash", "-c", script],
                          mounts={snapshot: "/snapshot:ro", logs: "/logs/verifier"},
                          network="none", timeout=timeout + GRACE_SEC)
    if done.exit_code is None or done.exit_code == 124:
        raise ReplayError(f"timeout after {timeout:g} s")
    if done.exit_code != 0:
        stderr = done.stderr.strip()
        raise ReplayError(f"container exited {done.exit_code}" + (f": {stderr}" if stderr else ""))
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        raise ReplayError(f"reward.json is not JSON: {done.stdout.strip()!r}") from None


def snapshots(trial: Trial):
    """The trace lines to replay: each with a commit, except a `final` line
    that changed nothing (it is the snapshot before it again)."""
    return [line for line in trial.trace
            if line.commit and not (line.event == "final" and line.changed is False)]


def replay_trial(
    trial: Trial, containers: Containers, image: str, timeout: float, logs: Path | None = None,
) -> list[dict]:
    """One line for each snapshot in the trial's trace, in seq order.

    With `logs`, each snapshot's verifier logs go to logs/<seq>/; without it
    they are thrown away.
    """
    step_ids = {call.tool_use_id: call.step_id for call in trial.tool_calls}
    lines = []
    for trace_line in snapshots(trial):
        start = time.monotonic()
        fields: dict = {}
        state = error = None
        try:
            with tempfile.TemporaryDirectory(prefix="assay-snapshot-") as tmp:
                snapshot = Path(tmp) / "snapshot"
                snapshot.mkdir()
                snapshot_logs = (logs / str(trace_line.seq)) if logs else Path(tmp) / "logs"
                snapshot_logs.mkdir(parents=True)
                _export(trial.trace_git, trace_line.commit, snapshot)
                fields = run_test_sh(containers, image, snapshot, timeout, snapshot_logs)
            missing = [f for f in AGENT_PASS_FIELDS if not isinstance(fields.get(f), (int, float))]
            if missing:
                raise ReplayError(f"reward.json lacks numeric {', '.join(missing)}")
            state = test_state(fields)
        except (ReplayError, subprocess.CalledProcessError) as exc:
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


def evaluate(inp: TrialInput) -> dict:
    """Replays the trial two times; the first run's verifier logs go to out/<seq>/."""
    pack = Path(inp.task_pack)
    config = tomllib.loads((pack / "task.toml").read_text(encoding="utf-8"))
    timeout = float(config["verifier"]["timeout_sec"])
    image = inp.containers.pack_image(pack)
    first = replay_trial(inp.record, inp.containers, image, timeout, inp.out)
    second = replay_trial(inp.record, inp.containers, image, timeout)
    verdict = replay_works(inp.record, first, second)
    # Provenance: the image replay ran, and the pack's base image pinned by digest.
    return {"works": verdict.works, "causes": verdict.causes, "image": image,
            "base_image": config.get("metadata", {}).get("base_image"), "snapshots": first}


# The base image is pinned by digest in the pack's Dockerfile, which the
# task-pack input covers; there is no other pin.
EVALUATION = Evaluation(name="replay", evaluate=evaluate)


def replay_job(
    job_dir: Path | str, analysis_root: Path | str, containers: Containers,
    *, tasks_root: Path | str = REPO_ROOT,
) -> dict[str, ReplayVerdict]:
    """`assay replay`: evaluates each trial of a job folder and writes the value
    as today's files.

    For each trial it writes analysis/<job-id>/<trial>/replay.jsonl (the first
    run), replay-logs/<seq>/ (the first run's verifier logs of each snapshot)
    and replay-works.json (the verdict). It never writes in job_dir.
    """
    job_dir = Path(job_dir)
    verdicts = {}
    for trial in read_job(job_dir):
        if not trial.task_path:
            raise ValueError(f"{trial.path}: lock.json gives no task path")
        out = Path(analysis_root) / job_dir.name / trial.name
        shutil.rmtree(out / LOGS_FOLDER, ignore_errors=True)
        (out / LOGS_FOLDER).mkdir(parents=True)
        value = evaluate(TrialInput(
            job=job_dir.name, trial=trial.name, cell=None,
            task_pack=Path(tasks_root).joinpath(*trial.task_path), record=trial, deps={},
            options={}, out=out / LOGS_FOLDER, containers=containers))
        write_replay(out, value["snapshots"])
        (out / WORKS_FILE).write_text(json.dumps(
            {k: v for k, v in value.items() if k != "snapshots"}, indent=2) + "\n",
            encoding="utf-8")
        verdicts[trial.name] = ReplayVerdict(value["works"], value["causes"])
    return verdicts


def write_replay(trial_out: Path, lines: list[dict]) -> Path:
    """Writes replay.jsonl into a trial's analysis folder."""
    trial_out.mkdir(parents=True, exist_ok=True)
    write_jsonl(trial_out / REPLAY_FILE, lines)
    return trial_out / REPLAY_FILE


def read_replay(trial_out: Path | str) -> list[dict]:
    """The lines of analysis/<job-id>/<trial>/replay.jsonl, in seq order.

    Each line: seq, commit, tool_use_id, step_id (None for the seed and final
    snapshots), the reward.json fields, test_state (None on a failure),
    duration_sec, and error on a failure only.
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


def main(argv: list[str] | None = None, containers: Containers | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="assay replay",
        description="Replay the trace snapshots of each trial in a job folder.")
    parser.add_argument("job_dir", type=Path, help="results/<job-id>")
    parser.add_argument("--analysis", type=Path, default=REPO_ROOT / "analysis",
                        help="output root; files go to <analysis>/<job-id>/<trial>/")
    args = parser.parse_args(argv)
    if containers is None:
        from assay.containers import DockerContainers

        containers = DockerContainers()
    verdicts = replay_job(args.job_dir, args.analysis, containers)
    for name, verdict in verdicts.items():
        print(f"{name}: replay {'works' if verdict.works else 'does not work'}")
        for cause in verdict.causes:
            print(f"  - {cause}")
    return 0 if all(v.works for v in verdicts.values()) else 1
