"""The neutral jq listing for the person check (spec #15; PRD section 5,
"How a person checks trajectory.py" and its red-to-green extension).

The listing is jq, not Python: these tests run analyze/listing.jq on a
fake trial folder with its analysis/ outputs. They skip when jq is not
on the PATH.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from analyze.agent_runs import agent_runs
from analyze.replay import read_replay
from analyze.trial import read_trial
from tests.trial_builder import TrialBuilder

REPO_ROOT = Path(__file__).resolve().parents[1]
LISTING = REPO_ROOT / "analyze" / "listing.jq"
JQ = shutil.which("jq")

pytestmark = pytest.mark.skipif(JQ is None, reason="jq is not on the PATH")

GO_STUB = "package stopwatch\n"
GO_TEST = "package stopwatch\n\nfunc TestNew(t *testing.T) {}\n"


def listing(trial_dir: Path, analysis_dir: Path) -> list[str]:
    """Runs the listing command the README gives, and returns its lines."""
    trace = trial_dir / "artifacts" / "logs" / "artifacts" / "trace" / "trace.jsonl"
    done = subprocess.run(
        [JQ, "-r",
         "--slurpfile", "trace", str(trace),
         "--slurpfile", "replay", str(analysis_dir / "replay.jsonl"),
         "--slurpfile", "runs", str(analysis_dir / "agent-runs.jsonl"),
         "-f", str(LISTING),
         str(trial_dir / "agent" / "trajectory.json")],
        capture_output=True, text=True, check=True,
    )
    return done.stdout.splitlines()


def build_with_analysis(builder: TrialBuilder, states: dict) -> tuple[Path, Path]:
    """Builds the trial and writes replay.jsonl and agent-runs.jsonl beside it."""
    trial_dir = builder.build()
    out = builder.write_replay(states)
    write_agent_runs(trial_dir, out)
    return trial_dir, out


def write_agent_runs(trial_dir: Path, out: Path) -> None:
    runs = agent_runs(read_trial(trial_dir), read_replay(out))
    (out / "agent-runs.jsonl").write_text(
        "".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8")


def test_a_red_then_green_trial_lists_each_call_with_its_trace_paths_runs_and_snapshots(tmp_path):
    b = TrialBuilder(tmp_path, language="go")
    b.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
    s2 = b.step()
    write_test = s2.call("Write", {"file_path": "/app/stopwatch_test.go", "content": GO_TEST},
                         files={"stopwatch_test.go": GO_TEST})
    s2.call("Read", {"file_path": "/app/stopwatch.go"})
    s3 = b.step()
    s3.call("Bash", {"command": "go test ./..."},
            result="Exit code 1\n--- FAIL: TestNew", is_error=True)
    s4 = b.step()
    edit = s4.call("Edit", {"file_path": "/app/stopwatch.go", "old_string": "a", "new_string": "b"},
                   files={"stopwatch.go": GO_STUB + "// done\n"})
    s5 = b.step()
    s5.call("Bash", {"command": "go test -run TestNew ./...\necho done"})

    trial_dir, out = build_with_analysis(b, {write_test: "fail", edit: "pass"})

    assert listing(trial_dir, out) == [
        "seed  paths=[A go.mod, A stopwatch.go]  test_state=no-tests agent_tests_total=0",
        '2.0  Write  "/app/stopwatch_test.go"  paths=[A stopwatch_test.go]'
        "  test_state=fail agent_tests_total=1",
        '2.1  Read  "/app/stopwatch.go"  paths=[]',
        '3.0  Bash  "go test ./..."  paths=[]  partial=false exit_code=1',
        '4.0  Edit  "/app/stopwatch.go"  paths=[M stopwatch.go]'
        "  test_state=pass agent_tests_total=1",
        '5.0  Bash  "go test -run TestNew ./...\\necho done"  paths=[]'
        "  partial=true exit_code=0",
    ]


def test_a_bash_write_lists_its_trace_paths_and_a_call_with_no_trace_line_says_so(tmp_path):
    b = TrialBuilder(tmp_path, language="go")
    b.seed({"stopwatch.go": GO_STUB})
    s2 = b.step()
    bash = s2.call("Bash", {"command": "cat > stopwatch_test.go <<EOF\nx\nEOF"},
                   files={"stopwatch_test.go": GO_TEST})
    s2.call("Glob", {"pattern": "*.go"}, traced=False)

    trial_dir, out = build_with_analysis(b, {bash: "red-compile"})

    assert listing(trial_dir, out)[1:] == [
        '2.0  Bash  "cat > stopwatch_test.go <<EOF\\nx\\nEOF"  paths=[A stopwatch_test.go]'
        "  test_state=red-compile agent_tests_total=1",
        '2.1  Glob  "*.go"  paths=-',
    ]


def test_a_failed_replay_of_a_snapshot_lists_its_error(tmp_path):
    b = TrialBuilder(tmp_path, language="go")
    b.seed({"stopwatch.go": GO_STUB})
    write = b.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                          files={"stopwatch_test.go": GO_TEST})
    trial_dir = b.build()
    out = b.write_replay(errors={write: "timeout"})
    write_agent_runs(trial_dir, out)

    assert listing(trial_dir, out)[1] == (
        '2.0  Write  "/app/stopwatch_test.go"  paths=[A stopwatch_test.go]  replay_error=timeout'
    )


def test_the_listing_gives_no_class_seen_state_verdict_or_agreement(tmp_path):
    b = TrialBuilder(tmp_path, language="go")
    b.seed({"stopwatch.go": GO_STUB})
    s2 = b.step()
    write = s2.call("Write", {"file_path": "/app/stopwatch_test.go"},
                    files={"stopwatch_test.go": GO_TEST})
    b.step().call("Bash", {"command": "go test ./..."},
                  result="Exit code 1\nFAIL", is_error=True)

    trial_dir, out = build_with_analysis(b, {write: "fail"})
    text = "\n".join(listing(trial_dir, out)).lower()

    for word in ("agree", "seen", "verdict", "test-first", "red-to-green",
                 "implementation", "class", "cycle", "count"):
        assert word not in text
