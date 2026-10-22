"""Process metrics from one trial: pure functions over the trial reader's data.

    uv run python -m analyze.trajectory <trial folder>...

prints one JSON line per trial, to compare with the labeling sheet.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from analyze.languages import IMPLEMENTATION, TEST, classify
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


def analyze_trial(trial: Trial) -> dict:
    return {
        "trial": trial.name,
        "language": trial.language,
        "test_first_order": write_order(trial),
        "bash": bash_marks(trial),
    }


def main(argv: list[str]) -> int:
    for folder in argv:
        print(json.dumps(analyze_trial(read_trial(folder))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
