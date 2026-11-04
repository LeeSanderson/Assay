"""Snapshot replay (`analyze/replay.py`): spec #15 seam 2, and the `replay`
built-in evaluation through `evaluate(TrialInput)` (issue #64).

The fake `Containers` stands in for Docker. Like the real `test.sh`, its
result depends only on the snapshot it gets (tests/fake_containers.py). One
slow test runs the real Docker containers.
"""

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from analyze.replay import (
    EVALUATION, main, read_replay, replay_job, replay_trial, replay_works,
)
from analyze.trial import read_trial
from assay.containers import DockerContainers
from assay.evaluation import TrialInput
from tests.fake_containers import FakeContainers, fails, gives, times_out
from tests.trial_builder import REPLAY_REWARDS, TrialBuilder

REPO_ROOT = Path(__file__).resolve().parents[1]

IMAGE = "sha256:" + "a" * 64


def reward(compile=1, passed=0, total=0, **over) -> dict:
    fields = {
        "reward": 0, "reference_compiles": 1, "reference_passed": 0, "reference_total": 29,
        "agent_tests_compile": compile, "agent_tests_passed": passed, "agent_tests_total": total,
    }
    fields.update(over)
    return fields


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
    lines = replay_trial(read_trial(b.build()), FakeContainers(), IMAGE, 600)
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
    runner = FakeContainers()

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
    # Each snapshot in a fresh container with no network, given longer than
    # test.sh's own timeout so that its logs are written first.
    assert [(r["image"], r["network"]) for r in runner.runs] == [(IMAGE, "none")] * 3
    assert all(r["timeout"] > 600 for r in runner.runs)


def test_an_unchanged_final_snapshot_is_not_replayed_again(make_trial):
    b = make_trial()
    b.seed(gives(reward()))
    write = b.step().call("Write", files=gives(FINAL))
    b.finish()  # the harness exited; nothing changed since the last call
    lines = replay_trial(read_trial(b.build()), FakeContainers(), IMAGE, 600)
    assert [l["tool_use_id"] for l in lines] == [None, write]


def test_a_final_snapshot_with_a_change_after_the_last_call_is_replayed(make_trial):
    b = make_trial()
    b.seed(gives(reward()))
    write = b.step().call("Write", files=gives(reward(total=1, compile=0)))
    b._change(gives(FINAL), [])  # a change no tool call's hook saw
    b.finish()
    lines = replay_trial(read_trial(b.build()), FakeContainers(), IMAGE, 600)
    assert [(l["seq"], l["tool_use_id"], l["test_state"]) for l in lines] == [
        (0, None, "no-tests"), (1, write, "red-compile"), (2, None, "pass")]


def test_reward_fields_beyond_the_seven_are_kept(make_trial):
    b = make_trial()
    b.seed(gives(reward(extra_field=7)))
    [line] = replay_trial(read_trial(b.build()), FakeContainers(), IMAGE, 600)
    assert line["extra_field"] == 7


def test_a_runner_timeout_or_container_error_is_a_failed_line_and_replay_goes_on(make_trial):
    b = make_trial()
    b.seed(times_out())
    b.step().call("Write", files=fails(125))
    b.step().call("Write", files=gives(reward(compile=0, passed=0, total=1)))

    lines = replay_trial(read_trial(b.build()), FakeContainers(), IMAGE, 600)

    assert [l.get("error") for l in lines] == ["timeout after 600 s", "container exited 125", None]
    assert states(lines) == [None, None, "red-compile"]
    assert "agent_tests_total" not in lines[0]
    assert "error" not in lines[2]  # red-compile is a test state, not a failure


def test_a_reward_without_the_agent_pass_fields_is_a_failed_line(make_trial):
    b = make_trial()
    b.seed(gives({"reward": 1}))
    [line] = replay_trial(read_trial(b.build()), FakeContainers(), IMAGE, 600)
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
    runner = runner or FakeContainers()
    return replay_trial(trial, runner, IMAGE, 600), replay_trial(trial, runner, IMAGE, 600)


def test_replay_works_when_all_three_conditions_hold(make_trial):
    trial = _trial_with_two_snapshots(make_trial)
    verdict = replay_works(trial, *_twice(trial))
    assert verdict.works
    assert verdict.causes == []


def test_a_failed_snapshot_means_replay_does_not_work(make_trial):
    b = make_trial()
    b.seed(fails(125))
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


class FlakyContainers(FakeContainers):
    """Gives one more passing agent test on every odd run: the seed snapshot."""

    def run(self, image, command, **kwargs):
        done = super().run(image, command, **kwargs)
        fields = json.loads(done.stdout)
        if len(self.runs) % 2 == 1:
            fields["agent_tests_passed"] += 1
            fields["agent_tests_total"] += 1
        return done._replace(stdout=json.dumps(fields))


def test_two_runs_must_give_the_same_state_and_fields_for_each_snapshot(make_trial):
    b = make_trial()
    b.seed(gives(reward()))
    b.step().call("Write", files=gives(FINAL))
    b.reward = FINAL
    trial = read_trial(b.build())
    runner = FlakyContainers()
    first = replay_trial(trial, runner, IMAGE, 600)  # calls 1, 2: seq 0 gets +1
    second = replay_trial(trial, runner, IMAGE, 600)  # calls 3, 4: seq 0 gets +1 again
    assert replay_works(trial, first, second).works  # durations differ; nothing else

    third = replay_trial(trial, FakeContainers(), IMAGE, 600)
    verdict = replay_works(trial, first, third)
    assert not verdict.works
    assert verdict.causes == ["the two runs differ at snapshot seq 0"]


# --- A job: the files under analysis/ ------------------------------------------


BASE_IMAGE = "golang:1@sha256:abc"


def _fake_pack(root: Path, timeout: float) -> Path:
    pack = root / "tasks" / "go" / "split-second-stopwatch"
    pack.mkdir(parents=True)
    (pack / "task.toml").write_text(
        f'[metadata]\nbase_image = "{BASE_IMAGE}"\n[verifier]\ntimeout_sec = {timeout}\n',
        encoding="utf-8")
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
    bad.seed(times_out())
    bad.reward = FINAL
    bad.build()
    (job / "lock.json").write_text("{}", encoding="utf-8")  # the job's own files
    before = sorted(p for p in (tmp_path / "results").rglob("*"))
    runner = FakeContainers()

    verdicts = replay_job(job, tmp_path / "analysis", runner, tasks_root=tmp_path / "repo")

    assert sorted(p for p in (tmp_path / "results").rglob("*")) == before
    assert {name: v.works for name, v in verdicts.items()} == {"good__a": True, "bad__b": False}
    out = tmp_path / "analysis" / "job-7"
    good_lines = read_replay(out / "good__a")
    assert states(good_lines) == ["no-tests", "pass"]
    assert read_replay(out / "bad__b")[0]["error"] == "timeout after 42 s"
    # The verdict records the image replay ran and the pack's pinned base image.
    assert json.loads((out / "good__a" / "replay-works.json").read_text(encoding="utf-8")) == {
        "works": True, "causes": [], "image": f"image-of:{pack.as_posix()}",
        "base_image": BASE_IMAGE}
    assert json.loads((out / "bad__b" / "replay-works.json").read_text(encoding="utf-8"))[
        "works"] is False
    # Each trial runs twice, with the pack's image and its verifier timeout.
    assert len(runner.runs) == 2 * (2 + 1)
    assert {r["image"] for r in runner.runs} == {f"image-of:{pack.as_posix()}"}
    assert all("timeout 42 bash /tests/test.sh" in r["command"][-1] for r in runner.runs)
    assert set(runner.packs) == {pack}


def _files_under(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_replay_job_keeps_each_snapshots_verifier_logs_in_a_folder_named_by_its_seq(tmp_path):
    _fake_pack(tmp_path / "repo", 42.0)
    job = tmp_path / "results" / "job-7"
    b = TrialBuilder(job, name="t__a")
    b.seed(gives(reward(), logs={"agent-tsc.log": "seed tsc\n"}))
    step = b.step()
    step.call("Write", files=gives(reward(compile=0, total=1), logs={
        "agent-tsc.log": "error TS2835: Relative import paths need explicit file extensions\n",
        "outcome-jest.log": "Tests: 29 failed\n", "test-stdout.txt": "{}\n"}))
    step.call("Read")  # no snapshot
    b.step().call("Write", files=gives(FINAL, logs={"agent-jest.log": "Tests: 2 passed\n"}))
    b.reward = FINAL
    b.build()

    replay_job(job, tmp_path / "analysis", FakeContainers(), tasks_root=tmp_path / "repo")

    logs = tmp_path / "analysis" / "job-7" / "t__a" / "replay-logs"
    assert _files_under(logs) == {
        "0/agent-tsc.log": "seed tsc\n",
        "1/agent-tsc.log": "error TS2835: Relative import paths need explicit file extensions\n",
        "1/outcome-jest.log": "Tests: 29 failed\n",
        "1/test-stdout.txt": "{}\n",
        "3/agent-jest.log": "Tests: 2 passed\n",
    }


def test_a_snapshot_with_a_runner_error_keeps_whatever_logs_exist(tmp_path):
    _fake_pack(tmp_path / "repo", 42.0)
    job = tmp_path / "results" / "job-7"
    b = TrialBuilder(job, name="t__a")
    b.seed(times_out(logs={"outcome-tsc.log": "half a log"}))
    b.step().call("Write", files=fails(125))  # no logs at all
    b.reward = FINAL
    b.build()

    verdicts = replay_job(job, tmp_path / "analysis", FakeContainers(), tasks_root=tmp_path / "repo")

    out = tmp_path / "analysis" / "job-7" / "t__a"
    assert _files_under(out / "replay-logs") == {"0/outcome-tsc.log": "half a log"}
    assert [l["error"] for l in read_replay(out)] == ["timeout after 42 s", "container exited 125"]
    assert verdicts["t__a"].causes[:2] == [
        "snapshot seq 0 gives no test state: timeout after 42 s",
        "snapshot seq 1 gives no test state: container exited 125"]


def test_a_new_replay_replaces_the_old_logs(tmp_path):
    _fake_pack(tmp_path / "repo", 42.0)
    job = tmp_path / "results" / "job-7"
    b = TrialBuilder(job, name="t__a")
    b.seed(gives(FINAL, logs={"agent-tsc.log": "new"}))
    b.reward = FINAL
    b.build()
    stale = tmp_path / "analysis" / "job-7" / "t__a" / "replay-logs" / "9"
    stale.mkdir(parents=True)
    (stale / "agent-tsc.log").write_text("old", encoding="utf-8")

    replay_job(job, tmp_path / "analysis", FakeContainers(), tasks_root=tmp_path / "repo")

    assert _files_under(stale.parent) == {"0/agent-tsc.log": "new"}


def test_the_builders_replay_jsonl_matches_what_replay_writes(make_trial):
    b = make_trial()
    b.seed(gives(REPLAY_REWARDS["no-tests"]))
    step = b.step()
    red = step.call("Write", files=gives(REPLAY_REWARDS["red-compile"]))
    failing = step.call("Write", files=gives(REPLAY_REWARDS["fail"]))
    passing = b.step().call("Bash", files=gives(REPLAY_REWARDS["pass"]))
    trial = read_trial(b.build())
    out = b.write_replay({red: "red-compile", failing: "fail", passing: "pass"})

    replayed = replay_trial(trial, FakeContainers(), IMAGE, 600)

    def strip(lines):
        return [{k: v for k, v in l.items() if k != "duration_sec"} for l in lines]

    assert strip(read_replay(out)) == strip(replayed)


# --- replay as an evaluation: evaluate(TrialInput) ---------------------------------


def trial_input(trial_dir: Path, pack: Path, out: Path, containers) -> TrialInput:
    out.mkdir(parents=True, exist_ok=True)
    return TrialInput(job="job-7", trial=trial_dir.name, cell=None, task_pack=pack,
                      record=read_trial(trial_dir), deps={}, options={}, out=out,
                      containers=containers)


def test_replay_evaluates_one_trial_into_one_value_with_its_logs_in_out(tmp_path):
    pack = _fake_pack(tmp_path / "repo", 42.0)
    b = TrialBuilder(tmp_path / "results" / "job-7", name="t__a")
    b.seed(gives(reward(), logs={"agent-tsc.log": "seed tsc\n"}))
    write = b.step().call("Write", files=gives(FINAL, logs={"agent-jest.log": "2 passed\n"}))
    b.finish()
    b.reward = FINAL
    trial_dir = b.build()
    containers = FakeContainers()

    value = EVALUATION.evaluate(trial_input(trial_dir, pack, tmp_path / "out", containers))

    assert EVALUATION.name == "replay"
    assert EVALUATION.depends_on == () and EVALUATION.online is False
    # replay-works.json and replay.jsonl merged into one value.
    assert {k: value[k] for k in ("works", "causes", "image", "base_image")} == {
        "works": True, "causes": [], "image": f"image-of:{pack.as_posix()}",
        "base_image": BASE_IMAGE}
    assert [(s["seq"], s["tool_use_id"], s["test_state"]) for s in value["snapshots"]] == [
        (0, None, "no-tests"), (1, write, "pass")]
    assert value["snapshots"][1]["agent_tests_passed"] == 2
    json.dumps(value)  # a JSON value
    assert _files_under(tmp_path / "out") == {"0/agent-tsc.log": "seed tsc\n",
                                              "1/agent-jest.log": "2 passed\n"}
    assert containers.packs == [pack]
    assert len(containers.runs) == 4  # two snapshots, replayed twice


def test_replay_gives_the_same_value_as_the_replay_files_of_the_thin_entry_point(tmp_path):
    # `assay replay <job folder>` writes today's replay.jsonl and
    # replay-works.json; the evaluation's value holds the same, merged.
    pack = _fake_pack(tmp_path / "repo", 42.0)
    job = tmp_path / "results" / "job-7"
    b = TrialBuilder(job, name="t__a")
    b.seed(gives(reward()))
    b.step().call("Write", files=gives(reward(compile=0, total=1)))
    b.step().call("Write", files=fails(125, "no space"))
    b.reward = FINAL
    trial_dir = b.build()

    value = EVALUATION.evaluate(trial_input(trial_dir, pack, tmp_path / "out", FakeContainers()))
    replay_job(job, tmp_path / "analysis", FakeContainers(), tasks_root=tmp_path / "repo")

    out = tmp_path / "analysis" / "job-7" / "t__a"
    works = json.loads((out / "replay-works.json").read_text(encoding="utf-8"))

    def strip(lines):
        return [{k: v for k, v in l.items() if k != "duration_sec"} for l in lines]

    assert {k: v for k, v in value.items() if k != "snapshots"} == works
    assert strip(value["snapshots"]) == strip(read_replay(out))
    assert value["snapshots"][2]["error"] == "container exited 125: no space"
    assert works["works"] is False


def test_assay_replay_works_on_a_job_folder(tmp_path, capsys):
    job = tmp_path / "results" / "job-7"
    b = TrialBuilder(job, name="t__a")  # tasks/go/split-second-stopwatch of this repository
    b.seed(gives(reward()))
    b.step().call("Write", files=gives(FINAL))
    b.reward = FINAL
    b.build()

    code = main([str(job), "--analysis", str(tmp_path / "analysis")],
                containers=FakeContainers())

    assert code == 0
    assert "t__a: replay works" in capsys.readouterr().out
    out = tmp_path / "analysis" / "job-7" / "t__a"
    assert states(read_replay(out)) == ["no-tests", "pass"]
    assert json.loads((out / "replay-works.json").read_text(encoding="utf-8"))["works"] is True


# --- The real Docker containers (slow) ----------------------------------------------

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
def test_docker_containers_replay_a_typescript_trial(tmp_path):
    runner = DockerContainers()
    image = runner.pack_image(TS_PACK)
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
    # The real verifier's logs of each snapshot land on the host.
    logs = tmp_path / "analysis" / "job-ts" / "split-second-stopwatch__ts1" / "replay-logs"
    assert sorted(p.name for p in logs.iterdir()) == ["0", str(lines[1]["seq"])]
    final = logs / str(lines[1]["seq"])
    assert "Tests:" in (final / "agent-jest.log").read_text(encoding="utf-8")
    assert '"agent_tests_passed": 1' in (final / "test-stdout.txt").read_text(encoding="utf-8")
    assert (final / "outcome-tsc.log").exists()


# A test.sh that writes a log, then ignores the inner timeout's TERM and hangs.
HANG_DOCKERFILE = """\
FROM python:3.11-slim
RUN mkdir -p /app /tests && printf '%s\\n' \\
    'mkdir -p /logs/verifier' \\
    'echo "half a log" > /logs/verifier/outcome-tsc.log' \\
    "trap '' TERM" \\
    'sleep 600' > /tests/test.sh
"""


@pytest.mark.slow
def test_docker_containers_keep_the_logs_of_a_container_that_outlives_its_timeout(tmp_path):
    image = "assay-test-hang:1"
    subprocess.run(["docker", "build", "-q", "-t", image, "-"], input=HANG_DOCKERFILE,
                   text=True, capture_output=True, check=True, timeout=600)
    snapshot, logs = tmp_path / "snapshot", tmp_path / "logs"
    snapshot.mkdir()
    logs.mkdir()

    done = DockerContainers().run(
        image, ["bash", "-c", "mkdir -p /logs/verifier && bash /tests/test.sh"],
        mounts={snapshot: "/snapshot:ro", logs: "/logs/verifier"}, timeout=5)

    assert done.exit_code is None  # a timeout

    assert (logs / "outcome-tsc.log").read_text(encoding="utf-8") == "half a log\n"
