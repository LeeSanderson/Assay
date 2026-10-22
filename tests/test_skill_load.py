"""Whether the instrument skill loaded (PRD section 5, "The phase 0 instrument"):
a `Skill` call for `tdd`, and whether it comes before the first file write
(the smoke trial's gate). Over fake trial folders (spec #15, seam 1)."""

from analyze.trajectory import analyze_trial
from analyze.trial import read_trial

GO_STUB = "package stopwatch\n"


def go_trial(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
    return trial


def skill_load(trial):
    return analyze_trial(read_trial(trial.build()))["skill_load"]


def write_test(trial):
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch // test\n"})


def test_a_tdd_skill_call_before_the_first_file_write_loads_the_skill_in_time(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Skill", {"skill": "tdd"}, result="Launching skill: tdd")
    write_test(trial)

    assert skill_load(trial) == {"loaded": True, "before_first_file_write": True}


def test_a_tdd_skill_call_after_the_first_file_write_loads_the_skill_late(make_trial):
    trial = go_trial(make_trial)
    write_test(trial)
    trial.step().call("Skill", {"skill": "tdd"}, result="Launching skill: tdd")

    assert skill_load(trial) == {"loaded": True, "before_first_file_write": False}


def test_a_trial_with_no_tdd_skill_call_did_not_load_the_skill(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Skill", {"skill": "other"}, result="Launching skill: other")
    write_test(trial)

    assert skill_load(trial) == {"loaded": False, "before_first_file_write": False}


def test_a_failed_tdd_skill_call_does_not_load_the_skill(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Skill", {"skill": "tdd"}, result="Unknown skill: tdd", is_error=True)
    write_test(trial)

    assert skill_load(trial) == {"loaded": False, "before_first_file_write": False}
