"""The evaluations of `assay experiment <name>` (issue #64), through the CLI's
`main`, with a fake Harbor that writes fixture trials and a fake
`Containers`: the plan-time refusals, `replay` over every kept trial, and the
reuse of results."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from assay.cli import job_config, main
from tests.fake_containers import FakeContainers, gives
from tests.trial_builder import TrialBuilder

AGENT = {"import_path": "instruments.agent:InstrumentedClaudeCode",
         "model_name": "anthropic/claude-haiku-5-5", "kwargs": {"version": "2.1.308"}}
REWARD = {"reward": 1, "reference_compiles": 1, "reference_passed": 29, "reference_total": 29,
          "agent_tests_compile": 1, "agent_tests_passed": 1, "agent_tests_total": 1}


class FakeHarbor:
    """Plays `harbor run`: one fixture trial (seed, one Write, final) for each
    task, agent and attempt that has no result.json yet."""

    def __init__(self, halt=()):
        self.ran = []
        self.halt = set(halt)  # <job>/<trial>: a wrong instruments digest, a halt

    def __call__(self, args):
        args = list(args)
        config = job_config(Path(args[args.index("-c") + 1]), args)
        folder = (config.jobs_dir / config.job_name).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text(config.model_dump_json(), encoding="utf-8")
        for task in config.tasks:
            language, slug = Path(task.path).parts[-2:]
            for a, agent in enumerate(config.agents):
                for attempt in range(config.n_attempts):
                    name = f"{slug}__{a}{attempt}"
                    if (folder / name / "result.json").exists():
                        continue
                    builder = TrialBuilder(folder, language=language, name=name)
                    builder.lock["task"]["path"] = f"tasks\\{language}\\{slug}"
                    builder.seed(gives({**REWARD, "agent_tests_total": 0}))
                    builder.step().call("Write", files=gives(REWARD))
                    builder.finish()
                    builder.reward = REWARD
                    if f"{config.job_name}/{name}" in self.halt:
                        builder.instruments["digest"] = "sha256:other"
                    builder.build()
                    trial_config = {"trial_name": name, "agent": agent.model_dump(mode="json")}
                    (folder / name / "config.json").write_text(json.dumps(trial_config),
                                                               encoding="utf-8")
                    shutil.rmtree(builder.app)
                    self.ran.append(f"{config.job_name}/{name}")
        return 0


def never_harbor(args):
    raise AssertionError(f"a dry run called Harbor: {args}")


class NoContainers:
    def pack_image(self, task_pack):
        raise AssertionError("called Containers")

    def run(self, *args, **kwargs):
        raise AssertionError("called Containers")


@pytest.fixture(autouse=True)
def no_env_file(tmp_path, monkeypatch):
    # The repository's own .env stays out of every test.
    monkeypatch.setattr("assay.cli.ENV_FILE", tmp_path / "no.env")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    pack = tmp_path / "tasks" / "go" / "slug"
    pack.mkdir(parents=True)
    (pack / "task.toml").write_text('[metadata]\nbase_image = "golang@sha256:abc"\n'
                                    '[verifier]\ntimeout_sec = 60.0\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_job(repo, name, n_attempts=1):
    data = {"job_name": name, "n_attempts": n_attempts, "tasks": [{"path": "tasks/go/slug"}],
            "agents": [AGENT]}
    (repo / "jobs").mkdir(exist_ok=True)
    (repo / "jobs" / f"{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return f"jobs/{name}.yaml"


def write_experiment(repo, job_files, evaluations, extra=""):
    folder = repo / "experiments" / "exp"
    folder.mkdir(parents=True, exist_ok=True)
    jobs = ", ".join(f'"{file}"' for file in job_files)
    listed = ", ".join(f'"{e}"' for e in evaluations)
    (folder / "experiment.toml").write_text(
        f"jobs = [{jobs}]\nevaluations = [{listed}]\n{extra}", encoding="utf-8")


def write_evaluation(repo, file, name, body="return {'n': 1}", **fields):
    """An experiment-local evaluation at experiments/exp/<file>."""
    args = "".join(f", {k}={v!r}" for k, v in fields.items())
    (repo / "experiments" / "exp").mkdir(parents=True, exist_ok=True)
    (repo / "experiments" / "exp" / file).write_text(
        "from assay.evaluation import Evaluation\n\n\n"
        f"def evaluate(inp):\n    {body}\n\n\n"
        f"EVALUATION = Evaluation(name={name!r}, evaluate=evaluate{args})\n", encoding="utf-8")


def experiment(harbor, containers, *args):
    return main(["experiment", "exp", *args], run_harbor=harbor, containers=containers)


def log(repo):
    path = repo / "analysis" / "exp" / "experiment-log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def result(repo, job, trial, evaluation):
    path = repo / "analysis" / "exp" / job / trial / evaluation / "result.json"
    return json.loads(path.read_text(encoding="utf-8"))


def finished(repo, evaluation):
    return [e for e in log(repo)
            if e["event"] == "evaluation-finished" and e["evaluation"] == evaluation]


# --- replay over every kept trial ------------------------------------------------


def test_replay_runs_over_every_trial_and_writes_its_result_envelope(repo):
    write_experiment(repo, [write_job(repo, "a", n_attempts=2)], ["replay"])
    containers = FakeContainers()

    assert experiment(FakeHarbor(), containers) == 0

    for trial in ("slug__00", "slug__01"):
        envelope = result(repo, "a", trial, "replay")
        assert set(envelope) == {"evaluation", "digest", "code", "inputs", "started_at",
                                 "duration_sec", "value", "error"}
        assert envelope["evaluation"] == "replay"
        assert envelope["error"] is None
        assert envelope["value"]["works"] is True
        # seed and the Write; the unchanged final snapshot is not replayed again
        assert [s["test_state"] for s in envelope["value"]["snapshots"]] == ["no-tests", "pass"]
        assert envelope["digest"].startswith("sha256:")
        assert envelope["code"].startswith("sha256:")
        assert set(envelope["inputs"]) == {"record", "task_pack", "options"}
        # The out/ folder beside result.json holds the logs of each snapshot.
        assert (repo / "analysis" / "exp" / "a" / trial / "replay" / "out").is_dir()
    assert containers.packs == [Path("tasks/go/slug")] * 2
    [event] = finished(repo, "replay")
    assert (event["ran"], event["reused"], event["errors"]) == (2, 0, 0)
    assert "duration_sec" in event
    assert log(repo)[-1]["event"] == "invocation-finished"


def test_a_second_run_reuses_every_replay_result(repo):
    write_experiment(repo, [write_job(repo, "a", n_attempts=2)], ["replay"])
    assert experiment(FakeHarbor(), FakeContainers()) == 0
    first = result(repo, "a", "slug__00", "replay")

    containers = FakeContainers()
    assert experiment(FakeHarbor(), containers) == 0

    assert containers.runs == [] and containers.packs == []
    assert result(repo, "a", "slug__00", "replay") == first
    second = finished(repo, "replay")[-1]
    assert (second["ran"], second["reused"], second["errors"]) == (0, 2, 0)


def test_an_error_result_is_never_reused(repo):
    write_experiment(repo, [write_job(repo, "a")], ["replay"])

    class BrokenContainers(FakeContainers):
        def pack_image(self, task_pack):
            raise RuntimeError("docker build failed")

    assert experiment(FakeHarbor(), BrokenContainers()) == 0
    envelope = result(repo, "a", "slug__00", "replay")
    assert envelope["value"] is None
    assert "docker build failed" in envelope["error"]
    assert finished(repo, "replay")[-1]["errors"] == 1

    containers = FakeContainers()
    assert experiment(FakeHarbor(), containers) == 0

    assert containers.packs  # it ran again
    assert result(repo, "a", "slug__00", "replay")["error"] is None


def test_a_changed_task_pack_reruns_replay(repo):
    write_experiment(repo, [write_job(repo, "a")], ["replay"])
    assert experiment(FakeHarbor(), FakeContainers()) == 0
    (repo / "tasks" / "go" / "slug" / "task.toml").write_text(
        '[metadata]\nbase_image = "golang@sha256:abc"\n[verifier]\ntimeout_sec = 90.0\n')

    containers = FakeContainers()
    assert experiment(FakeHarbor(), containers) == 0

    assert len(containers.runs) == 4


def test_the_evaluations_cover_every_trial_whichever_jobs_ran(repo):
    write_experiment(repo, [write_job(repo, "a"), write_job(repo, "b")], ["replay"])
    assert experiment(FakeHarbor(), FakeContainers(), "--job", "a") == 0
    assert not (repo / "analysis" / "exp" / "b").exists()

    harbor = FakeHarbor()
    assert experiment(harbor, FakeContainers(), "--job", "b") == 0

    assert harbor.ran == ["b/slug__00"]
    assert result(repo, "b", "slug__00", "replay")["error"] is None
    last = finished(repo, "replay")[-1]
    assert (last["ran"], last["reused"]) == (1, 1)  # a's trial was kept and reused


def test_a_halted_invocation_runs_no_evaluation_and_the_next_one_evaluates_the_rerun(
        repo, capsys):
    write_experiment(repo, [write_job(repo, "a", n_attempts=2)], ["replay"])

    assert experiment(FakeHarbor(halt={"a/slug__00"}), NoContainers()) == 3

    assert finished(repo, "replay") == []
    # The dry run leaves the halted trial out: the next invocation deletes it.
    capsys.readouterr()
    assert plan(capsys)[1].out.count("replay: 0 reused, 1 to run") == 1

    harbor = FakeHarbor()
    assert experiment(harbor, FakeContainers()) == 0

    assert harbor.ran == ["a/slug__00"]
    last = finished(repo, "replay")[-1]
    assert (last["ran"], last["reused"], last["errors"]) == (2, 0, 0)


def test_an_interrupted_job_runs_no_evaluation(repo):
    write_experiment(repo, [write_job(repo, "a")], ["replay"])

    def interrupted(args):
        FakeHarbor()(args)
        return 130

    assert experiment(interrupted, NoContainers()) == 130

    assert finished(repo, "replay") == []


# --- reuse through dependencies, with experiment-local evaluations ---------------


def test_an_edited_evaluation_reruns_only_itself_and_an_unchanged_value_reruns_nothing_after(
        repo):
    write_evaluation(repo, "first.py", "first", "return {'n': 1}")
    write_evaluation(repo, "second.py", "second", "return inp.deps['first']",
                     depends_on=("first",))
    write_experiment(repo, [write_job(repo, "a")], ["./first.py", "./second.py"])
    assert experiment(FakeHarbor(), NoContainers()) == 0
    assert result(repo, "a", "slug__00", "second")["value"] == {"n": 1}
    assert set(result(repo, "a", "slug__00", "second")["inputs"]) == {
        "record", "task_pack", "options", "deps.first"}

    # The same value from new code: first reruns, second does not.
    write_evaluation(repo, "first.py", "first", "return {'n': 0 + 1}")
    assert experiment(FakeHarbor(), NoContainers()) == 0
    assert (finished(repo, "first")[-1]["ran"], finished(repo, "second")[-1]["ran"]) == (1, 0)

    # Edited code of the last evaluation: only it reruns.
    write_evaluation(repo, "second.py", "second", "return {'m': inp.deps['first']['n']}",
                     depends_on=("first",))
    assert experiment(FakeHarbor(), NoContainers()) == 0
    assert (finished(repo, "first")[-1]["ran"], finished(repo, "second")[-1]["ran"]) == (0, 1)
    assert result(repo, "a", "slug__00", "second")["value"] == {"m": 1}


def test_a_dependency_with_an_error_gives_its_dependent_an_error_without_a_call(repo):
    write_evaluation(repo, "first.py", "first", "raise ValueError('no data')")
    write_evaluation(repo, "second.py", "second", "raise AssertionError('called')",
                     depends_on=("first",))
    write_experiment(repo, [write_job(repo, "a")], ["./first.py", "./second.py"])

    assert experiment(FakeHarbor(), NoContainers()) == 0

    assert "ValueError: no data" in result(repo, "a", "slug__00", "first")["error"]
    second = result(repo, "a", "slug__00", "second")
    assert "first" in second["error"] and "called" not in second["error"]
    assert finished(repo, "second")[-1]["ran"] == 0


def test_the_options_reach_the_evaluation_and_count_in_its_digest(repo):
    write_evaluation(repo, "opts.py", "opts", "return dict(inp.options)")
    write_job(repo, "a")
    write_experiment(repo, ["jobs/a.yaml"], ["./opts.py"],
                     extra='[evaluation-options."./opts.py"]\nstrict = true\n')
    assert experiment(FakeHarbor(), NoContainers()) == 0
    assert result(repo, "a", "slug__00", "opts")["value"] == {"strict": True}

    write_experiment(repo, ["jobs/a.yaml"], ["./opts.py"],
                     extra='[evaluation-options."./opts.py"]\nstrict = false\n')
    assert experiment(FakeHarbor(), NoContainers()) == 0
    assert result(repo, "a", "slug__00", "opts")["value"] == {"strict": False}


def test_an_evaluation_cannot_run_an_online_container(repo):
    write_evaluation(repo, "net.py", "net",
                     "return inp.containers.run('img', ['true'], network='online')")
    write_experiment(repo, [write_job(repo, "a")], ["./net.py"])

    assert experiment(FakeHarbor(), FakeContainers()) == 0

    assert "online" in result(repo, "a", "slug__00", "net")["error"]


# --- the plan: refusals and the dry run --------------------------------------------


def plan(capsys):
    code = main(["experiment", "exp", "--dry-run"], run_harbor=never_harbor,
                containers=NoContainers())
    return code, capsys.readouterr()


def test_an_evaluation_listed_before_its_dependency_refuses_the_plan(repo, capsys):
    write_evaluation(repo, "first.py", "first")
    write_evaluation(repo, "second.py", "second", depends_on=("first",))
    write_experiment(repo, [write_job(repo, "a")], ["./second.py", "./first.py"])

    code, out = plan(capsys)

    assert code == 2
    assert "second is listed before its dependency first" in out.err


def test_a_dependency_that_is_not_listed_refuses_the_plan(repo, capsys):
    write_evaluation(repo, "second.py", "second", depends_on=("first",))
    write_experiment(repo, [write_job(repo, "a")], ["./second.py"])

    code, out = plan(capsys)

    assert code == 2
    assert "second depends on first, which experiment.toml does not list" in out.err


def test_an_evaluation_that_a_harness_cannot_feed_refuses_the_plan(repo, capsys):
    # The Claude Code reader never gives a tool call's duration.
    write_evaluation(repo, "timing.py", "timing", needs=("call_duration",))
    write_experiment(repo, [write_job(repo, "a")], ["./timing.py"])

    code, out = plan(capsys)

    assert code == 2
    assert "timing needs call_duration" in out.err and "claude-code" in out.err


def test_an_evaluation_that_needs_what_the_reader_gives_is_planned(repo, capsys):
    write_evaluation(repo, "exits.py", "exits", needs=("exit_code", "result"))
    write_experiment(repo, [write_job(repo, "a")], ["./exits.py"])

    code, out = plan(capsys)

    assert code == 0, out.err


@pytest.mark.parametrize("listed, refusal", [
    ("nope", "nope is not a built-in evaluation"),
    ("./missing.py", "./missing.py"),
])
def test_an_unknown_evaluation_refuses_the_plan(repo, capsys, listed, refusal):
    write_experiment(repo, [write_job(repo, "a")], [listed])

    code, out = plan(capsys)

    assert code == 2
    assert refusal in out.err


def test_an_online_evaluation_refuses_the_plan(repo, capsys):
    write_evaluation(repo, "osv.py", "osv", online=True)
    write_experiment(repo, [write_job(repo, "a")], ["./osv.py"])

    code, out = plan(capsys)

    assert code == 2
    assert "osv is online" in out.err


def test_the_dry_run_prints_the_evaluation_plan_and_what_it_would_reuse(repo, capsys):
    write_evaluation(repo, "after.py", "after", depends_on=("replay",))
    write_experiment(repo, [write_job(repo, "a", n_attempts=2)], ["replay", "./after.py"])
    assert experiment(FakeHarbor(), FakeContainers()) == 0
    shutil.rmtree(repo / "analysis" / "exp" / "a" / "slug__01" / "replay")
    capsys.readouterr()

    code, out = plan(capsys)

    assert code == 0, out.err
    text = out.out
    assert "replay" in text and "after" in text
    assert "after (./after.py) depends on replay" in text
    assert "replay: 1 reused, 1 to run" in text
    # after's result for slug__01 waits on replay's new value.
    assert "after: 1 reused, 1 to run" in text
