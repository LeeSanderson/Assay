"""Ad-hoc runs: Bash calls that run a script the agent wrote (spec #15, seam 1).

They are not test runs, so the cross-check never sees them.
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


def heredoc_and_run(path: str, word: str = "EOF") -> str:
    return (f"cat << '{word}' > {path}\n"
            "import { SplitSecondStopwatch } from '/app/split-second-stopwatch.ts';\n"
            "console.assert(new SplitSecondStopwatch().state === 'ready', 'ready');\n"
            f"{word}\n"
            f"npx tsx {path} 2>&1")


def test_scripts_the_agent_wrote_and_ran_with_tsx_are_ad_hoc_runs(make_trial):
    # The phase0-local trial: assertion scripts in /tmp, never a test file.
    trial = ts_trial(make_trial)
    trial.step().call("Write", {"file_path": "/app/split-second-stopwatch.ts"},
                      files={"split-second-stopwatch.ts": TS_IMPL})
    trial.step().call("Bash", {"command": heredoc_and_run("/tmp/verify.ts")},
                      result="Exit code 1\nError: Cannot find module", is_error=True)
    trial.step().call("Bash", {"command": heredoc_and_run("/tmp/verify.ts")})
    trial.step().call("Bash", {"command": heredoc_and_run("/tmp/verify2.ts", "SCRIPT")})
    trial.step().call("Bash", {"command": "yarn lint:ci 2>&1"})
    trial.step().call("Bash", {"command": "npx tsx /tmp/verify2.ts 2>&1"})
    trial.step().call("Bash", {"command": "rm -f /tmp/verify.ts /tmp/verify2.ts"})

    out = run(trial)

    assert out["test_first_order"]["verdict"] == "no-test"
    assert out["ad_hoc_runs"] == {"count": 4, "first_step_id": 3}


def test_running_a_file_the_agent_did_not_write_is_not_an_ad_hoc_run(make_trial):
    trial = ts_trial(make_trial)
    trial.step().call("Bash", {"command": "node scripts/build.js && npx tsx /tmp/other.ts"})

    assert run(trial)["ad_hoc_runs"] == {"count": 0, "first_step_id": None}
