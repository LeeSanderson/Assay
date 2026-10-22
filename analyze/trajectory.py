"""Process metrics from one trial: pure functions over the trial reader's data.

    uv run python -m analyze.trajectory [--analysis analysis] <trial folder>...

prints one JSON line per trial, to compare with the labeling sheet. Red-to-green
order and the TDD loop need analysis/<job-id>/<trial>/replay.jsonl and
agent-runs.jsonl (from analyze.replay and analyze.agent_runs); without them
both are null.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from analyze.agent_runs import AGENT_RUNS_FILE, read_agent_runs
from analyze.languages import IMPLEMENTATION, TEST, classify
from analyze.replay import FAIL, PASS, RED_COMPILE, REPLAY_FILE, REPO_ROOT, read_replay
from analyze.trial import Trial, read_trial

WRITE_STATUSES = ("A", "M")


@dataclass(frozen=True)
class FileWrite:
    step_id: int
    position: int
    path: str
    file_class: str
    function_name: str

    def anchor(self) -> dict:
        return {"step_id": self.step_id, "position": self.position, "path": self.path}


def file_writes(trial: Trial) -> list[FileWrite]:
    """File writes in ATIF order: A/M paths in each tool call's trace line.

    The tool has no effect; a call with no trace change makes no write, and the
    seed line belongs to no tool call.
    """
    writes = []
    for call in trial.tool_calls:
        for line in trial.trace_lines_for(call.tool_use_id):
            for change in line.paths:
                if change.status in WRITE_STATUSES:
                    writes.append(FileWrite(
                        call.step_id, call.position, change.path,
                        classify(trial.language, change.path), call.function_name,
                    ))
    return writes


def write_order(trial: Trial) -> dict:
    """Test-first order: the verdict and its two anchors (PRD section 5)."""
    writes = file_writes(trial)
    test = next((w for w in writes if w.file_class == TEST), None)
    impl = next((w for w in writes if w.file_class == IMPLEMENTATION), None)
    if impl is None:
        verdict = "no-implementation"
    elif test is None:
        verdict = "no-test"
    elif test.step_id == impl.step_id:
        verdict = "same-turn"
    elif test.step_id < impl.step_id:
        verdict = "test-first"
    else:
        verdict = "implementation-first"
    return {
        "verdict": verdict,
        "first_test_write": test and test.anchor(),
        "first_implementation_write": impl and impl.anchor(),
    }


def bash_marks(trial: Trial) -> dict:
    """Whether a Bash call changed the repository, and whether one wrote a test
    or implementation file (Risk 2: offline replay cannot rebuild such a trial)."""
    bash_ids = {c.tool_use_id for c in trial.tool_calls if c.function_name == "Bash"}
    file_writing = any(
        line.changed is True for line in trial.trace if line.tool_use_id in bash_ids
    )
    classed = any(
        w.function_name == "Bash" and w.file_class in (TEST, IMPLEMENTATION)
        for w in file_writes(trial)
    )
    return {"file_writing_bash": file_writing, "bash_writes_test_or_implementation": classed}


INSTRUMENT_SKILL = "tdd"


def skill_load(trial: Trial) -> dict:
    """Whether a successful Skill call loaded the instrument skill, and whether
    it came before the first file write (PRD section 5, "The phase 0 instrument")."""
    call = next((c for c in trial.tool_calls if c.function_name == "Skill"
                 and c.arguments.get("skill") == INSTRUMENT_SKILL and c.is_error is not True), None)
    first = next(iter(file_writes(trial)), None)
    return {
        "loaded": call is not None,
        "before_first_file_write": call is not None and (
            first is None or (call.step_id, call.position) < (first.step_id, first.position)),
    }


SEEN_RED = "red"
SEEN_GREEN = "green"


@dataclass(frozen=True)
class SeenState:
    tool_use_id: str
    step_id: int
    position: int
    color: str  # SEEN_RED or SEEN_GREEN
    tests_total: int  # agent_tests_total of the snapshot the run applies to


def seen_states(replay: list[dict], runs: list[dict]) -> list[SeenState]:
    """The seen states of one trial, in ATIF order (PRD section 5).

    A test run gives a seen state when it agrees with the replay: exit code
    not 0 on a fail or red-compile snapshot (seen red), or exit code 0 on a
    pass snapshot (seen green). A partial run counts. A run on a no-tests
    snapshot, or with no exit code or no test state, gives none.
    """
    snapshots = {line["seq"]: line for line in replay}
    seen = []
    for run in runs:
        code = run["exit_code"]
        snapshot = snapshots.get(run["snapshot_seq"], {})
        state = snapshot.get("test_state")
        if code is None:
            continue
        if code != 0 and state in (FAIL, RED_COMPILE):
            color = SEEN_RED
        elif code == 0 and state == PASS:
            color = SEEN_GREEN
        else:
            continue
        seen.append(SeenState(run["tool_use_id"], run["step_id"], run["position"],
                              color, snapshot.get("agent_tests_total") or 0))
    return seen


def red_to_green_order(seen: list[SeenState]) -> dict:
    """Red-to-green order: the verdict and the tool_use_id of the first seen
    red and the first seen green (PRD section 5)."""
    red = next((s for s in seen if s.color == SEEN_RED), None)
    green = next((s for s in seen if s.color == SEEN_GREEN), None)
    if not seen:
        verdict = "not-observed"
    elif seen[0].color == SEEN_GREEN:
        verdict = "green-first"
    elif green is None:
        verdict = "never-green"
    else:
        verdict = "red-to-green"
    return {
        "verdict": verdict,
        "first_seen_red": red and red.tool_use_id,
        "first_seen_green": green and green.tool_use_id,
    }


def tdd_loop(seen: list[SeenState], writes: list[FileWrite]) -> dict:
    """The TDD loop: cycles, tests never seen red, and refactor steps (PRD section 5).

    Seen states of one color in a row count as one, so a cycle is a change
    from seen red to seen green. For each two seen greens in a row (no seen
    red between them), the increase of agent_tests_total adds to the tests
    never seen red, and the gap is a refactor step when it has a test or
    implementation write and agent_tests_total does not change.
    """
    cycles = sum(1 for a, b in zip(seen, seen[1:]) if a.color == SEEN_RED and b.color == SEEN_GREEN)
    never_red = 0
    refactors = 0
    for a, b in zip(seen, seen[1:]):
        if a.color != SEEN_GREEN or b.color != SEEN_GREEN:
            continue
        never_red += max(0, b.tests_total - a.tests_total)
        start, end = (a.step_id, a.position), (b.step_id, b.position)
        edited = any(
            w.file_class in (TEST, IMPLEMENTATION) and start < (w.step_id, w.position) < end
            for w in writes
        )
        if edited and b.tests_total == a.tests_total:
            refactors += 1
    return {"cycles": cycles, "tests_never_seen_red": never_red, "refactor_steps": refactors}


def analyze_trial(trial: Trial, replay: list[dict] | None = None,
                  runs: list[dict] | None = None) -> dict:
    """The metrics of one trial. Red-to-green order and the TDD loop need the
    trial's replay.jsonl and agent-runs.jsonl lines; without them both are None."""
    out = {
        "trial": trial.name,
        "language": trial.language,
        "test_first_order": write_order(trial),
        "red_to_green_order": None,
        "tdd_loop": None,
        "bash": bash_marks(trial),
        "skill_load": skill_load(trial),
    }
    if replay is not None and runs is not None:
        seen = seen_states(replay, runs)
        out["red_to_green_order"] = red_to_green_order(seen)
        out["tdd_loop"] = tdd_loop(seen, file_writes(trial))
    return out


def analyze_folder(folder: Path | str, analysis_root: Path | str) -> dict:
    """analyze_trial for results/<job-id>/<trial>, with the replay.jsonl and
    agent-runs.jsonl in analysis_root/<job-id>/<trial>/ when both exist."""
    trial = read_trial(folder)
    out = Path(analysis_root) / Path(folder).resolve().parent.name / trial.name
    if (out / REPLAY_FILE).is_file() and (out / AGENT_RUNS_FILE).is_file():
        return analyze_trial(trial, read_replay(out), read_agent_runs(out))
    return analyze_trial(trial)


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m analyze.trajectory",
                                     description="Process metrics of each trial, one JSON line each.")
    parser.add_argument("trials", nargs="*", type=Path, help="results/<job-id>/<trial>")
    parser.add_argument("--analysis", type=Path, default=REPO_ROOT / "analysis",
                        help="analysis root holding <job-id>/<trial>/replay.jsonl and agent-runs.jsonl")
    args = parser.parse_args(argv)
    for folder in args.trials:
        print(json.dumps(analyze_folder(folder, args.analysis)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
