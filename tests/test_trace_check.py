"""The ten-check validity check of the trial record (PRD v3 section 8) over
fake trial folders, and `assay trace-check` over a job folder."""

import json

import pytest

from analyze.trial import read_trial
from analyze.trace_check import (
    CHECKS,
    ConditionDigests,
    MixedClaudeCodeVersions,
    job_claude_code_version,
    validity_check,
)
from assay.cli import main
from tests.trial_builder import TrialBuilder

GO_STUB = "package stopwatch\n"
VARIANT = "sha256:" + "a" * 64


def clean_trial(make_trial, **kwargs):
    """A trial that passes every check: a seed fire, one traced file write, a
    final fire. finish() adds the final fire, so a test can add calls first."""
    trial = make_trial("go", **kwargs)
    trial.seed({"stopwatch.go": GO_STUB})
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go", "content": GO_STUB},
                      files={"stopwatch_test.go": GO_STUB})
    return trial


def check(trial, condition=None, *, finish=True):
    if finish:
        trial.finish()
    return validity_check(read_trial(trial.build()), condition).failed


def test_there_are_ten_checks_in_prd_order():
    assert list(CHECKS) == [
        "instruments", "seed", "calls", "errors", "final", "harness-version",
        "harbor-version", "condition", "claimed-paths", "required-core",
    ]


def test_a_clean_trial_passes(make_trial):
    assert check(clean_trial(make_trial)) == []


def test_a_trial_with_no_file_writes_passes(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB})
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"})
    assert check(trial) == []


# 1. instruments

def test_a_missing_instruments_json_fails_the_instruments_check(make_trial):
    trial = clean_trial(make_trial)
    trial.instruments = None
    assert "instruments" in check(trial)


def test_a_digest_that_is_not_the_committed_digest_fails_the_instruments_check(make_trial):
    trial = clean_trial(make_trial)
    trial.instruments["digest"] = "sha256:" + "0" * 64
    assert check(trial) == ["instruments"]


@pytest.mark.parametrize("field", ["granularity", "calls_may_overlap"])
def test_an_undeclared_granularity_or_overlap_flag_fails_the_instruments_check(make_trial, field):
    trial = clean_trial(make_trial)
    del trial.instruments[field]
    assert "instruments" in check(trial)


# 2. seed

def test_a_trial_with_no_seed_line_fails_the_seed_check(make_trial):
    trial = make_trial("go")
    trial.step().call("Write", {"file_path": "/app/stopwatch.go", "content": GO_STUB},
                      files={"stopwatch.go": GO_STUB})
    assert check(trial) == ["seed"]


def test_a_seed_whose_commit_is_not_the_first_commit_fails_the_seed_check(make_trial):
    trial = make_trial("go")
    trial.step().call("Write", {"file_path": "/app/stopwatch.go", "content": GO_STUB},
                      files={"stopwatch.go": GO_STUB})
    trial.seed({"go.mod": "module stopwatch\n"})
    assert check(trial) == ["seed"]


# 3. calls

def test_a_tool_call_with_no_line_fails_the_calls_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"}, traced=False)
    assert check(trial) == ["calls"]


def test_a_failed_tool_call_with_no_line_fails_the_calls_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Bash", {"command": "false"}, result="Exit code 1", is_error=True,
                      traced=False)
    assert check(trial) == ["calls"]


def test_a_tool_call_with_two_lines_fails_the_calls_check(make_trial):
    trial = clean_trial(make_trial)
    tool_use_id = trial.step().call("Read", {"file_path": "/app/stopwatch.go"})
    trial.line(event="call", tool_name="Read", tool_use_id=tool_use_id,
               changed=False, paths=[])
    assert check(trial) == ["calls"]


# 4. errors

def test_a_line_with_an_error_fails_the_errors_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"},
                      trace={"changed": None, "error": "git add failed"})
    assert check(trial) == ["errors"]


# 5. final

def test_a_trial_with_no_final_line_fails_the_final_check(make_trial):
    assert check(clean_trial(make_trial), finish=False) == ["final"]


def test_a_final_that_found_a_change_fails_the_final_check(make_trial):
    trial = clean_trial(make_trial)
    trial._change({"untraced.go": GO_STUB}, [])  # a write no call line recorded
    assert check(trial) == ["final"]


def test_a_final_line_that_is_not_the_last_commit_fails_the_final_check(make_trial):
    trial = clean_trial(make_trial)
    trial.finish()
    trial.step().call("Write", {"file_path": "/app/late.go", "content": GO_STUB},
                      files={"late.go": GO_STUB})
    assert check(trial, finish=False) == ["final"]


# 6. harness version

def test_a_harness_version_that_is_not_the_pinned_version_fails(make_trial):
    trial = clean_trial(make_trial, claude_code_version="2.1.0")
    trial.agent_version = "2.1.7"
    assert check(trial) == ["harness-version"]


def test_a_trial_with_no_version_that_ran_fails_the_harness_version_check(make_trial):
    trial = clean_trial(make_trial)
    trial.agent_version = None
    assert "harness-version" in check(trial)


def test_a_job_whose_trials_ran_one_claude_code_version_gives_that_version(make_trial):
    trials = [read_trial(clean_trial(make_trial, claude_code_version="2.1.0").build())
              for _ in range(2)]
    assert job_claude_code_version(trials) == "2.1.0"


def test_a_job_with_mixed_claude_code_versions_stops_with_an_error(make_trial):
    first = clean_trial(make_trial, claude_code_version="2.1.0")
    second = clean_trial(make_trial, claude_code_version="2.1.0")
    second.agent_version = "2.1.7"
    trials = [read_trial(first.build()), read_trial(second.build())]
    with pytest.raises(MixedClaudeCodeVersions, match=r"2\.1\.0.*2\.1\.7"):
        job_claude_code_version(trials)


# 7. Harbor version

def test_a_harbor_version_that_is_not_the_locked_version_fails(make_trial):
    trial = clean_trial(make_trial)
    trial.instruments["harbor_version"] = "0.25.0"
    assert check(trial) == ["harbor-version"]


# 8. condition

def test_outside_an_experiment_the_condition_check_is_skipped_and_says_so(make_trial):
    trial = clean_trial(make_trial)
    trial.finish()

    result = validity_check(read_trial(trial.build())).to_json()

    assert result["passed"] is True
    assert result["checks"]["condition"]["passed"] is None
    assert "skipped" in result["checks"]["condition"]


def test_logged_digests_that_agree_with_the_plan_pass_the_condition_check(make_trial):
    assert check(clean_trial(make_trial), ConditionDigests(VARIANT, (VARIANT, VARIANT))) == []


def test_a_control_with_no_digest_passes_the_condition_check(make_trial):
    assert check(clean_trial(make_trial), ConditionDigests(None, (None, None))) == []


def test_a_part_file_changed_during_the_job_fails_the_condition_check(make_trial):
    changed = "sha256:" + "b" * 64
    assert check(clean_trial(make_trial),
                 ConditionDigests(VARIANT, (VARIANT, changed))) == ["condition"]


def test_a_part_file_changed_before_a_resume_fails_the_condition_check(make_trial):
    earlier = "sha256:" + "b" * 64
    assert check(clean_trial(make_trial),
                 ConditionDigests(VARIANT, (earlier, earlier))) == ["condition"]


def test_a_job_with_no_logged_digest_fails_the_condition_check(make_trial):
    assert check(clean_trial(make_trial), ConditionDigests(VARIANT, ())) == ["condition"]


# 9. claimed paths

def test_an_edit_whose_line_holds_its_path_passes(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})
    assert check(trial) == []


def test_an_edit_whose_line_lacks_its_path_fails_the_claimed_paths_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"},
                      trace={"paths": []})
    assert "claimed-paths" in check(trial)


def test_a_multiedit_whose_line_lacks_its_path_fails_the_claimed_paths_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("MultiEdit", {"file_path": "/app/stopwatch.go"}, trace={"paths": []})
    assert check(trial) == ["claimed-paths"]


def test_a_failed_edit_needs_no_path_in_its_line(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      result="String to replace not found", is_error=True)
    assert check(trial) == []


def test_an_edit_outside_the_seed_repository_needs_no_path_in_its_line(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/root/.bashrc"})
    assert check(trial) == []


def test_a_write_that_changes_the_content_and_whose_line_lacks_its_path_fails(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/stopwatch.go", "content": "package other\n"})
    assert check(trial) == ["claimed-paths"]


def test_a_write_of_a_new_file_whose_line_lacks_its_path_fails(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/new.go", "content": GO_STUB})
    assert check(trial) == ["claimed-paths"]


def test_a_write_of_the_same_content_needs_no_path_in_its_line(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/stopwatch.go", "content": GO_STUB})
    assert check(trial) == []


def test_a_write_is_compared_with_the_snapshot_before_it_not_the_seed(make_trial):
    trial = clean_trial(make_trial)
    changed = GO_STUB + "func New() {}\n"
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"}, files={"stopwatch.go": changed})
    trial.step().call("Write", {"file_path": "/app/stopwatch.go", "content": changed})
    assert check(trial) == []


# 10. required core

def test_a_trial_with_no_result_json_fails_the_required_core_check(make_trial):
    trial = clean_trial(make_trial)
    trial.result = None
    assert check(trial) == ["required-core"]


def test_a_trial_with_no_task_pack_digest_fails_the_required_core_check(make_trial):
    trial = clean_trial(make_trial)
    del trial.lock["task"]["digest"]

    trial.finish()
    result = validity_check(read_trial(trial.build())).to_json()

    assert result["failed_checks"] == ["required-core"]
    assert result["checks"]["required-core"]["missing"] == ["identity.task_pack_digest"]


# The class of a failure

@pytest.mark.parametrize("break_it,failure_class", [
    (lambda t: t.instruments.update(harbor_version="0.25.0"), "halt"),
    (lambda t: t.step().call("Read", {}, traced=False), "infrastructure-failure"),
])
def test_a_failed_check_gives_the_class_of_the_failure(make_trial, break_it, failure_class):
    trial = clean_trial(make_trial)
    break_it(trial)
    trial.finish()

    result = validity_check(read_trial(trial.build())).to_json()

    assert (result["passed"], result["class"]) == (False, failure_class)


def test_a_halt_check_wins_over_an_infrastructure_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Read", {}, traced=False)
    trial.instruments["harbor_version"] = "0.25.0"
    trial.finish()

    result = validity_check(read_trial(trial.build())).to_json()

    assert result["failed_checks"] == ["calls", "harbor-version"]
    assert result["class"] == "halt"


# assay trace-check: the thin entry point for one job folder

def job_of_two(tmp_path):
    job = tmp_path / "results" / "job"
    good = TrialBuilder(job, name="a__1")
    good.seed({"stopwatch.go": GO_STUB})
    good.finish()
    good.build()
    bad = TrialBuilder(job, name="b__2")
    bad.seed({"stopwatch.go": GO_STUB})
    bad.build()  # no final line
    return job


def test_trace_check_prints_each_trial_and_writes_its_trial_check_json(tmp_path, capsys):
    job = job_of_two(tmp_path)
    analysis = tmp_path / "analysis"

    assert main(["trace-check", str(job), "--analysis", str(analysis)],
                env_file=tmp_path / "none.env") == 0

    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(p["trial"], p["failed_checks"]) for p in printed] == [
        ("a__1", []), ("b__2", ["final"])]
    written = json.loads((analysis / "job" / "b__2" / "trial-check.json").read_text("utf-8"))
    assert (written["trial"], written["passed"], written["failed_checks"], written["class"]) == (
        "b__2", False, ["final"], "infrastructure-failure")
    assert written["checks"]["final"]["passed"] is False
    assert (analysis / "job" / "a__1" / "trial-check.json").is_file()


def test_trace_check_stops_on_mixed_claude_code_versions(tmp_path, capsys):
    job = job_of_two(tmp_path)
    late = TrialBuilder(job, name="c__3")
    late.agent_version = "9.9.9"
    late.build()

    assert main(["trace-check", str(job), "--analysis", str(tmp_path / "analysis")],
                env_file=tmp_path / "none.env") == 2
    assert "more than one Claude Code version" in capsys.readouterr().err
