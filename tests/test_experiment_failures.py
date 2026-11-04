"""`assay experiment <name>` checks each trial after its job, discards
infrastructure failures, retries them, and halts (issue #63, PRD v3 section
11), through the CLI's `main`, with the fake Harbor of test_experiment_run
writing failing fixture trials."""

import json

import pytest

from tests.test_experiment_run import (  # noqa: F401 (fixtures)
    AGENT, FakeHarbor, experiment, log, no_env_file, repo, write_experiment, write_job)


def exception(exception_type):
    """A trial change: Harbor recorded this exception for the trial."""
    def change(builder):
        builder.result["exception_info"] = {
            "exception_type": exception_type, "exception_message": "boom",
            "exception_traceback": "", "occurred_at": "2026-01-01T00:04:00Z"}
    return change


def no_seed_line(builder):
    """A trial change that fails validity check 2 (seed)."""
    builder._lines = [line for line in builder._lines if line["event"] != "seed"]


def events(repo, name):
    return [e for e in log(repo) if e["event"] == name]


def test_an_infrastructure_exception_is_discarded_and_logged_with_its_cost(repo):
    write_experiment(repo, write_job(repo, "a", n_attempts=2))
    harbor = FakeHarbor(outcomes={"a/slug__01": [exception("ApiOverloadedError")]})

    assert experiment(harbor) == 0

    [discarded] = events(repo, "trial-discarded")
    assert discarded["job"] == "a"
    assert discarded["trial"] == "slug__01"
    assert discarded["cause"] == {"exception": "ApiOverloadedError"}
    assert discarded["cost_usd"] == 0.1
    assert discarded["tokens"] == {"input": 1000, "cache": 800, "output": 100}
    assert discarded["duration_sec"] == 300.0
    assert discarded["task_pack"] == "tasks/go/split-second-stopwatch"
    assert discarded["cell"] == {"harness": "claude-code",
                                 "model_tier": "anthropic/claude-haiku-5-5",
                                 "condition": "control", "language": "go"}
    job = repo / "results" / "exp" / "a"
    assert not (job / "slug__01").exists()
    assert (job / "slug__00" / "result.json").exists()
    assert log(repo)[-1]["outcome"] == "complete"


def test_a_failed_validity_check_is_discarded_with_its_failed_checks(repo):
    write_experiment(repo, write_job(repo, "a"))
    harbor = FakeHarbor(outcomes={"a/slug__00": [no_seed_line]})

    assert experiment(harbor) == 0

    [discarded] = events(repo, "trial-discarded")
    assert discarded["cause"] == {"failed_checks": ["seed"]}
    assert not (repo / "results" / "exp" / "a" / "slug__00").exists()
    assert not (repo / "analysis" / "exp" / "a" / "slug__00").exists()


def test_a_kept_trial_has_its_trial_check(repo):
    write_experiment(repo, write_job(repo, "a"))

    assert experiment(FakeHarbor()) == 0

    check = repo / "analysis" / "exp" / "a" / "slug__00" / "trial-check.json"
    assert json.loads(check.read_text())["passed"] is True
    assert events(repo, "trial-discarded") == []


def test_retries_rerun_the_discarded_trials_in_their_place(repo):
    write_experiment(repo, write_job(repo, "a", n_attempts=2), write_job(repo, "b"))
    harbor = FakeHarbor(outcomes={"a/slug__01": [exception("ApiRateLimitError"),
                                                 no_seed_line]})

    assert experiment(harbor, "--retries", "2") == 0

    assert harbor.ran == ["a/slug__00", "a/slug__01", "a/slug__01", "a/slug__01", "b/slug__00"]
    assert [e["cause"] for e in events(repo, "trial-discarded")] == [
        {"exception": "ApiRateLimitError"}, {"failed_checks": ["seed"]}]
    assert [e.get("retry") for e in events(repo, "job-started")] == [None, 1, 2, None]
    assert (repo / "results" / "exp" / "a" / "slug__01" / "result.json").exists()
    assert log(repo)[-1]["outcome"] == "complete"


def test_an_unresolved_trial_leaves_its_cell_short(repo):
    write_experiment(repo, write_job(repo, "a", n_attempts=2))
    harbor = FakeHarbor(outcomes={"a/slug__01": [exception("HealthcheckError")] * 3})

    assert experiment(harbor, "--retries=1") == 0

    assert harbor.ran == ["a/slug__00", "a/slug__01", "a/slug__01"]
    assert len(events(repo, "trial-discarded")) == 2
    assert not (repo / "results" / "exp" / "a" / "slug__01").exists()


def test_no_retry_runs_by_default(repo):
    write_experiment(repo, write_job(repo, "a"))
    harbor = FakeHarbor(outcomes={"a/slug__00": [exception("ApiOverloadedError")]})

    assert experiment(harbor) == 0

    assert harbor.ran == ["a/slug__00"]


def test_an_unlisted_exception_type_is_an_infrastructure_failure_named_by_type(repo):
    write_experiment(repo, write_job(repo, "a"))
    harbor = FakeHarbor(outcomes={"a/slug__00": [exception("SomethingNewError")]})

    assert experiment(harbor) == 0

    [discarded] = events(repo, "trial-discarded")
    assert discarded["cause"] == {"exception": "SomethingNewError", "unlisted": True}


@pytest.mark.parametrize("exception_type", [
    "AgentTimeoutError", "ContextWindowExceededError", "AgentSafetyRefusalError",
    "VerifierTimeoutError"])
def test_a_timeout_or_refusal_is_kept_as_a_result(repo, exception_type):
    write_experiment(repo, write_job(repo, "a"))
    harbor = FakeHarbor(outcomes={"a/slug__00": [exception(exception_type)]})

    assert experiment(harbor) == 0

    assert events(repo, "trial-discarded") == []
    assert (repo / "results" / "exp" / "a" / "slug__00" / "result.json").exists()


def test_a_trial_with_no_file_writes_is_kept_as_a_result(repo):
    # The fake's trials change no file: the seed, then the final.
    write_experiment(repo, write_job(repo, "a"))

    assert experiment(FakeHarbor()) == 0

    assert events(repo, "trial-discarded") == []


@pytest.mark.parametrize("change, cause", [
    (exception("ApiUsageLimitError"), {"exception": "ApiUsageLimitError"}),
    (exception("AgentAuthenticationError"), {"exception": "AgentAuthenticationError"}),
    (exception("ModelNotFoundError"), {"exception": "ModelNotFoundError"}),
    (lambda b: b.instruments.update(digest="sha256:other"), {"failed_checks": ["instruments"]}),
])
def test_a_halt_stops_after_the_current_job_with_no_retries(repo, change, cause):
    write_experiment(repo, write_job(repo, "a", n_attempts=2), write_job(repo, "b"))
    harbor = FakeHarbor(outcomes={"a/slug__00": [change],
                                  "a/slug__01": [exception("ApiOverloadedError")]})

    assert experiment(harbor, "--retries", "3") == 3

    assert harbor.ran == ["a/slug__00", "a/slug__01"]  # no retry, no job b
    [halt] = events(repo, "halt")
    assert halt["trial"] == "slug__00"
    assert halt["cause"] == cause
    assert halt["cost_usd"] == 0.1
    assert "message" in halt
    [discarded] = events(repo, "trial-discarded")
    assert discarded["trial"] == "slug__01"
    assert (repo / "results" / "exp" / "a" / "slug__00").exists()  # kept until the next run
    assert log(repo)[-1]["outcome"] == "halted"


def test_the_next_invocation_deletes_the_halted_trials_and_runs_them_again(repo):
    write_experiment(repo, write_job(repo, "a"))
    harbor = FakeHarbor(outcomes={"a/slug__00": [exception("ApiUsageLimitError")]})
    assert experiment(harbor) == 3

    assert experiment(harbor) == 0

    assert harbor.ran == ["a/slug__00", "a/slug__00"]
    [discarded] = events(repo, "trial-discarded")
    assert discarded["trial"] == "slug__00"
    assert discarded["cause"] == {"exception": "ApiUsageLimitError"}
    assert discarded["after_halt"] is True
    assert log(repo)[-1]["outcome"] == "complete"


def test_the_dry_run_prints_the_halted_trials_that_resume_would_delete(repo, capsys):
    write_experiment(repo, write_job(repo, "a", n_attempts=2))
    harbor = FakeHarbor(outcomes={"a/slug__00": [exception("ModelNotFoundError")]})
    assert experiment(harbor) == 3
    capsys.readouterr()

    assert experiment(lambda args: pytest.fail("a dry run called Harbor"), "--dry-run") == 0

    out = capsys.readouterr().out
    assert "1 finished trial kept, 1 to run" in out
    assert "slug__00 (halted: ModelNotFoundError, Assay deletes it)" in out
    assert (repo / "results" / "exp" / "a" / "slug__00").exists()


def test_a_variant_edited_between_an_interrupted_invocation_and_its_resume_halts(repo):
    tdd = {**AGENT, "skills": ["variants/tdd/skill"]}
    write_experiment(repo, write_job(repo, "a", [tdd], n_attempts=3), write_job(repo, "b"))
    assert experiment(FakeHarbor(stop_after=1)) == 130
    skill = repo / "variants" / "tdd" / "skill" / "SKILL.md"
    skill.write_text(skill.read_text() + "edited\n", encoding="utf-8")

    harbor = FakeHarbor()
    assert experiment(harbor) == 3

    assert harbor.ran == ["a/slug__01", "a/slug__02"]  # job b does not run
    [halt] = events(repo, "halt")
    assert halt["trial"] == "slug__00"  # finished before the edit
    assert halt["cause"] == {"failed_checks": ["condition"]}
    assert halt["cell"]["condition"] == "tdd"

    harbor = FakeHarbor()
    assert experiment(harbor) == 0  # the halted trial runs again under the edited variant
    assert harbor.ran == ["a/slug__00", "b/slug__00"]


def test_a_variant_edited_after_a_killed_invocation_still_halts(repo):
    # A killed process writes no job-finished: the trial it finished is put in
    # its run by the job-started of the next run, which lists it.
    tdd = {**AGENT, "skills": ["variants/tdd/skill"]}
    write_experiment(repo, write_job(repo, "a", [tdd], n_attempts=2))
    experiment(FakeHarbor(stop_after=1))
    path = repo / "analysis" / "exp" / "experiment-log.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(l for l in lines if '"job-finished"' not in l and
                              '"invocation-finished"' not in l) + "\n")
    skill = repo / "variants" / "tdd" / "skill" / "SKILL.md"
    skill.write_text("edited\n", encoding="utf-8")

    assert experiment(FakeHarbor()) == 3

    [halt] = events(repo, "halt")
    assert halt["trial"] == "slug__00"


def test_a_variant_edited_during_a_job_halts(repo):
    tdd = {**AGENT, "skills": ["variants/tdd/skill"]}
    write_experiment(repo, write_job(repo, "a", [tdd]))
    fake = FakeHarbor()
    skill = repo / "variants" / "tdd" / "skill" / "SKILL.md"

    def harbor_and_an_edit(args):
        code = fake(args)
        skill.write_text("edited\n", encoding="utf-8")
        return code

    assert experiment(harbor_and_an_edit) == 3

    assert events(repo, "halt")[0]["cause"] == {"failed_checks": ["condition"]}


def test_a_job_file_that_sets_harbors_own_retries_is_refused(repo, capsys):
    write_job(repo, "a")
    job = repo / "jobs" / "a.yaml"
    job.write_text(job.read_text() + "retry:\n  max_retries: 2\n", encoding="utf-8")
    write_experiment(repo, "jobs/a.yaml")

    assert experiment(lambda args: pytest.fail("Harbor ran"), "--dry-run") == 2

    assert "max_retries" in capsys.readouterr().err
