"""Red-to-green order and the TDD loop (PRD section 5) over fake trial folders
(spec #15, seam 1): the trial, its replay.jsonl, and its agent-runs lines."""

from analyze.agent_runs import agent_runs
from analyze.replay import read_replay
from analyze.trajectory import analyze_trial
from analyze.trial import read_trial

GO_STUB = "package stopwatch\n"
GO_TEST = "package stopwatch\n\nfunc TestNew(t *testing.T) {}\n"


def go_trial(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
    return trial


def write(trial, path, content):
    """One step that writes a file and returns its tool_use_id (its snapshot)."""
    return trial.step().call("Write", {"file_path": f"/app/{path}"}, files={path: content})


def go_test(trial, code, command="go test ./..."):
    """One step that runs the tests with the given exit code."""
    if code == 0:
        return trial.step().call("Bash", {"command": command}, result="ok\n")
    return trial.step().call("Bash", {"command": command},
                             result=f"Exit code {code}\n--- FAIL: TestNew", is_error=True)


def analyze(trial, states, totals=None):
    replay = read_replay(trial.write_replay(states, totals=totals))
    built = read_trial(trial.build())
    return analyze_trial(built, replay, agent_runs(built, replay))


def test_seen_red_then_seen_green_is_red_to_green(make_trial):
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    red = go_test(trial, 1)
    impl = write(trial, "stopwatch.go", GO_STUB + "func New() {}\n")
    green = go_test(trial, 0)

    out = analyze(trial, {test: "fail", impl: "pass"})

    assert out["red_to_green_order"] == {
        "verdict": "red-to-green", "first_seen_red": red, "first_seen_green": green,
    }


def test_seen_green_first_is_green_first(make_trial):
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    green = go_test(trial, 0)
    edit = write(trial, "stopwatch_test.go", GO_TEST + "// more\n")
    red = go_test(trial, 1)

    out = analyze(trial, {test: "pass", edit: "fail"})

    assert out["red_to_green_order"] == {
        "verdict": "green-first", "first_seen_red": red, "first_seen_green": green,
    }


def test_only_seen_red_states_are_never_green(make_trial):
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    red = go_test(trial, 1)
    go_test(trial, 2)

    out = analyze(trial, {test: "red-compile"})

    assert out["red_to_green_order"] == {
        "verdict": "never-green", "first_seen_red": red, "first_seen_green": None,
    }


def test_a_trial_with_no_test_runs_is_not_observed(make_trial):
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)

    out = analyze(trial, {test: "pass"})

    assert out["red_to_green_order"] == {
        "verdict": "not-observed", "first_seen_red": None, "first_seen_green": None,
    }


def test_a_run_that_disagrees_with_the_replay_is_not_a_seen_state(make_trial):
    # go test -run TestNew passes, but the replay of the snapshot gives fail.
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    go_test(trial, 0, command="go test -run TestNew")
    red = go_test(trial, 1)

    out = analyze(trial, {test: "fail"})

    assert out["red_to_green_order"] == {
        "verdict": "never-green", "first_seen_red": red, "first_seen_green": None,
    }


def test_a_partial_run_that_agrees_is_a_seen_state(make_trial):
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    red = go_test(trial, 1, command="go test -run TestNew")
    impl = write(trial, "stopwatch.go", GO_STUB + "func New() {}\n")
    green = go_test(trial, 0, command="go test -run TestNew")

    out = analyze(trial, {test: "fail", impl: "pass"})

    assert out["red_to_green_order"] == {
        "verdict": "red-to-green", "first_seen_red": red, "first_seen_green": green,
    }


def test_a_run_on_a_no_tests_snapshot_is_not_a_seen_state_whatever_its_exit_code(make_trial):
    trial = go_trial(make_trial)
    write(trial, "notes.txt", "x\n")
    go_test(trial, 1)
    go_test(trial, 0)

    out = analyze(trial, {})

    assert out["red_to_green_order"]["verdict"] == "not-observed"


def test_without_replay_and_agent_runs_the_two_metrics_are_none(make_trial):
    trial = go_trial(make_trial)
    go_test(trial, 0)

    out = analyze_trial(read_trial(trial.build()))

    assert out["red_to_green_order"] is None
    assert out["tdd_loop"] is None


def test_the_prd_worked_example_gives_2_cycles_0_never_seen_red_and_2_refactor_steps(make_trial):
    # red, green with 1 test, green with 1 test after an edit of the
    # implementation, red, green with 2 tests, green with 2 tests after an
    # edit of the test file.
    trial = go_trial(make_trial)
    test1 = write(trial, "stopwatch_test.go", GO_TEST)
    go_test(trial, 1)
    impl1 = write(trial, "stopwatch.go", GO_STUB + "func New() {}\n")
    go_test(trial, 0)
    impl2 = write(trial, "stopwatch.go", GO_STUB + "func New() { }\n")
    go_test(trial, 0)
    test2 = write(trial, "stopwatch_test.go", GO_TEST + "func TestStart(t *testing.T) {}\n")
    go_test(trial, 1)
    impl3 = write(trial, "stopwatch.go", GO_STUB + "func New() {}\nfunc Start() {}\n")
    go_test(trial, 0)
    test3 = write(trial, "stopwatch_test.go", GO_TEST + "func TestStart(t *testing.T) { }\n")
    go_test(trial, 0)

    out = analyze(
        trial,
        {test1: "fail", impl1: "pass", impl2: "pass", test2: "fail", impl3: "pass", test3: "pass"},
        totals={test1: 1, impl1: 1, impl2: 1, test2: 2, impl3: 2, test3: 2},
    )

    assert out["tdd_loop"] == {"cycles": 2, "tests_never_seen_red": 0, "refactor_steps": 2}
    assert out["red_to_green_order"]["verdict"] == "red-to-green"


def test_a_gap_between_two_seen_greens_that_adds_tests_is_not_a_refactor_step(make_trial):
    trial = go_trial(make_trial)
    test1 = write(trial, "stopwatch_test.go", GO_TEST)
    go_test(trial, 1)
    impl = write(trial, "stopwatch.go", GO_STUB + "func New() {}\n")
    go_test(trial, 0)
    test2 = write(trial, "stopwatch_test.go", GO_TEST + "func TestStart(t *testing.T) {}\n")
    go_test(trial, 0)

    out = analyze(trial, {test1: "fail", impl: "pass", test2: "pass"},
                  totals={test1: 1, impl: 1, test2: 3})

    # The two new tests were never seen red.
    assert out["tdd_loop"] == {"cycles": 1, "tests_never_seen_red": 2, "refactor_steps": 0}


def test_a_gap_with_no_test_or_implementation_write_is_not_a_refactor_step(make_trial):
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    go_test(trial, 0)
    write(trial, "README.md", "notes\n")
    go_test(trial, 0)
    go_test(trial, 0)

    out = analyze(trial, {test: "pass"})

    assert out["tdd_loop"] == {"cycles": 0, "tests_never_seen_red": 0, "refactor_steps": 0}


def test_seen_states_of_one_color_in_a_row_count_as_one_for_cycles(make_trial):
    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    go_test(trial, 1)
    go_test(trial, 1)
    impl = write(trial, "stopwatch.go", GO_STUB + "func New() {}\n")
    go_test(trial, 0)
    broken = write(trial, "stopwatch.go", GO_STUB + "func New() {\n")
    go_test(trial, 2)
    fixed = write(trial, "stopwatch.go", GO_STUB + "func New() {}\n")
    go_test(trial, 0)

    out = analyze(trial, {test: "fail", impl: "pass", broken: "red-compile", fixed: "pass"})

    assert out["tdd_loop"]["cycles"] == 2


def test_main_reads_replay_and_agent_runs_from_the_analysis_folder(make_trial, tmp_path, capsys):
    import json

    from analyze.agent_runs import cross_check_job
    from analyze.trajectory import main

    trial = go_trial(make_trial)
    test = write(trial, "stopwatch_test.go", GO_TEST)
    red = go_test(trial, 1)
    impl = write(trial, "stopwatch.go", GO_STUB + "func New() {}\n")
    green = go_test(trial, 0)
    trial_dir = trial.build()
    analysis = tmp_path / "analysis"
    trial.write_replay({test: "fail", impl: "pass"},
                       analysis_dir=analysis / trial_dir.parent.name / trial_dir.name)
    cross_check_job(trial_dir.parent, analysis)

    assert main(["--analysis", str(analysis), str(trial_dir)]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["red_to_green_order"] == {
        "verdict": "red-to-green", "first_seen_red": red, "first_seen_green": green,
    }
    assert out["tdd_loop"] == {"cycles": 1, "tests_never_seen_red": 0, "refactor_steps": 0}
