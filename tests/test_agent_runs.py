"""The cross-check with the agent's test runs (spec #15, seam 1; PRD section 5)."""

import json

import pytest

from analyze.agent_runs import (
    agent_runs, cross_check, cross_check_job, match_test_run, read_agent_runs,
)
from analyze.replay import read_replay
from analyze.trial import read_trial
from tests.trial_builder import TrialBuilder

GO_STUB = "package stopwatch\n"
GO_TEST = "package stopwatch\n\nfunc TestNew(t *testing.T) {}\n"


def go_trial(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
    return trial


def runs_of(builder, states=None):
    """The agent-runs lines of a built trial, with a replay of the given states."""
    replay = read_replay(builder.write_replay(states))
    return agent_runs(read_trial(builder.build()), replay), replay


def failed(code):
    return {"result": f"Exit code {code}\n--- FAIL: TestNew", "is_error": True}


@pytest.mark.parametrize("language, command", [
    ("go", "go test ./..."),
    ("go", "go test"),
    ("typescript", "jest"),
    ("typescript", "npx jest"),
    ("typescript", "npm test"),
    ("typescript", "npm run test"),
    ("typescript", "yarn test"),
    ("typescript", "pnpm test"),
])
def test_each_prd_pattern_is_a_full_test_run_for_its_language(language, command):
    run = match_test_run(language, command)

    assert run is not None
    assert run.partial is False


@pytest.mark.parametrize("language, command", [
    ("go", "go vet ./..."),
    ("go", "npm test"),
    ("typescript", "go test ./..."),
    ("typescript", "cat jest.config.cjs"),
    ("go", "echo go test"),
])
def test_a_command_outside_the_language_patterns_is_not_a_test_run(language, command):
    assert match_test_run(language, command) is None


@pytest.mark.parametrize("command", [
    "cd /app && go test ./...",
    "go build ./... && go test ./... 2>&1 | tail -20",
    "cd /app/sub && go test",
    "cd /tmp/x && cd /app && go test ./...",
    "GOFLAGS=-mod=mod go test ./...",
    "timeout 60 go test ./...",
    "gofmt -l .\ngo test ./...",
])
def test_a_test_run_inside_a_compound_command_in_the_seed_repository_counts(command):
    assert match_test_run("go", command) is not None


@pytest.mark.parametrize("command", [
    "cd /tmp/scratch && go test ./...",
    "cd /tmp/scratch; go test ./...",
    "cd .. && go test ./...",
    "cd && go test ./...",
])
def test_a_run_after_cd_out_of_the_seed_repository_is_not_a_test_run(command):
    assert match_test_run("go", command) is None


@pytest.mark.parametrize("language, command", [
    ("go", "go test -run TestNew ./..."),
    ("go", "go test -v -run=TestLap"),
    ("go", "go test --run TestLap"),
    ("go", "go test -skip TestReset ./..."),
    ("typescript", "npx jest split-second-stopwatch.test.ts"),
    ("typescript", "jest -t 'laps'"),
    ("typescript", "yarn test --testNamePattern=laps"),
    ("typescript", "npm test -- stopwatch"),
    ("typescript", "npx jest --config jest.config.cjs stopwatch"),
])
def test_a_run_that_selects_some_tests_is_partial(language, command):
    assert match_test_run(language, command).partial is True


@pytest.mark.parametrize("language, command", [
    ("go", "go test -v -count=1 ./..."),
    ("go", "go test -timeout 30s ./..."),
    ("go", "go test ./... 2>&1"),
    ("typescript", "npx jest --ci"),
    ("typescript", "npx jest --config jest.config.cjs"),
    ("typescript", "npx jest --testTimeout 5000 2>&1 | tail"),
    ("typescript", "npm test -- --ci"),
])
def test_a_run_of_the_whole_suite_is_not_partial(language, command):
    assert match_test_run(language, command).partial is False


def test_a_command_with_a_partial_and_a_full_run_is_partial():
    run = match_test_run("go", "go test -run TestNew && go test ./...")

    assert run.partial is True


def test_each_test_run_gives_one_line_against_the_last_snapshot_before_it(make_trial):
    trial = go_trial(make_trial)
    write = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                              files={"stopwatch_test.go": GO_TEST})
    run = trial.step().call("Bash", {"command": "go test ./..."}, **failed(1))
    trial.step().call("Bash", {"command": "ls"})

    lines, replay = runs_of(trial, {write: "fail"})

    assert lines == [{
        "tool_use_id": run,
        "step_id": 3,
        "position": 0,
        "command": "go test ./...",
        "partial": False,
        "exit_code": 1,
        "snapshot_seq": 1,
        "snapshot_commit": replay[1]["commit"],
        "snapshot_tool_use_id": write,
        "test_state": "fail",
        "agrees": True,
    }]


@pytest.mark.parametrize("outcome, state, agrees", [
    ({}, "pass", True),
    ({}, "fail", False),
    ({}, "red-compile", False),
    ({}, "no-tests", False),
    (failed(1), "fail", True),
    (failed(2), "red-compile", True),
    (failed(1), "pass", False),
    (failed(1), "no-tests", True),
])
def test_a_run_agrees_when_both_pass_or_both_do_not(make_trial, outcome, state, agrees):
    trial = go_trial(make_trial)
    write = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                              files={"stopwatch_test.go": GO_TEST})
    trial.step().call("Bash", {"command": "go test ./..."}, **outcome)

    [line], _ = runs_of(trial, {write: state})

    assert (line["test_state"], line["agrees"]) == (state, agrees)


def test_fail_and_red_compile_count_as_the_same_for_agreement(make_trial):
    trial = go_trial(make_trial)
    first = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                              files={"stopwatch_test.go": GO_TEST})
    trial.step().call("Bash", {"command": "go test ./..."}, **failed(1))
    second = trial.step().call("Edit", {"file_path": "/app/stopwatch_test.go"},
                               files={"stopwatch_test.go": GO_TEST + "// x\n"})
    trial.step().call("Bash", {"command": "go test ./..."}, **failed(1))

    lines, _ = runs_of(trial, {first: "fail", second: "red-compile"})

    assert [line["agrees"] for line in lines] == [True, True]


def test_the_exit_code_is_0_for_success_and_n_from_the_error_result(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Bash", {"command": "go test ./..."}, result="ok", is_error=None)
    trial.step().call("Bash", {"command": "go test ./..."}, **failed(2))
    trial.step().call("Bash", {"command": "go test ./..."}, result=None)

    lines, _ = runs_of(trial)

    assert [line["exit_code"] for line in lines] == [0, 2, None]
    assert lines[2]["agrees"] is None


def test_a_partial_run_has_no_agreement_value(make_trial):
    trial = go_trial(make_trial)
    write = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                              files={"stopwatch_test.go": GO_TEST})
    trial.step().call("Bash", {"command": "go test -run TestNew ./..."})

    [line], _ = runs_of(trial, {write: "fail"})

    assert line["partial"] is True
    assert line["exit_code"] == 0
    assert line["test_state"] == "fail"
    assert line["agrees"] is None


def test_a_run_that_changes_files_applies_to_the_snapshot_before_it(make_trial):
    trial = go_trial(make_trial)
    write = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                              files={"stopwatch_test.go": GO_TEST})
    run = trial.step().call("Bash", {"command": "go mod tidy && go test ./..."},
                            files={"go.sum": "x\n"})

    [line], _ = runs_of(trial, {write: "pass", run: "fail"})

    assert line["snapshot_tool_use_id"] == write
    assert line["test_state"] == "pass"


def test_a_run_before_any_change_applies_to_the_seed_snapshot(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Bash", {"command": "go test ./..."})

    [line], replay = runs_of(trial)

    assert (line["snapshot_seq"], line["snapshot_tool_use_id"]) == (0, None)
    assert line["snapshot_commit"] == replay[0]["commit"]
    assert line["test_state"] == "no-tests"


def test_a_typescript_run_after_cd_out_of_the_seed_repository_gives_no_line(make_trial):
    trial = make_trial("typescript")
    trial.seed({"split-second-stopwatch.ts": "export {}\n"})
    trial.step().call("Bash", {"command": "cd /tmp/probe && npx jest"})
    trial.step().call("Bash", {"command": "corepack yarn jest"})

    lines, _ = runs_of(trial)

    assert [line["command"] for line in lines] == ["corepack yarn jest"]


def test_coverage_is_the_share_of_snapshots_followed_by_a_run_and_agreement_of_full_runs(make_trial):
    trial = go_trial(make_trial)  # snapshot 1: the seed
    a = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                          files={"stopwatch_test.go": GO_TEST})  # snapshot 2
    trial.step().call("Bash", {"command": "go test ./..."})  # agrees
    trial.step().call("Bash", {"command": "go test -run TestNew"})  # partial, same snapshot
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "// b\n"})  # snapshot 3, no run
    c = trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                          files={"stopwatch.go": GO_STUB + "// c\n"})  # snapshot 4
    differs = trial.step().call("Bash", {"command": "go test ./..."}, **failed(1))

    lines, replay = runs_of(trial, {a: "pass", c: "pass"})

    assert cross_check(replay, lines) == {
        "snapshots": 4,
        "covered_snapshots": 2,
        "coverage": 0.5,
        "test_runs": 3,
        "partial_runs": 1,
        "compared_runs": 2,
        "agreeing_runs": 1,
        "agreement": 0.5,
        "differences": [differs],
    }


def test_cross_check_job_writes_agent_runs_and_the_summary_under_analysis_only(tmp_path):
    job = tmp_path / "results" / "job-1"
    trial = TrialBuilder(job, language="go")
    trial.seed({"stopwatch.go": GO_STUB})
    write = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                              files={"stopwatch_test.go": GO_TEST})
    run = trial.step().call("Bash", {"command": "go test ./..."}, **failed(1))
    trial.build()
    out = tmp_path / "analysis" / "job-1" / trial.dir.name
    trial.write_replay({write: "red-compile"}, analysis_dir=out)
    before = sorted(p for p in job.rglob("*"))

    summaries = cross_check_job(job, tmp_path / "analysis")

    assert sorted(p for p in job.rglob("*")) == before
    [line] = read_agent_runs(out)
    assert (line["tool_use_id"], line["agrees"]) == (run, True)
    written = json.loads((out / "cross-check.json").read_text(encoding="utf-8"))
    assert written == summaries[trial.dir.name]
    assert (written["coverage"], written["agreement"]) == (0.5, 1.0)


def test_a_trial_without_test_runs_has_no_agreement_value(make_trial):
    trial = go_trial(make_trial)

    lines, replay = runs_of(trial)
    summary = cross_check(replay, lines)

    assert (summary["coverage"], summary["agreement"]) == (0.0, None)
