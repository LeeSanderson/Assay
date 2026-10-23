"""Throwaway tests: test files the agent wrote but did not keep (spec #15, seam 1).

A test write comes from the trace, from the file_path of a Write, Edit or
MultiEdit call, or from a redirection in a Bash command. A test file is kept
when the final snapshot holds it.
"""

from analyze.trajectory import analyze_trial
from analyze.trial import read_trial

TS_STUB = "export class SplitSecondStopwatch {}\n"
TS_IMPL = "export class SplitSecondStopwatch { state = 'ready' }\n"


def ts_trial(make_trial):
    trial = make_trial("typescript")
    trial.seed({"split-second-stopwatch.ts": TS_STUB, "package.json": "{}\n"})
    return trial


def run(trial):
    return analyze_trial(read_trial(trial.build()))


def test_a_test_written_run_and_deleted_in_one_bash_call_is_a_throwaway_test(make_trial):
    # The phase0-smoke trial: the Bash call leaves no trace change.
    trial = ts_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/split-second-stopwatch.ts"},
                      files={"split-second-stopwatch.ts": TS_IMPL})
    trial.step().call("Bash", {"command": (
        "corepack yarn prettier --write split-second-stopwatch.ts >/dev/null && "
        "cat > /app/tmp-stopwatch.test.ts <<'EOF'\n"
        "import { SplitSecondStopwatch } from './split-second-stopwatch'\n"
        "test('flow', () => {\n"
        "  expect(new SplitSecondStopwatch().state).toBe('ready')\n"
        "})\n"
        "EOF\n"
        "corepack yarn jest tmp-stopwatch 2>&1 | tail -15; rm -f /app/tmp-stopwatch.test.ts")})

    assert run(trial)["test_first_order"] == {
        "verdict": "throwaway-tests",
        "first_test_write": {"step_id": 3, "position": 0, "path": "tmp-stopwatch.test.ts",
                             "kept": False, "source": "bash"},
        "first_implementation_write": {"step_id": 2, "position": 0,
                                       "path": "split-second-stopwatch.ts"},
    }


def test_a_traced_test_deleted_later_is_a_throwaway_test(make_trial):
    trial = ts_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/try.test.ts"},
                      files={"try.test.ts": "test('x', () => {})\n"})
    trial.step().call("Edit", {"file_path": "/app/split-second-stopwatch.ts"},
                      files={"split-second-stopwatch.ts": TS_IMPL})
    trial.step().call("Bash", {"command": "rm try.test.ts"}, delete=["try.test.ts"])

    out = run(trial)["test_first_order"]
    assert out["verdict"] == "throwaway-tests"
    assert out["first_test_write"] == {"step_id": 2, "position": 0, "path": "try.test.ts",
                                       "kept": False, "source": "trace"}


def test_a_kept_test_orders_against_the_implementation_past_an_earlier_throwaway(make_trial):
    trial = ts_trial(make_trial)
    trial.step().call("Write", {"file_path": "/tmp/scratch.test.ts", "content": "x"})
    trial.step().call("Edit", {"file_path": "/app/split-second-stopwatch.ts"},
                      files={"split-second-stopwatch.ts": TS_IMPL})
    trial.step().call("Write", {"file_path": "/app/split-second-stopwatch.test.ts"},
                      files={"split-second-stopwatch.test.ts": "test('x', () => {})\n"})

    assert run(trial)["test_first_order"] == {
        "verdict": "implementation-first",
        "first_test_write": {"step_id": 4, "position": 0, "path": "split-second-stopwatch.test.ts"},
        "first_implementation_write": {"step_id": 3, "position": 0,
                                       "path": "split-second-stopwatch.ts"},
    }
