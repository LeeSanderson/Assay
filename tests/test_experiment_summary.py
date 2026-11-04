"""The summary contract (PRD v3 section 10; issue #66), through the CLI's
`main`, with the fake Harbor of test_experiment_run and an experiment-local
summary that writes what its ExperimentView holds."""

import json

import pytest

from assay.cli import main
from tests.test_experiment_failures import exception
from tests.test_experiment_run import (  # noqa: F401 (fixtures)
    AGENT, FakeHarbor, log, no_env_file, repo, write_job)

# An experiment-local summary that writes its view, so a test can read it.
VIEW_SUMMARY = '''
import json
from assay.summary import Summary


def summarize(view, options, out):
    data = {
        "factors": {name: list(levels) for name, levels in view.factors.items()},
        "trials": [{"job": t.job, "trial": t.trial, "cell": t.cell.__dict__,
                    "task_pack": t.task_pack.as_posix(), "record": t.record.name,
                    "values": dict(t.values), "errors": dict(t.errors)}
                   for t in view.trials],
        "expected": [[c.__dict__, n] for c, n in view.expected.items()],
        "events": [e["event"] for e in view.log],
        "options": dict(options),
    }
    (out / "view.json").write_text(json.dumps(data), encoding="utf-8")
    (out / "notes.md").write_text("notes", encoding="utf-8")


SUMMARY = Summary(summarize)
'''

COUNT_EVALUATION = '''
from assay.evaluation import Evaluation

EVALUATION = Evaluation(name="count", evaluate=lambda inp: {"calls": len(inp.record.tool_calls)})
'''


def write_experiment(repo, job_files, summary="./summary.py", evaluations=(), extra=""):
    folder = repo / "experiments" / "exp"
    folder.mkdir(parents=True, exist_ok=True)
    jobs = ", ".join(f'"{file}"' for file in job_files)
    listed = ", ".join(f'"{e}"' for e in evaluations)
    (folder / "experiment.toml").write_text(
        f'jobs = [{jobs}]\nevaluations = [{listed}]\n\n[summary]\nuse = "{summary}"\n{extra}',
        encoding="utf-8")


def write_summary(repo, source=VIEW_SUMMARY, file="summary.py"):
    (repo / "experiments" / "exp").mkdir(parents=True, exist_ok=True)
    (repo / "experiments" / "exp" / file).write_text(source, encoding="utf-8")


def view(repo):
    path = repo / "analysis" / "exp" / "summary" / "view.json"
    return json.loads(path.read_text(encoding="utf-8"))


def experiment(harbor, *args):
    return main(["experiment", "exp", *args], run_harbor=harbor)


def never_harbor(args):
    raise AssertionError(f"a dry run called Harbor: {args}")


def test_the_summary_gets_the_view_of_the_experiment_and_writes_to_its_folder(repo):
    sonnet = {**AGENT, "model_name": "anthropic/claude-sonnet-5-5"}
    write_experiment(repo, [write_job(repo, "a", [AGENT, sonnet]),
                            write_job(repo, "b", n_attempts=2)], evaluations=["./count.py"])
    (repo / "experiments" / "exp").mkdir(parents=True, exist_ok=True)
    (repo / "experiments" / "exp" / "count.py").write_text(COUNT_EVALUATION, encoding="utf-8")
    write_summary(repo)

    assert experiment(FakeHarbor(), "--job", "a") == 0

    seen = view(repo)
    # Only model_tier varies; harness and condition have one level each.
    assert seen["factors"] == {"model_tier": ["anthropic/claude-haiku-5-5",
                                              "anthropic/claude-sonnet-5-5"]}
    assert [(t["job"], t["trial"]) for t in seen["trials"]] == [("a", "slug__00"),
                                                                ("a", "slug__10")]
    first = seen["trials"][0]
    assert first["cell"] == {"harness": "claude-code", "model_tier": "anthropic/claude-haiku-5-5",
                             "condition": "control", "language": "go"}
    assert first["task_pack"] == "tasks/go/split-second-stopwatch"
    assert first["record"] == "slug__00"
    assert first["values"] == {"count": {"calls": 0}}
    assert first["errors"] == {"count": None}
    # The expected trials of every job, also of b, which did not run.
    haiku = {"harness": "claude-code", "model_tier": "anthropic/claude-haiku-5-5",
             "condition": "control", "language": "go"}
    assert [haiku, 3] in seen["expected"]
    assert seen["events"][0] == "invocation-started"
    assert "evaluation-finished" in seen["events"]
    events = log(repo)
    written = [e for e in events if e["event"] == "summary-written"]
    assert [e["files"] for e in written] == [["analysis/exp/summary/notes.md",
                                              "analysis/exp/summary/view.json"]]
    assert events[-1]["event"] == "invocation-finished"
    assert events[-1]["outcome"] == "complete"


def test_the_summary_always_runs_again_and_sees_the_discarded_trials(repo):
    write_experiment(repo, [write_job(repo, "a", n_attempts=2)])
    write_summary(repo)
    harbor = FakeHarbor(outcomes={"a/slug__01": [exception("ApiOverloadedError")]})
    assert experiment(harbor) == 0
    stale = repo / "analysis" / "exp" / "summary" / "stale.txt"
    stale.write_text("from before", encoding="utf-8")

    assert experiment(harbor) == 0

    assert not stale.exists()  # the summary folder is written afresh
    assert len([e for e in log(repo) if e["event"] == "summary-written"]) == 2
    assert view(repo)["events"].count("trial-discarded") == 1
    assert len(view(repo)["trials"]) == 2


def test_the_summary_options_reach_the_summary(repo):
    write_experiment(repo, [write_job(repo, "a")], extra="options = { rate = 1.5 }\n")
    write_summary(repo)

    assert experiment(FakeHarbor()) == 0

    assert view(repo)["options"] == {"rate": 1.5}


def test_a_halted_invocation_writes_no_summary(repo):
    write_experiment(repo, [write_job(repo, "a")])
    write_summary(repo)

    assert experiment(FakeHarbor(outcomes={"a/slug__00": [exception("ApiUsageLimitError")]})) == 3

    assert not (repo / "analysis" / "exp" / "summary").exists()
    assert all(e["event"] != "summary-written" for e in log(repo))


def test_a_summary_that_raises_ends_the_invocation_with_an_error(repo, capsys):
    write_experiment(repo, [write_job(repo, "a")])
    write_summary(repo, "from assay.summary import Summary\n\n\n"
                        "def summarize(view, options, out):\n    raise ValueError('no cells')\n\n\n"
                        "SUMMARY = Summary(summarize)\n")

    assert experiment(FakeHarbor()) == 2

    assert "no cells" in capsys.readouterr().err
    assert log(repo)[-1]["outcome"] == "error"


# --- the plan --------------------------------------------------------------------


def plan(capsys):
    code = main(["experiment", "exp", "--dry-run"], run_harbor=never_harbor)
    return code, capsys.readouterr()


def test_the_dry_run_names_the_summary(repo, capsys):
    write_experiment(repo, [write_job(repo, "a")])
    write_summary(repo)

    code, out = plan(capsys)

    assert code == 0, out.err
    assert "summary: ./summary.py (runs again on every invocation)" in out.out


@pytest.mark.parametrize("source, refusal", [
    (None, "summary ./summary.py: no file experiments/exp/summary.py"),
    ("import nowhere_at_all\n", "summary ./summary.py does not load"),
    ("SUMMARY = 1\n", "summary ./summary.py has no SUMMARY = Summary(...)"),
])
def test_a_summary_that_cannot_be_loaded_refuses_the_plan(repo, capsys, source, refusal):
    write_experiment(repo, [write_job(repo, "a")])
    if source is not None:
        write_summary(repo, source)

    code, out = plan(capsys)

    assert code == 2
    assert refusal in out.err


def test_a_summary_that_is_not_a_path_refuses_the_plan(repo, capsys):
    write_experiment(repo, [write_job(repo, "a")], summary="paired-delta")

    code, out = plan(capsys)

    assert code == 2
    assert "summary paired-delta is not a built-in summary" in out.err


def test_invalid_summary_options_refuse_the_plan(repo, capsys):
    write_experiment(repo, [write_job(repo, "a")], extra="options = { rate = -1 }\n")
    write_summary(repo, VIEW_SUMMARY.replace(
        "SUMMARY = Summary(summarize)",
        "def check(options):\n    if options.get('rate', 1) <= 0:\n"
        "        raise ValueError('rate must be above 0')\n\n\n"
        "SUMMARY = Summary(summarize, check_options=check)"))

    code, out = plan(capsys)

    assert code == 2
    assert "summary ./summary.py: invalid options: rate must be above 0" in out.err


def test_summary_options_must_be_a_table(repo, capsys):
    write_experiment(repo, [write_job(repo, "a")], extra='options = "fast"\n')
    write_summary(repo)

    code, out = plan(capsys)

    assert code == 2
    assert "summary.options must be a table" in out.err
