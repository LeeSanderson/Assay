"""Bash file-write marks and the per-trial output (spec #15, seam 1)."""

import json

from analyze.trajectory import analyze_trial, main
from analyze.trial import read_trial

GO_STUB = "package stopwatch\n"


def go_trial(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
    return trial


def marks(trial):
    return analyze_trial(read_trial(trial.build()))["bash"]


def test_a_trial_without_a_file_writing_bash_call_has_neither_mark(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Bash", {"command": "go test ./..."}, result="ok")
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch\n"})

    assert marks(trial) == {"file_writing_bash": False, "bash_writes_test_or_implementation": False}


def test_a_bash_call_that_changes_only_a_neutral_file_gives_the_first_mark_only(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Bash", {"command": "go mod tidy"},
                      files={"go.sum": "x\n"})

    assert marks(trial) == {"file_writing_bash": True, "bash_writes_test_or_implementation": False}


def test_a_bash_call_that_only_deletes_a_file_is_file_writing_but_writes_no_class(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "old_test.go": "package stopwatch\n"})
    trial.step().call("Bash", {"command": "rm old_test.go"}, delete=["old_test.go"])

    assert marks(trial) == {"file_writing_bash": True, "bash_writes_test_or_implementation": False}


def test_a_bash_call_that_writes_an_implementation_file_gives_both_marks(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Bash", {"command": "sed -i s/a/b/ stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert marks(trial) == {"file_writing_bash": True, "bash_writes_test_or_implementation": True}


def test_main_prints_one_json_line_per_trial(make_trial, capsys):
    first = go_trial(make_trial)
    first.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch\n"})
    second = make_trial("typescript", name="other__xyz9876")
    second.seed({"stopwatch.ts": "export {}\n"})

    assert main([str(first.build()), str(second.build())]) == 0

    lines = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert lines == [
        {
            "trial": "split-second-stopwatch__abc1234",
            "language": "go",
            "test_first_order": {
                "verdict": "no-implementation",
                "first_test_write": {"step_id": 2, "position": 0, "path": "stopwatch_test.go"},
                "first_implementation_write": None,
            },
            "red_to_green_order": None,
            "tdd_loop": None,
            "bash": {"file_writing_bash": False, "bash_writes_test_or_implementation": False},
        },
        {
            "trial": "other__xyz9876",
            "language": "typescript",
            "test_first_order": {
                "verdict": "no-implementation",
                "first_test_write": None,
                "first_implementation_write": None,
            },
            "red_to_green_order": None,
            "tdd_loop": None,
            "bash": {"file_writing_bash": False, "bash_writes_test_or_implementation": False},
        },
    ]
