"""The trace check (PRD section 5, "The trace check") over fake trial folders."""

import pytest

from analyze.trace_check import MixedClaudeCodeVersions, job_claude_code_version, trace_check
from analyze.trial import read_trial

GO_STUB = "package stopwatch\n"


def clean_trial(make_trial, **kwargs):
    """A trial that passes every check: a seed fire and one traced file write."""
    trial = make_trial("go", **kwargs)
    trial.seed({"stopwatch.go": GO_STUB})
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go", "content": "package stopwatch\n"},
                      files={"stopwatch_test.go": "package stopwatch\n"})
    return trial


def check(trial):
    return trace_check(read_trial(trial.build()))


def test_a_clean_trial_passes_with_an_empty_list(make_trial):
    assert check(clean_trial(make_trial)) == []


def test_a_missing_instruments_json_fails_the_instruments_check(make_trial):
    trial = clean_trial(make_trial)
    trial.instruments = None
    assert "instruments" in check(trial)


def test_a_digest_that_is_not_the_committed_digest_fails_the_instruments_check(make_trial):
    trial = clean_trial(make_trial)
    trial.instruments["digest"] = "sha256:" + "0" * 64
    assert check(trial) == ["instruments"]


def test_a_trial_with_no_seed_line_fails_the_seed_check(make_trial):
    trial = make_trial("go")
    trial.step().call("Write", {"file_path": "/app/stopwatch.go", "content": GO_STUB},
                      files={"stopwatch.go": GO_STUB})
    assert check(trial) == ["seed"]


def test_a_tool_call_with_no_trace_line_fails_the_tool_call_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"}, traced=False)
    assert check(trial) == ["tool-calls"]


def test_a_tool_call_with_two_trace_lines_fails_the_tool_call_check(make_trial):
    trial = clean_trial(make_trial)
    tool_use_id = trial.step().call("Read", {"file_path": "/app/stopwatch.go"})
    trial.line(event="PostToolUse", tool_name="Read", tool_use_id=tool_use_id,
               changed=False, paths=[])
    assert check(trial) == ["tool-calls"]


def test_a_line_with_an_error_fails_the_error_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"},
                      trace={"changed": None, "error": "git add failed"})
    assert check(trial) == ["errors"]


def test_a_trial_with_no_changed_line_fails_the_changed_check(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB}, trace={"changed": False})
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"})
    assert check(trial) == ["changed"]


def test_a_claude_code_version_that_is_not_the_requested_version_fails_the_version_check(make_trial):
    trial = clean_trial(make_trial, claude_code_version="2.1.0")
    trial.agent_version = "2.1.7"
    assert check(trial) == ["claude-code-version"]


def test_a_trial_with_no_trajectory_version_fails_the_version_check(make_trial):
    trial = clean_trial(make_trial)
    trial.agent_version = None
    assert check(trial) == ["claude-code-version"]


def test_a_harbor_version_that_is_not_the_locked_version_fails_the_harbor_check(make_trial):
    trial = clean_trial(make_trial)
    trial.instruments["harbor_version"] = "0.25.0"
    assert check(trial) == ["harbor-version"]


def test_an_edit_whose_line_holds_its_path_passes_the_file_write_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})
    assert check(trial) == []


def test_an_edit_whose_line_lacks_its_path_fails_the_file_write_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"},
                      trace={"paths": []})
    assert check(trial) == ["file-writes"]


def test_a_multiedit_whose_line_lacks_its_path_fails_the_file_write_check(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("MultiEdit", {"file_path": "/app/stopwatch.go"}, trace={"paths": []})
    assert check(trial) == ["file-writes"]


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
    assert check(trial) == ["file-writes"]


def test_a_write_of_a_new_file_whose_line_lacks_its_path_fails(make_trial):
    trial = clean_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/new.go", "content": GO_STUB})
    assert check(trial) == ["file-writes"]


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
