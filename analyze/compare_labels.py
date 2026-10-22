"""Compares the labeling sheet with trajectory.py's output (PRD section 5,
"How a person checks trajectory.py" and its red-to-green extension).

    uv run python -m analyze.trajectory <trial folder>... > trajectory.jsonl
    uv run python -m analyze.compare_labels <sheet.csv> trajectory.jsonl

The sheet is a filled copy of labeling/sheet-template.csv. The two agree on a
trial, for each metric, when every field of that metric is the same: for
test-first order the verdict and the two anchors; for red-to-green order the
verdict, the two anchors and the three counts of the TDD loop. Notes are not
compared. A blank cell is the same as a null value in the output (for
example the anchor of a write that does not occur).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# Each sheet column and the path of its value in a trajectory.py output line.
METRICS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "test_first": [
        ("test_first_verdict", ("test_first_order", "verdict")),
        ("first_test_write_step_id", ("test_first_order", "first_test_write", "step_id")),
        ("first_test_write_position", ("test_first_order", "first_test_write", "position")),
        ("first_test_write_path", ("test_first_order", "first_test_write", "path")),
        ("first_implementation_write_step_id",
         ("test_first_order", "first_implementation_write", "step_id")),
        ("first_implementation_write_position",
         ("test_first_order", "first_implementation_write", "position")),
        ("first_implementation_write_path",
         ("test_first_order", "first_implementation_write", "path")),
    ],
    "red_to_green": [
        ("red_to_green_verdict", ("red_to_green_order", "verdict")),
        ("first_seen_red", ("red_to_green_order", "first_seen_red")),
        ("first_seen_green", ("red_to_green_order", "first_seen_green")),
        ("cycles", ("tdd_loop", "cycles")),
        ("tests_never_seen_red", ("tdd_loop", "tests_never_seen_red")),
        ("refactor_steps", ("tdd_loop", "refactor_steps")),
    ],
}


def compare(sheet: Path | str, output: Path | str) -> dict:
    """The agreement of each trial on each metric, with each difference."""
    with Path(sheet).open(newline="", encoding="utf-8-sig") as f:
        rows = {row["trial"].strip(): row for row in csv.DictReader(f) if row.get("trial", "").strip()}
    lines = {}
    for text in Path(output).read_text(encoding="utf-8").splitlines():
        if text.strip():
            line = json.loads(text)
            lines[line["trial"]] = line

    trials = []
    for name in sorted(rows.keys() & lines.keys()):
        result = {"trial": name}
        for metric, fields in METRICS.items():
            differences = []
            for column, path in fields:
                labeled = (rows[name].get(column) or "").strip()
                computed = _text(_get(lines[name], path))
                if labeled != computed:
                    differences.append({"field": column, "sheet": labeled, "script": computed})
            result[metric] = {"agrees": not differences, "differences": differences}
        trials.append(result)

    only_in_sheet = sorted(rows.keys() - lines.keys())
    only_in_output = sorted(lines.keys() - rows.keys())
    complete = not only_in_sheet and not only_in_output
    return {
        "trials": trials,
        "only_in_sheet": only_in_sheet,
        "only_in_output": only_in_output,
        "agrees_every_time": {
            metric: complete and all(t[metric]["agrees"] for t in trials) for metric in METRICS
        },
    }


def _get(line: dict, path: tuple[str, ...]):
    value = line
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _text(value) -> str:
    return "" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m analyze.compare_labels",
        description="Compare the labeling sheet with trajectory.py's output.")
    parser.add_argument("sheet", type=Path, help="a filled copy of labeling/sheet-template.csv")
    parser.add_argument("output", type=Path, help="the JSON lines that analyze.trajectory prints")
    args = parser.parse_args(argv)

    report = compare(args.sheet, args.output)
    for trial in report["trials"]:
        verdicts = "  ".join(
            f"{metric}: {'agrees' if trial[metric]['agrees'] else 'differs'}" for metric in METRICS)
        print(f"{trial['trial']}  {verdicts}")
        for metric in METRICS:
            for d in trial[metric]["differences"]:
                print(f"  {d['field']}: sheet={d['sheet']!r} script={d['script']!r}")
    for name in report["only_in_sheet"]:
        print(f"{name}  only in the sheet")
    for name in report["only_in_output"]:
        print(f"{name}  only in the trajectory.py output")
    every = report["agrees_every_time"]
    print("agrees every time: " + "  ".join(f"{m}={every[m]}" for m in METRICS))
    return 0 if all(every.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
