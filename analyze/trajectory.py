"""Process metrics from one trial: pure functions over the trial reader's data.

    uv run assay trajectory results/<job-id>... [--analysis analysis]

writes analysis/trajectory.jsonl, one JSON line for each trial of each job, to
compare with the labeling sheet. Red-to-green order and the TDD loop need
analysis/<job-id>/<trial>/replay.jsonl and agent-runs.jsonl (from assay replay
and assay agent-runs); without them both are null.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from analyze.agent_runs import AGENT_RUNS_FILE, SEED_REPOSITORY, read_agent_runs
from analyze.languages import IMPLEMENTATION, LANGUAGES, TEST, classify, is_test_file
from analyze.replay import FAIL, PASS, RED_COMPILE, REPLAY_FILE, read_replay
from analyze.shell import simple_commands, without_heredoc_bodies, without_prefixes, written_paths
from analyze.trial import REPO_ROOT, ToolCall, Trial, read_job, read_trial, write_jsonl

TRAJECTORY_FILE = "trajectory.jsonl"
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


@dataclass(frozen=True)
class TestWrite:
    __test__ = False  # not a pytest class

    step_id: int
    position: int
    path: str  # relative to the seed repository, or absolute outside it
    source: str  # "trace", "tool" (a file tool's file_path) or "bash" (a redirection)
    kept: bool  # the final snapshot holds the file

    def anchor(self) -> dict:
        out = {"step_id": self.step_id, "position": self.position, "path": self.path}
        return out if self.kept else {**out, "kept": False, "source": self.source}


def test_writes(trial: Trial) -> list[TestWrite]:
    """Writes of test files in ATIF order, from the trace and from Bash redirections.

    A file written and deleted in one Bash call leaves no trace change, so the
    redirection is the only sign of it. Each file appears once a call.
    """
    final = next((line.commit for line in reversed(trial.trace) if line.commit), None)

    def kept(path: str) -> bool:
        return (final is not None and not path.startswith("/")
                and trial.snapshot_file(final, path) is not None)

    writes = []
    for call in trial.tool_calls:
        seen = set()
        for line in trial.trace_lines_for(call.tool_use_id):
            for change in line.paths:
                if change.status in WRITE_STATUSES and classify(trial.language, change.path) == TEST:
                    seen.add(change.path)
                    writes.append(TestWrite(call.step_id, call.position, change.path,
                                            "trace", kept(change.path)))
        for source, raw in _named_writes(call):
            path = _repository_path(raw)
            if path not in seen and is_test_file(trial.language, path):
                seen.add(path)
                writes.append(TestWrite(call.step_id, call.position, path, source, kept(path)))
    return writes


FILE_TOOLS = ("Write", "Edit", "MultiEdit")


def _named_writes(call: ToolCall) -> list[tuple[str, str]]:
    """(source, path) for each file a call names as written: the file_path of
    a file tool that did not fail, or a Bash redirection."""
    if call.function_name in FILE_TOOLS and call.is_error is not True:
        path = call.arguments.get("file_path")
        return [("tool", path)] if isinstance(path, str) else []
    command = call.arguments.get("command") if call.function_name == "Bash" else None
    return [("bash", p) for p in written_paths(command)] if isinstance(command, str) else []


def ad_hoc_runs(trial: Trial) -> dict:
    """Bash calls that run, with a script runner of the language, a file the
    agent wrote in that call or before it. A call counts once."""
    runners = [r.split() for r in LANGUAGES[trial.language].script_runners]
    written: set[str] = set()
    steps = []
    for call in trial.tool_calls:
        for line in trial.trace_lines_for(call.tool_use_id):
            written.update(_absolute(c.path) for c in line.paths if c.status in WRITE_STATUSES)
        written.update(_absolute(path) for _, path in _named_writes(call))
        command = call.arguments.get("command") if call.function_name == "Bash" else None
        if isinstance(command, str) and any(
                _absolute(script) in written
                for script in _scripts_run(without_heredoc_bodies(command), runners)):
            steps.append(call.step_id)
    return {"count": len(steps), "first_step_id": steps[0] if steps else None}


WEB_TOOLS = ("WebFetch", "WebSearch")
_URL = re.compile(r"\bhttps?://")


def web_access(trial: Trial) -> dict:
    """The steps where the agent may have reached the web: a web tool call that
    did not fail, or a Bash command with a URL, curl, wget or git clone (a
    heuristic: curl localhost is flagged, node -e "fetch(...)" is missed)."""
    steps = []
    for call in trial.tool_calls:
        if call.function_name in WEB_TOOLS:
            reached = call.is_error is not True
        elif call.function_name == "Bash" and isinstance(call.arguments.get("command"), str):
            text = without_heredoc_bodies(call.arguments["command"])
            reached = bool(_URL.search(text)) or any(
                words[:1] in (["curl"], ["wget"]) or words[:2] == ["git", "clone"]
                for words in map(without_prefixes, simple_commands(text)))
        else:
            reached = False
        if reached and call.step_id not in steps:
            steps.append(call.step_id)
    return {"flagged": bool(steps), "step_ids": steps}


def _scripts_run(command: str, runners: list[list[str]]) -> list[str]:
    """The file each runner in the command runs: its first argument that is not a flag."""
    scripts = []
    for words in simple_commands(command):
        words = without_prefixes(words)
        runner = next((r for r in runners if words[:len(r)] == r), None)
        if runner is not None:
            scripts += [w for w in words[len(runner):] if not w.startswith("-")][:1]
    return scripts


def _absolute(path: str) -> str:
    return posixpath.normpath(posixpath.join(SEED_REPOSITORY, path))


def _repository_path(path: str) -> str:
    """A path the agent named, relative to the seed repository when inside it."""
    full = _absolute(path)
    if full.startswith(SEED_REPOSITORY + "/"):
        return full[len(SEED_REPOSITORY) + 1:]
    return full


def write_order(trial: Trial) -> dict:
    """Test-first order: the verdict and its two anchors (PRD section 5).

    Only kept test files order against the implementation. When the agent
    kept none but wrote some, the verdict is throwaway-tests.
    """
    writes = file_writes(trial)
    tests = test_writes(trial)
    test = next((t for t in tests if t.kept), None)
    impl = next((w for w in writes if w.file_class == IMPLEMENTATION), None)
    if impl is None:
        verdict = "no-implementation"
        test = test or next(iter(tests), None)
    elif test is None and tests:
        verdict = "throwaway-tests"
        test = tests[0]
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
        "ad_hoc_runs": ad_hoc_runs(trial),
        "web_access": web_access(trial),
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


def write_trajectory(job_dirs: list[Path | str], analysis_root: Path | str) -> Path:
    """Writes analysis_root/trajectory.jsonl, a line for each trial of each job
    in turn, over any earlier file; returns its path."""
    lines = [analyze_folder(trial.path, analysis_root)
             for job_dir in job_dirs for trial in read_job(job_dir)]
    output = Path(analysis_root) / TRAJECTORY_FILE
    output.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output, lines)
    return output


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="assay trajectory",
        description=f"Write the process metrics of each trial of one or more jobs to "
                    f"analysis/{TRAJECTORY_FILE}, one JSON line each.")
    parser.add_argument("job_dirs", nargs="+", type=Path, help="results/<job-id>")
    parser.add_argument("--analysis", type=Path, default=REPO_ROOT / "analysis",
                        help=f"analysis root holding <job-id>/<trial>/replay.jsonl and "
                             f"agent-runs.jsonl; {TRAJECTORY_FILE} goes here")
    args = parser.parse_args(argv)
    print(f"wrote {write_trajectory(args.job_dirs, args.analysis)}")
    return 0
