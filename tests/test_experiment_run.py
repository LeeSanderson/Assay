"""`assay experiment <name>` runs its jobs and resumes (issue #61), through
the CLI's `main`, with a fake Harbor that writes fixture trials with the
trial builder and can stop partway."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from assay.cli import job_config, main
from tests.trial_builder import TrialBuilder

AGENT = {"import_path": "instruments.agent:InstrumentedClaudeCode",
         "model_name": "anthropic/claude-haiku-5-5", "kwargs": {"version": "2.1.308"}}


class FakeHarbor:
    """Plays `harbor run -c <job file> --jobs-dir <dir>`: writes the job's
    config.json and one fixture trial for each task, agent and attempt. Like
    Harbor, it resumes: it keeps each trial that has a result.json and deletes
    and reruns the rest. With `stop_after=n` it is interrupted (Ctrl-C) after
    n new trials, leaving the next trial unfinished."""

    def __init__(self, stop_after=None):
        self.stop_after = stop_after
        self.calls = []
        self.ran = []  # the trials this fake ran, as <job>/<trial>

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        config = job_config(Path(args[args.index("-c") + 1]), args)
        folder = (config.jobs_dir / config.job_name).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text(config.model_dump_json(), encoding="utf-8")
        new = 0
        for task in config.tasks:
            language, slug = Path(task.path).parts[-2:]
            for a, _agent in enumerate(config.agents):
                for attempt in range(config.n_attempts):
                    name = f"{slug}__{a}{attempt}"
                    if (folder / name / "result.json").exists():
                        continue
                    if folder.joinpath(name).exists():
                        shutil.rmtree(folder / name)
                    if self.stop_after is not None and new == self.stop_after:
                        (folder / name).mkdir()  # started, never finished
                        raise KeyboardInterrupt
                    builder = TrialBuilder(folder, language=language, name=name)
                    builder.seed({"README.md": "seed\n"})
                    builder.build()
                    shutil.rmtree(builder.app)
                    self.ran.append(f"{config.job_name}/{name}")
                    new += 1
        return 0


@pytest.fixture(autouse=True)
def no_env_file(tmp_path, monkeypatch):
    # The repository's own .env stays out of every test.
    monkeypatch.setattr("assay.cli.ENV_FILE", tmp_path / "no.env")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    skill = tmp_path / "variants" / "tdd" / "skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: tdd\n---\n", encoding="utf-8")
    (tmp_path / "tasks" / "go" / "slug").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_job(repo, name, agents=None, n_attempts=1):
    data = {"job_name": name, "n_attempts": n_attempts, "tasks": [{"path": "tasks/go/slug"}],
            "agents": agents if agents is not None else [AGENT]}
    (repo / "jobs").mkdir(exist_ok=True)
    (repo / "jobs" / f"{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return f"jobs/{name}.yaml"


def write_experiment(repo, *job_files):
    folder = repo / "experiments" / "exp"
    folder.mkdir(parents=True, exist_ok=True)
    jobs = ", ".join(f'"{file}"' for file in job_files)
    (folder / "experiment.toml").write_text(f"jobs = [{jobs}]\n", encoding="utf-8")


def log(repo):
    path = repo / "analysis" / "exp" / "experiment-log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def experiment(harbor, *args):
    return main(["experiment", "exp", *args], run_harbor=harbor)


def test_the_jobs_run_in_order_and_the_log_records_the_invocation(repo):
    write_experiment(repo, write_job(repo, "b"), write_job(repo, "a"))
    harbor = FakeHarbor()

    assert experiment(harbor) == 0

    assert harbor.ran == ["b/slug__00", "a/slug__00"]
    assert (repo / "results" / "exp" / "b" / "slug__00" / "result.json").exists()
    events = log(repo)
    assert [e["event"] for e in events] == [
        "invocation-started", "job-started", "job-finished", "job-started", "job-finished",
        "invocation-finished"]
    assert len({e["invocation"] for e in events}) == 1
    assert all("at" in e for e in events)
    assert [e["job"] for e in events if e["event"] == "job-started"] == ["b", "a"]
    assert events[-1]["outcome"] == "complete"
    finished = events[2]
    assert finished["exit_code"] == 0
    assert finished["trials"] == ["slug__00"]


def test_job_started_and_job_finished_carry_each_agents_condition_digest(repo):
    tdd = {**AGENT, "skills": ["variants/tdd/skill"]}
    control = {**AGENT, "model_name": "anthropic/claude-sonnet-5-5"}
    write_experiment(repo, write_job(repo, "a", [tdd, control]))

    assert experiment(FakeHarbor()) == 0

    started, finished = [e for e in log(repo) if e["event"] in ("job-started", "job-finished")]
    assert started["file"] == "jobs/a.yaml"
    for event in (started, finished):
        tdd_agent, control_agent = event["agents"]
        assert tdd_agent["condition"] == "tdd"
        assert tdd_agent["condition_digest"].startswith("sha256:")
        assert tdd_agent["model_tier"] == "anthropic/claude-haiku-5-5"
        assert control_agent["condition"] == "control"
        assert control_agent["condition_digest"] is None
    assert started["agents"] == finished["agents"]


def test_an_interrupted_job_resumes_keeping_its_finished_trials(repo):
    write_experiment(repo, write_job(repo, "a", n_attempts=3))
    job = repo / "results" / "exp" / "a"

    assert experiment(FakeHarbor(stop_after=1)) != 0
    (job / "slug__00" / "kept.txt").write_text("from the first invocation")

    harbor = FakeHarbor()
    assert experiment(harbor) == 0

    assert harbor.ran == ["a/slug__01", "a/slug__02"]
    assert (job / "slug__00" / "kept.txt").exists()
    assert all((job / f"slug__0{i}" / "result.json").exists() for i in range(3))
    events = log(repo)
    invocations = list(dict.fromkeys(e["invocation"] for e in events))
    assert len(invocations) == 2
    outcomes = [e["outcome"] for e in events if e["event"] == "invocation-finished"]
    assert outcomes == ["interrupted", "complete"]


def test_a_harbor_interrupted_by_ctrl_c_ends_the_invocation_as_interrupted(repo):
    write_experiment(repo, write_job(repo, "a"), write_job(repo, "b"))
    harbor = FakeHarbor()

    def stopped_by_ctrl_c(args):
        harbor(args)
        return 130  # what run_harbor returns after a Ctrl-C reached Harbor

    assert experiment(stopped_by_ctrl_c) == 130

    assert harbor.ran == ["a/slug__00"]  # no later job runs
    assert log(repo)[-1]["outcome"] == "interrupted"


def test_a_failing_harbor_ends_the_invocation_with_an_error(repo):
    write_experiment(repo, write_job(repo, "a"), write_job(repo, "b"))
    calls = []

    assert experiment(lambda args: calls.append(args) or 1) == 1

    assert len(calls) == 1
    assert log(repo)[-1]["outcome"] == "error"


def test_job_selects_the_jobs_that_run(repo):
    write_experiment(repo, write_job(repo, "a"), write_job(repo, "local"))
    harbor = FakeHarbor()

    assert experiment(harbor, "--job", "local") == 0

    assert harbor.ran == ["local/slug__00"]
    assert [e["job"] for e in log(repo) if e["event"] == "job-started"] == ["local"]


def test_only_debug_reaches_harbor(repo, capsys):
    write_experiment(repo, write_job(repo, "a"))
    harbor = FakeHarbor()

    assert experiment(harbor) == 0
    assert experiment(harbor, "--debug") == 0
    assert experiment(harbor, "--n-concurrent", "4") == 2

    plain = ["-c", "jobs/a.yaml", "--jobs-dir", "results/exp", "-y"]
    assert harbor.calls == [plain, [*plain, "--debug"]]
    assert "--n-concurrent" in capsys.readouterr().err


def test_from_scratch_deletes_the_results_and_the_analysis_then_runs(repo):
    write_experiment(repo, write_job(repo, "a"))
    assert experiment(FakeHarbor()) == 0
    (repo / "results" / "exp" / "a" / "slug__00" / "kept.txt").write_text("old")
    (repo / "analysis" / "exp" / "a").mkdir(parents=True)
    (repo / "analysis" / "exp" / "a" / "old.json").write_text("{}")

    harbor = FakeHarbor()
    assert experiment(harbor, "--from-scratch") == 0

    assert harbor.ran == ["a/slug__00"]
    assert not (repo / "results" / "exp" / "a" / "slug__00" / "kept.txt").exists()
    assert not (repo / "analysis" / "exp" / "a").exists()
    assert len({e["invocation"] for e in log(repo)}) == 1  # the old log is gone


def test_from_scratch_with_dry_run_only_prints_what_it_would_delete(repo, capsys):
    write_experiment(repo, write_job(repo, "a"))
    assert experiment(FakeHarbor()) == 0
    before = sorted(p.relative_to(repo) for p in repo.rglob("*"))
    capsys.readouterr()

    def never_harbor(args):
        raise AssertionError("a dry run called Harbor")

    assert experiment(never_harbor, "--from-scratch", "--dry-run") == 0

    out = capsys.readouterr().out
    assert "would delete results/exp" in out
    assert "would delete analysis/exp" in out
    assert sorted(p.relative_to(repo) for p in repo.rglob("*")) == before


def test_the_dry_run_prints_what_resume_would_rerun(repo, capsys):
    write_experiment(repo, write_job(repo, "a", n_attempts=3), write_job(repo, "b"))
    experiment(FakeHarbor(stop_after=1))
    capsys.readouterr()

    assert experiment(lambda args: pytest.fail("a dry run called Harbor"), "--dry-run") == 0

    out = capsys.readouterr().out
    resume = out[out.index("resume"):]
    assert "a" in resume and "1 finished trial kept, 2 to run" in resume
    assert "slug__01 (unfinished, Harbor deletes it)" in resume
    assert "0 finished trials kept, 1 to run" in resume  # job b has not run
