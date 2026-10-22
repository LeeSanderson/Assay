"""Snapshot replay (`analyze/replay.py`), spec #15 seam 2.

The fake runner stands in for Docker. Like the real `test.sh`, its result
depends only on the snapshot it gets: it reads `fake-verifier.json` from the
exported snapshot tree, so each test sets the result of a snapshot by writing
that file in the trial's history. One slow test runs the real Docker runner.
"""

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from analyze.replay import (
    DockerRunner, RunnerError, read_replay, replay_job, replay_trial, replay_works,
)
from analyze.trial import read_trial
from tests.trial_builder import REPLAY_REWARDS, TrialBuilder

REPO_ROOT = Path(__file__).resolve().parents[1]

FAKE = "fake-verifier.json"
IMAGE = "sha256:" + "a" * 64


def reward(compile=1, passed=0, total=0, **over) -> dict:
    fields = {
        "reward": 0, "reference_compiles": 1, "reference_passed": 0, "reference_total": 29,
        "agent_tests_compile": compile, "agent_tests_passed": passed, "agent_tests_total": total,
    }
    fields.update(over)
    return fields


def gives(fields: dict) -> dict[str, str]:
    return {FAKE: json.dumps({"reward": fields})}


def fails(message: str) -> dict[str, str]:
    return {FAKE: json.dumps({"error": message})}


class FakeRunner:
    def __init__(self):
        self.calls: list[tuple[str, float]] = []

    def run(self, image: str, snapshot: Path, timeout: float) -> dict:
        self.calls.append((image, timeout))
        spec = json.loads((snapshot / FAKE).read_text(encoding="utf-8"))
        if "error" in spec:
            raise RunnerError(spec["error"])
        return spec["reward"]


def states(lines) -> list[str | None]:
    return [line["test_state"] for line in lines]


@pytest.mark.parametrize("fields, state", [
    (reward(compile=0, passed=0, total=0), "no-tests"),  # no-tests comes before red-compile
    (reward(compile=1, passed=0, total=0), "no-tests"),
    (reward(compile=0, passed=0, total=3), "red-compile"),  # red-compile comes before fail
    (reward(compile=0, passed=3, total=3), "red-compile"),
    (reward(compile=1, passed=2, total=3), "fail"),
    (reward(compile=1, passed=3, total=3), "pass"),
])
def test_test_state_follows_the_prd_rules_in_order(make_trial, fields, state):
    b = make_trial()
    b.seed(gives(fields))
    lines = replay_trial(read_trial(b.build()), FakeRunner(), IMAGE, 600)
    assert states(lines) == [state]


def test_each_snapshot_gives_one_line_with_its_call_and_all_reward_fields(make_trial):
    b = make_trial()
    b.seed(gives(reward()))
    step = b.step()
    write = step.call("Write", {"file_path": "/app/x_test.go"},
                      files=gives(reward(compile=1, passed=1, total=2)))
    step.call("Read", {"file_path": "/app/x_test.go"})  # changes nothing: no snapshot
    later = b.step()
    bash = later.call("Bash", {"command": "go test"}, files=gives(reward(passed=2, total=2)))
    trial = read_trial(b.build())
    runner = FakeRunner()

    lines = replay_trial(trial, runner, IMAGE, 600)

    commits = [l.commit for l in trial.trace if l.commit]
    assert len(lines) == 3
    assert [(l["seq"], l["commit"], l["tool_use_id"], l["step_id"]) for l in lines] == [
        (0, commits[0], None, None),
        (1, commits[1], write, step.step_id),
        (3, commits[2], bash, later.step_id),
    ]
    assert {k: lines[1][k] for k in reward()} == reward(compile=1, passed=1, total=2)
    assert states(lines) == ["no-tests", "fail", "pass"]
    assert all(isinstance(l["duration_sec"], float) and l["duration_sec"] >= 0 for l in lines)
    assert all("error" not in l for l in lines)
    assert runner.calls == [(IMAGE, 600)] * 3


def test_reward_fields_beyond_the_seven_are_kept(make_trial):
    b = make_trial()
    b.seed(gives(reward(extra_field=7)))
    [line] = replay_trial(read_trial(b.build()), FakeRunner(), IMAGE, 600)
    assert line["extra_field"] == 7


def test_a_runner_timeout_or_container_error_is_a_failed_line_and_replay_goes_on(make_trial):
    b = make_trial()
    b.seed(fails("timeout after 600 s"))
    b.step().call("Write", files=fails("container exited 125"))
    b.step().call("Write", files=gives(reward(compile=0, passed=0, total=1)))

    lines = replay_trial(read_trial(b.build()), FakeRunner(), IMAGE, 600)

    assert [l.get("error") for l in lines] == ["timeout after 600 s", "container exited 125", None]
    assert states(lines) == [None, None, "red-compile"]
    assert "agent_tests_total" not in lines[0]
    assert "error" not in lines[2]  # red-compile is a test state, not a failure


def test_a_reward_without_the_agent_pass_fields_is_a_failed_line(make_trial):
    b = make_trial()
    b.seed(gives({"reward": 1}))
    [line] = replay_trial(read_trial(b.build()), FakeRunner(), IMAGE, 600)
    assert line["test_state"] is None
    assert "agent_tests_total" in line["error"]


# --- Replay works -----------------------------------------------------------

FINAL = reward(compile=1, passed=2, total=2, reward=1, reference_passed=29)


def _trial_with_two_snapshots(make_trial, *, last=None, verifier=FINAL):
    b = make_trial()
    b.seed(gives(reward()))
    b.step().call("Write", files=last or gives(FINAL))
    b.reward = verifier
    return read_trial(b.build())


def _twice(trial, runner=None):
    runner = runner or FakeRunner()
    return replay_trial(trial, runner, IMAGE, 600), replay_trial(trial, runner, IMAGE, 600)


def test_replay_works_when_all_three_conditions_hold(make_trial):
    trial = _trial_with_two_snapshots(make_trial)
    verdict = replay_works(trial, *_twice(trial))
    assert verdict.works
    assert verdict.causes == []


def test_a_failed_snapshot_means_replay_does_not_work(make_trial):
    b = make_trial()
    b.seed(fails("container exited 125"))
    b.step().call("Write", files=gives(FINAL))
    b.reward = FINAL
    trial = read_trial(b.build())
    verdict = replay_works(trial, *_twice(trial))
    assert not verdict.works
    assert verdict.causes == ["snapshot seq 0 gives no test state: container exited 125"]


def test_a_red_compile_snapshot_still_works(make_trial):
    b = make_trial()
    b.seed(gives(reward(compile=0, total=1)))
    b.step().call("Write", files=gives(FINAL))
    b.reward = FINAL
    trial = read_trial(b.build())
    assert replay_works(trial, *_twice(trial)).works


def test_the_last_snapshot_must_equal_the_verifier_field_for_field(make_trial):
    trial = _trial_with_two_snapshots(make_trial, verifier={**FINAL, "reference_passed": 28})
    verdict = replay_works(trial, *_twice(trial))
    assert not verdict.works
    assert verdict.causes == [
        "last snapshot reward.json differs from the verifier's: reference_passed 29 != 28"]


def test_a_missing_verifier_reward_means_replay_does_not_work(make_trial):
    trial = _trial_with_two_snapshots(make_trial, verifier=None)
    verdict = replay_works(trial, *_twice(trial))
    assert not verdict.works
    assert verdict.causes == ["the trial has no verifier reward.json"]


def test_a_trial_with_no_snapshots_does_not_work(make_trial):
    b = make_trial()
    b.line(event="seed", changed=True, error="git failed")  # a seed fire with no commit
    b.reward = FINAL
    trial = read_trial(b.build())
    verdict = replay_works(trial, *_twice(trial))
    assert not verdict.works
    assert verdict.causes == ["the trace has no snapshots"]


class FlakyRunner(FakeRunner):
    """Gives one more passing agent test on every odd call: the seed snapshot."""

    def run(self, image, snapshot, timeout):
        fields = dict(super().run(image, snapshot, timeout))
        if len(self.calls) % 2 == 1:
            fields["agent_tests_passed"] += 1
            fields["agent_tests_total"] += 1
        return fields


def test_two_runs_must_give_the_same_state_and_fields_for_each_snapshot(make_trial):
    b = make_trial()
    b.seed(gives(reward()))
    b.step().call("Write", files=gives(FINAL))
    b.reward = FINAL
    trial = read_trial(b.build())
    runner = FlakyRunner()
    first = replay_trial(trial, runner, IMAGE, 600)  # calls 1, 2: seq 0 gets +1
    second = replay_trial(trial, runner, IMAGE, 600)  # calls 3, 4: seq 0 gets +1 again
    assert replay_works(trial, first, second).works  # durations differ; nothing else

    third = replay_trial(trial, FakeRunner(), IMAGE, 600)
    verdict = replay_works(trial, first, third)
    assert not verdict.works
    assert verdict.causes == ["the two runs differ at snapshot seq 0"]


# --- A job: the files under analysis/ ------------------------------------------


class PackRunner(FakeRunner):
    """Builds no image: the image name is the pack folder's path."""

    def __init__(self):
        super().__init__()
        self.packs: list[Path] = []

    def image(self, pack: Path) -> str:
        self.packs.append(pack)
        return f"image-of:{pack.as_posix()}"


def _fake_pack(root: Path, timeout: float) -> Path:
    pack = root / "tasks" / "go" / "split-second-stopwatch"
    pack.mkdir(parents=True)
    (pack / "task.toml").write_text(f"[verifier]\ntimeout_sec = {timeout}\n", encoding="utf-8")
    return pack


def test_replay_job_writes_replay_jsonl_and_the_verdict_under_analysis_only(tmp_path):
    pack = _fake_pack(tmp_path / "repo", 42.0)
    job = tmp_path / "results" / "job-7"
    good = TrialBuilder(job, name="good__a")
    good.seed(gives(reward()))
    good.step().call("Write", files=gives(FINAL))
    good.reward = FINAL
    good.build()
    bad = TrialBuilder(job, name="bad__b")
    bad.seed(fails("timeout after 42 s"))
    bad.reward = FINAL
    bad.build()
    (job / "lock.json").write_text("{}", encoding="utf-8")  # the job's own files
    before = sorted(p for p in (tmp_path / "results").rglob("*"))
    runner = PackRunner()

    verdicts = replay_job(job, tmp_path / "analysis", runner, tasks_root=tmp_path / "repo")

    assert sorted(p for p in (tmp_path / "results").rglob("*")) == before
    assert {name: v.works for name, v in verdicts.items()} == {"good__a": True, "bad__b": False}
    out = tmp_path / "analysis" / "job-7"
    good_lines = read_replay(out / "good__a")
    assert states(good_lines) == ["no-tests", "pass"]
    assert read_replay(out / "bad__b")[0]["error"] == "timeout after 42 s"
    assert json.loads((out / "good__a" / "replay-works.json").read_text(encoding="utf-8")) == {
        "works": True, "causes": []}
    assert json.loads((out / "bad__b" / "replay-works.json").read_text(encoding="utf-8"))[
        "works"] is False
    # Each trial runs twice, with the pack's image and its verifier timeout.
    assert len(runner.calls) == 2 * (2 + 1)
    assert set(runner.calls) == {(f"image-of:{pack.as_posix()}", 42.0)}
    assert set(runner.packs) == {pack}


def test_the_builders_replay_jsonl_matches_what_replay_writes(make_trial):
    b = make_trial()
    b.seed(gives(REPLAY_REWARDS["no-tests"]))
    step = b.step()
    red = step.call("Write", files=gives(REPLAY_REWARDS["red-compile"]))
    failing = step.call("Write", files=gives(REPLAY_REWARDS["fail"]))
    passing = b.step().call("Bash", files=gives(REPLAY_REWARDS["pass"]))
    trial = read_trial(b.build())
    out = b.write_replay({red: "red-compile", failing: "fail", passing: "pass"})

    replayed = replay_trial(trial, FakeRunner(), IMAGE, 600)

    def strip(lines):
        return [{k: v for k, v in l.items() if k != "duration_sec"} for l in lines]

    assert strip(read_replay(out)) == strip(replayed)


# --- The real Docker runner (slow) ----------------------------------------------

TS_PACK = REPO_ROOT / "tasks" / "typescript" / "split-second-stopwatch"
TS_STUB = "split-second-stopwatch.ts"
TS_AGENT_TEST = """\
import { expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from './split-second-stopwatch.ts'

it('starts ready', () => {
  expect(new SplitSecondStopwatch().state).toBe('ready')
})
"""


def _app_files(image: str) -> dict[str, bytes]:
    """The image's /app as the trace hook's seed fire records it: no .git/, no node_modules/."""
    done = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image,
         "tar", "-C", "/app", "--exclude=./.git", "-cf", "-", "."],
        capture_output=True, check=True, timeout=300,
    )
    files = {}
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        for member in tar.getmembers():
            name = member.name.removeprefix("./")
            if member.isfile() and "node_modules" not in name.split("/"):
                files[name] = tar.extractfile(member).read()
    return files


@pytest.mark.slow
def test_docker_runner_replays_a_typescript_trial(tmp_path):
    runner = DockerRunner()
    image = runner.image(TS_PACK)
    job = tmp_path / "results" / "job-ts"
    b = TrialBuilder(job, language="typescript", name="split-second-stopwatch__ts1")
    b.seed(_app_files(image))
    write = b.step().call("Write", {"file_path": "/app/stopwatch.test.ts"}, files={
        TS_STUB: (TS_PACK / "solution" / "proof.ci.ts").read_text(encoding="utf-8"),
        "stopwatch.test.ts": TS_AGENT_TEST,
    })
    b.reward = {
        "reward": 1, "reference_compiles": 1, "reference_passed": 29, "reference_total": 29,
        "agent_tests_compile": 1, "agent_tests_passed": 1, "agent_tests_total": 1,
    }
    b.build()

    verdicts = replay_job(job, tmp_path / "analysis", runner, tasks_root=REPO_ROOT)

    assert verdicts["split-second-stopwatch__ts1"].causes == []
    lines = read_replay(tmp_path / "analysis" / "job-ts" / "split-second-stopwatch__ts1")
    assert [(l["tool_use_id"], l["test_state"]) for l in lines] == [
        (None, "no-tests"), (write, "pass")]
    assert lines[0]["reward"] == 0
