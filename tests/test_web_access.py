"""The web-access mark: a trial that may have read the solution from the web
(spec #15, seam 1). Flagged trials stay in the data."""

from analyze.trajectory import analyze_trial
from analyze.trial import read_trial

TS_STUB = "export class SplitSecondStopwatch {}\n"


def ts_trial(make_trial):
    trial = make_trial("typescript")
    trial.seed({"split-second-stopwatch.ts": TS_STUB, "package.json": "{}\n"})
    return trial


def web_access(trial):
    return analyze_trial(read_trial(trial.build()))["web_access"]


def test_a_successful_web_fetch_flags_the_trial_at_its_step(make_trial):
    # The phase0-smoke trial: two WebFetch calls in one step, after a ToolSearch.
    trial = ts_trial(make_trial)
    trial.step().call("ToolSearch", {"query": "select:WebFetch", "max_results": 1})
    step = trial.step()
    step.call("WebFetch", {"url": "https://raw.githubusercontent.com/exercism/typescript/main/"
                                  "exercises/practice/split-second-stopwatch/.meta/proof.ci.ts"},
              result="export class SplitSecondStopwatch { ... }")
    step.call("WebFetch", {"url": "https://raw.githubusercontent.com/exercism/typescript/main/"
                                  "exercises/practice/split-second-stopwatch/"
                                  "split-second-stopwatch.test.ts"},
              result="I can't return the full file verbatim ...")

    assert web_access(trial) == {"flagged": True, "step_ids": [3]}


def test_a_denied_web_search_does_not_flag_the_trial(make_trial):
    trial = ts_trial(make_trial)
    trial.step().call("WebSearch", {"query": "exercism split second stopwatch"},
                      result="Permission to use WebSearch has been denied.", is_error=True)

    assert web_access(trial) == {"flagged": False, "step_ids": []}


def test_bash_commands_that_reach_the_web_flag_the_trial(make_trial):
    trial = ts_trial(make_trial)
    trial.step().call("Bash", {"command": "curl -s https://example.com/proof.ts > /tmp/p.ts"})
    trial.step().call("Bash", {"command": "wget -q example.com/x"})
    trial.step().call("Bash", {"command": "git clone github.com/exercism/typescript /tmp/x"})
    trial.step().call("Bash", {"command": "corepack yarn jest 2>&1 | tail -5"})

    assert web_access(trial) == {"flagged": True, "step_ids": [2, 3, 4]}


def test_a_url_in_a_heredoc_body_does_not_flag_the_trial(make_trial):
    trial = ts_trial(make_trial)
    trial.step().call("Bash", {"command": (
        "cat > notes.ts <<'EOF'\n// see https://exercism.org/docs\nEOF")})

    assert web_access(trial) == {"flagged": False, "step_ids": []}
