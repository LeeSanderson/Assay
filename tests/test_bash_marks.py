"""Bash file-write marks and the per-trial output (spec #15, seam 1)."""

import json

from analyze.trajectory import analyze_trial, main
from analyze.trial import read_trial
from tests.trial_builder import TrialBuilder

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


def test_main_writes_one_json_line_per_trial_of_each_job_to_the_analysis_folder(tmp_path, capsys):
    job_a, job_b = tmp_path / "results" / "job-a", tmp_path / "results" / "job-b"
    first = TrialBuilder(job_a, language="go")
    first.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
    first.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch\n"})
    first.build()
    second = TrialBuilder(job_b, language="typescript", name="other__xyz9876")
    second.seed({"stopwatch.ts": "export {}\n"})
    second.build()
    analysis = tmp_path / "analysis"

    assert main(["--analysis", str(analysis), str(job_a), str(job_b)]) == 0

    output = analysis / "trajectory.jsonl"
    assert capsys.readouterr().out == f"wrote {output}\n"
    lines = [json.loads(l) for l in output.read_text(encoding="utf-8").splitlines()]
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
            "skill_load": {"loaded": False, "before_first_file_write": False},
            "ad_hoc_runs": {"count": 0, "first_step_id": None},
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
            "skill_load": {"loaded": False, "before_first_file_write": False},
            "ad_hoc_runs": {"count": 0, "first_step_id": None},
        },
    ]


def test_main_overwrites_the_output_so_it_holds_only_the_jobs_given(tmp_path):
    job_a, job_b = tmp_path / "results" / "job-a", tmp_path / "results" / "job-b"
    for job in (job_a, job_b):
        TrialBuilder(job, name=f"{job.name}__t1").build()
    analysis = tmp_path / "analysis"
    main(["--analysis", str(analysis), str(job_a), str(job_b)])

    assert main(["--analysis", str(analysis), str(job_b)]) == 0

    lines = (analysis / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["trial"] for l in lines] == ["job-b__t1"]
