"""The trial reader over a fake trial folder (spec #15, seam 1)."""

import subprocess

from analyze.trial import PathChange, read_trial


def test_reader_joins_each_tool_call_with_its_observation_in_atif_order(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": "package stopwatch\n"})
    step = trial.step()
    read_id = step.call("Read", {"file_path": "/app/stopwatch.go"}, result="package stopwatch")
    bash_id = step.call("Bash", {"command": "go test ./..."},
                        result="Exit code 1\nFAIL", is_error=True)
    silent_id = trial.step().call("Bash", {"command": "sleep 999"}, result=None)

    t = read_trial(trial.build())

    assert [(c.step_id, c.position, c.tool_use_id, c.function_name) for c in t.tool_calls] == [
        (2, 0, read_id, "Read"), (2, 1, bash_id, "Bash"), (3, 0, silent_id, "Bash"),
    ]
    assert (t.tool_calls[1].arguments, t.tool_calls[1].result, t.tool_calls[1].is_error) == (
        {"command": "go test ./..."}, "Exit code 1\nFAIL", True,
    )
    assert (t.tool_calls[0].is_error, t.tool_calls[2].result, t.tool_calls[2].is_error) == (
        False, None, None,
    )
    assert t.last_step_id == 3


def test_reader_gives_trace_lines_joined_by_tool_use_id_and_a_real_trace_git(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": "package stopwatch\n"})
    write_id = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                                 files={"stopwatch_test.go": "package stopwatch\n"})

    t = read_trial(trial.build())

    assert [line.event for line in t.trace] == ["seed", "PostToolUse"]
    (line,) = t.trace_lines_for(write_id)
    assert (line.changed, line.paths) == (True, (PathChange("A", "stopwatch_test.go"),))
    files = subprocess.run(
        ["git", "--git-dir", str(t.trace_git), "ls-tree", "-r", "--name-only", line.commit],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert files == ["stopwatch.go", "stopwatch_test.go"]


def test_reader_gives_the_language_versions_and_the_json_files(make_trial):
    trial = make_trial("typescript", claude_code_version="2.1.7")
    trial.reward = {"reward": 1, "agent_tests_total": 3}
    trial.seed({"a.ts": "export {}\n"})

    t = read_trial(trial.build())

    assert t.language == "typescript"
    assert t.agent_version == "2.1.7"
    assert t.lock["agent"]["kwargs"]["version"] == "2.1.7"
    assert t.reward == {"reward": 1, "agent_tests_total": 3}
    assert t.result["verifier_result"] == {"rewards": {"reward": 1, "agent_tests_total": 3}}
    assert t.instruments["harbor_version"] == "0.24.0"


def test_reader_gives_none_for_missing_files(make_trial):
    trial = make_trial("go")
    trial.instruments = None
    trial.result = None
    path = trial.build()

    t = read_trial(path)

    assert (t.reward, t.result, t.instruments, t.trace) == (None, None, None, ())
