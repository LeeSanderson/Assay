"""Test-first order (PRD section 5) over fake trial folders (spec #15, seam 1)."""

from analyze.trajectory import analyze_trial
from analyze.trial import read_trial

GO_STUB = "package stopwatch\n"


def go_trial(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
    return trial


def run(trial):
    return analyze_trial(read_trial(trial.build()))


def test_a_test_write_in_an_earlier_step_is_test_first(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch // test\n"})
    impl = trial.step()
    impl.call("Read", {"file_path": "/app/stopwatch.go"})
    impl.call("Edit", {"file_path": "/app/stopwatch.go"},
              files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    out = run(trial)

    assert out["test_first_order"] == {
        "verdict": "test-first",
        "first_test_write": {"step_id": 2, "position": 0, "path": "stopwatch_test.go"},
        "first_implementation_write": {"step_id": 3, "position": 1, "path": "stopwatch.go"},
    }


def test_an_implementation_write_in_an_earlier_step_is_implementation_first(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch // test\n"})

    out = run(trial)["test_first_order"]

    assert out["verdict"] == "implementation-first"
    assert out["first_test_write"] == {"step_id": 3, "position": 0, "path": "stopwatch_test.go"}
    assert out["first_implementation_write"] == {"step_id": 2, "position": 0, "path": "stopwatch.go"}


def test_both_writes_in_one_step_are_same_turn_even_when_the_test_comes_first(make_trial):
    trial = go_trial(make_trial)
    step = trial.step()
    step.call("Write", {"file_path": "/app/stopwatch_test.go"},
              files={"stopwatch_test.go": "package stopwatch // test\n"})
    step.call("Edit", {"file_path": "/app/stopwatch.go"},
              files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"] == {
        "verdict": "same-turn",
        "first_test_write": {"step_id": 2, "position": 0, "path": "stopwatch_test.go"},
        "first_implementation_write": {"step_id": 2, "position": 1, "path": "stopwatch.go"},
    }


def test_an_implementation_write_with_no_test_write_is_no_test(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"] == {
        "verdict": "no-test",
        "first_test_write": None,
        "first_implementation_write": {"step_id": 2, "position": 0, "path": "stopwatch.go"},
    }


def test_a_test_write_with_no_implementation_write_is_no_implementation(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch // test\n"})

    assert run(trial)["test_first_order"] == {
        "verdict": "no-implementation",
        "first_test_write": {"step_id": 2, "position": 0, "path": "stopwatch_test.go"},
        "first_implementation_write": None,
    }


def test_a_trial_with_no_writes_is_no_implementation(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"})

    assert run(trial)["test_first_order"]["verdict"] == "no-implementation"


def test_the_seed_repository_is_not_a_write(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "stopwatch_test.go": "package stopwatch\n"})
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"]["verdict"] == "no-test"


def test_a_bash_call_can_be_the_anchor(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Bash", {"command": "cat > stopwatch_test.go <<EOF ..."},
                      files={"stopwatch_test.go": "package stopwatch // test\n"})
    trial.step().call("Bash", {"command": "sed -i s/x/y/ stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"] == {
        "verdict": "test-first",
        "first_test_write": {"step_id": 2, "position": 0, "path": "stopwatch_test.go"},
        "first_implementation_write": {"step_id": 3, "position": 0, "path": "stopwatch.go"},
    }


def test_a_deleted_test_file_is_not_a_write(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "old_test.go": "package stopwatch\n"})
    trial.step().call("Bash", {"command": "rm old_test.go"}, delete=["old_test.go"])
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"]["verdict"] == "no-test"


def test_a_renamed_test_file_writes_its_new_path(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": GO_STUB, "old_test.go": "package stopwatch\n"})
    trial.step().call("Bash", {"command": "mv old_test.go new_test.go"},
                      files={"new_test.go": "package stopwatch\n"}, delete=["old_test.go"])
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    out = run(trial)["test_first_order"]
    assert out["verdict"] == "test-first"
    assert out["first_test_write"] == {"step_id": 2, "position": 0, "path": "new_test.go"}


def test_a_write_outside_the_seed_repository_is_neutral(make_trial):
    # The trace covers only the seed repository, so /tmp/try_test.go gives no path.
    trial = go_trial(make_trial)
    trial.step().call("Write", {"file_path": "/tmp/try_test.go", "content": "package x\n"})
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"]["verdict"] == "no-test"


def test_neutral_files_do_not_decide_the_verdict(make_trial):
    trial = go_trial(make_trial)
    step = trial.step()
    step.call("Write", {"file_path": "/app/README.md"}, files={"README.md": "notes\n"})
    step.call("Edit", {"file_path": "/app/go.mod"}, files={"go.mod": "module stopwatch\n\ngo 1.22\n"})
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": "package stopwatch // test\n"})

    out = run(trial)["test_first_order"]
    assert out["verdict"] == "no-implementation"
    assert out["first_test_write"] == {"step_id": 3, "position": 0, "path": "stopwatch_test.go"}


def test_a_failed_write_with_no_trace_change_is_not_a_write(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/stopwatch_test.go", "content": "x"},
                      result="File has not been read yet.", is_error=True)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"]["verdict"] == "no-test"


def test_a_failed_call_that_changed_a_file_is_a_write(make_trial):
    trial = go_trial(make_trial)
    trial.step().call("Bash", {"command": "echo ... > stopwatch_test.go; false"},
                      files={"stopwatch_test.go": "package stopwatch\n"},
                      result="Exit code 1", is_error=True)
    trial.step().call("Edit", {"file_path": "/app/stopwatch.go"},
                      files={"stopwatch.go": GO_STUB + "func New() {}\n"})

    assert run(trial)["test_first_order"]["verdict"] == "test-first"


def test_typescript_classes_test_files_and_leaves_config_neutral(make_trial):
    trial = make_trial("typescript")
    trial.seed({"split-second-stopwatch.ts": "export class Stopwatch {}\n",
                "package.json": "{}\n"})
    step = trial.step()
    step.call("Write", {"file_path": "/app/jest.config.ts"}, files={"jest.config.ts": "export default {}\n"})
    step.call("Write", {"file_path": "/app/babel.config.js"}, files={"babel.config.js": "module.exports = {}\n"})
    trial.step().call("Write", {"file_path": "/app/split-second-stopwatch.spec.ts"},
                      files={"split-second-stopwatch.spec.ts": "test('x', () => {})\n"})
    trial.step().call("Edit", {"file_path": "/app/split-second-stopwatch.ts"},
                      files={"split-second-stopwatch.ts": "export class Stopwatch { x = 1 }\n"})

    assert run(trial)["test_first_order"] == {
        "verdict": "test-first",
        "first_test_write": {"step_id": 3, "position": 0, "path": "split-second-stopwatch.spec.ts"},
        "first_implementation_write": {"step_id": 4, "position": 0, "path": "split-second-stopwatch.ts"},
    }


def test_typescript_dot_test_files_are_test_files(make_trial):
    trial = make_trial("typescript")
    trial.seed({"stopwatch.ts": "export {}\n"})
    trial.step().call("Edit", {"file_path": "/app/stopwatch.ts"}, files={"stopwatch.ts": "export const a = 1\n"})
    trial.step().call("Write", {"file_path": "/app/src/stopwatch.test.ts"},
                      files={"src/stopwatch.test.ts": "test('x', () => {})\n"})

    out = run(trial)["test_first_order"]
    assert out["verdict"] == "implementation-first"
    assert out["first_test_write"]["path"] == "src/stopwatch.test.ts"
