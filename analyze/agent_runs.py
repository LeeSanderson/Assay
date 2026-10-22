"""The cross-check with the agent's test runs (PRD section 5).

A Bash call is a test run when its command matches a test-run pattern of the
task pack's language (analyze.languages) and runs in the seed repository.
It runs after replay.py, from the replay.jsonl of each trial:

    uv run python -m analyze.agent_runs results/<job-id>

writes analysis/<job-id>/<trial>/agent-runs.jsonl and cross-check.json.
"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from analyze.languages import LANGUAGES, LanguageRules
from analyze.replay import PASS, REPO_ROOT, read_replay
from analyze.trial import ToolCall, Trial, read_job, read_jsonl, share, write_jsonl

AGENT_RUNS_FILE = "agent-runs.jsonl"
CROSS_CHECK_FILE = "cross-check.json"

SEED_REPOSITORY = "/app"  # the agent's working folder in the task image
_EXIT_CODE = re.compile(r"Exit code (\d+)")
_PUNCTUATION = "();<>|&\n"
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class TestRun:
    __test__ = False  # not a pytest class

    partial: bool  # the run selects a subset of the tests


def match_test_run(language: str, command: str) -> TestRun | None:
    """The test run in a Bash command, or None when the command runs no tests.

    The command is split into simple commands at ;, &&, ||, |, & and new
    lines. It starts in the seed repository; a cd to a folder outside it
    makes the simple commands after it not test runs.
    """
    rules = LANGUAGES[language]
    cwd = SEED_REPOSITORY
    runs: list[bool] = []  # the partial flag of each test run in the command
    for words in _simple_commands(command):
        words = _without_prefixes(words)
        if not words:
            continue
        if words[0] == "cd":
            cwd = _cd(cwd, words[1:])
            continue
        if not _inside(cwd):
            continue
        for pattern in rules.test_runs:
            prefix = pattern.split()
            if words[:len(prefix)] == prefix:
                runs.append(_partial(rules, words[len(prefix):]))
                break
    if not runs:
        return None
    # One exit code covers all the runs, so one partial run makes the call partial.
    return TestRun(partial=any(runs))


def exit_code(call: ToolCall) -> int | None:
    """0 for a successful call; N from "Exit code N" when tool_result_is_error.

    None when the call has no result, or a failed result gives no exit code
    (for example an interrupted call).
    """
    if call.result is None:
        return None
    if not call.is_error:
        return 0
    found = _EXIT_CODE.match(call.result)
    return int(found[1]) if found else None


def agent_runs(trial: Trial, replay: list[dict]) -> list[dict]:
    """One agent-runs.jsonl line for each test run in the trial, in ATIF order.

    Each run applies to the last snapshot before the run's own trace line.
    The run agrees with the replay when both give a pass or both do not
    (fail and red-compile are the same here); a partial run, or one with no
    exit code or no replay test state, has no agreement value (None).
    """
    states = {line["seq"]: line for line in replay}
    lines = []
    for call in trial.tool_calls:
        if call.function_name != "Bash":
            continue
        command = call.arguments.get("command")
        run = match_test_run(trial.language, command) if isinstance(command, str) else None
        if run is None:
            continue
        own = trial.trace_lines_for(call.tool_use_id)
        snapshot = trial.snapshot_before(own[0]) if own else None
        code = exit_code(call)
        state = states.get(snapshot.seq, {}).get("test_state") if snapshot else None
        agrees = None
        if not run.partial and code is not None and state is not None:
            agrees = (code == 0) == (state == PASS)
        lines.append({
            "tool_use_id": call.tool_use_id,
            "step_id": call.step_id,
            "position": call.position,
            "command": command,
            "partial": run.partial,
            "exit_code": code,
            "snapshot_seq": snapshot and snapshot.seq,
            "snapshot_commit": snapshot and snapshot.commit,
            "snapshot_tool_use_id": snapshot and snapshot.tool_use_id,
            "test_state": state,
            "agrees": agrees,
        })
    return lines


def cross_check(replay: list[dict], runs: list[dict]) -> dict:
    """Coverage and agreement of one trial's test runs (PRD section 5).

    Coverage: the share of snapshots with a test run after them and before
    the next snapshot (a partial run counts). Agreement: the share of the
    runs that are not partial and agree with the replay, out of those with
    an agreement value. A share with no denominator is None. differences
    lists the tool_use_id of each run that does not agree.
    """
    snapshots = {line["seq"] for line in replay}
    covered = snapshots & {run["snapshot_seq"] for run in runs}
    compared = [run for run in runs if run["agrees"] is not None]
    agreeing = [run for run in compared if run["agrees"]]
    return {
        "snapshots": len(snapshots),
        "covered_snapshots": len(covered),
        "coverage": share(len(covered), len(snapshots)),
        "test_runs": len(runs),
        "partial_runs": sum(1 for run in runs if run["partial"]),
        "compared_runs": len(compared),
        "agreeing_runs": len(agreeing),
        "agreement": share(len(agreeing), len(compared)),
        "differences": [run["tool_use_id"] for run in compared if not run["agrees"]],
    }


def cross_check_job(job_dir: Path | str, analysis_root: Path | str) -> dict[str, dict]:
    """Cross-checks each trial of a job against its replay.jsonl.

    For each trial it reads analysis/<job-id>/<trial>/replay.jsonl and writes
    agent-runs.jsonl and cross-check.json (the cross_check summary) beside
    it. It never writes in job_dir. Returns the summary of each trial.
    """
    job_dir = Path(job_dir)
    summaries = {}
    for trial in read_job(job_dir):
        out = Path(analysis_root) / job_dir.name / trial.name
        replay = read_replay(out)
        runs = agent_runs(trial, replay)
        summary = cross_check(replay, runs)
        (out / AGENT_RUNS_FILE).write_text(
            "".join(json.dumps(run) + "\n" for run in runs), encoding="utf-8")
        (out / CROSS_CHECK_FILE).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        summaries[trial.name] = summary
    return summaries


def read_agent_runs(trial_out: Path | str) -> list[dict]:
    """The lines of analysis/<job-id>/<trial>/agent-runs.jsonl, in ATIF order.

    Each line: tool_use_id, step_id, position, command, partial, exit_code,
    snapshot_seq, snapshot_commit and snapshot_tool_use_id (the snapshot the
    run applies to; snapshot_seq joins replay.jsonl's seq), test_state (from
    the replay) and agrees (None for a partial run).
    """
    return read_jsonl(Path(trial_out) / AGENT_RUNS_FILE)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m analyze.agent_runs",
        description="Cross-check the agent's test runs with the replay, for each trial of a job.")
    parser.add_argument("job_dir", type=Path, help="results/<job-id>")
    parser.add_argument("--analysis", type=Path, default=REPO_ROOT / "analysis",
                        help="analysis root holding <job-id>/<trial>/replay.jsonl")
    args = parser.parse_args(argv)
    for name, summary in cross_check_job(args.job_dir, args.analysis).items():
        print(json.dumps({"trial": name, **summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



def _partial(rules: LanguageRules, args: list[str]) -> bool:
    args = iter(a for a in args if a != "--")  # npm test -- <args to jest>
    for arg in args:
        if not arg.startswith("-"):
            if rules.positional_selects:
                return True
            continue
        name = arg.split("=", 1)[0]
        if name in rules.selecting_flags:
            return True
        if name in rules.value_flags and "=" not in arg:
            next(args, None)
    return False


def _simple_commands(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes
        tokens = command.split()
    commands: list[list[str]] = [[]]
    redirect = False
    for token in tokens:
        if redirect:
            redirect = False  # the redirection's target
        elif token and all(c in _PUNCTUATION for c in token):
            if "<" in token or ">" in token:
                redirect = True  # the next word is the target: the file, or the 1 of 2>&1
                if commands[-1] and commands[-1][-1].isdigit():
                    commands[-1].pop()  # the 2 of 2>file
            else:
                commands.append([])
        else:
            commands[-1].append(token)
    return [c for c in commands if c]


def _without_prefixes(words: list[str]) -> list[str]:
    """Drops VAR=value assignments and the wrappers time and timeout <duration>."""
    while words:
        if _ASSIGNMENT.match(words[0]) or words[0] == "time":
            words = words[1:]
        elif words[0] == "timeout":
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
            words = rest[1:]  # the duration
        else:
            break
    return words


def _cd(cwd: str, args: list[str]) -> str:
    if not args:
        return "~"  # the home folder, outside the seed repository
    target = args[0]
    if target.startswith(("~", "$", "-")):
        return "~"  # a folder this check cannot know
    return posixpath.normpath(posixpath.join(cwd, target))


def _inside(cwd: str) -> bool:
    return cwd == SEED_REPOSITORY or cwd.startswith(SEED_REPOSITORY + "/")
