"""The comparison of the labeling sheet with trajectory.py's output (spec #15;
PRD section 5, "How a person checks trajectory.py")."""

import csv
import json
import shutil
from pathlib import Path

from analyze.compare_labels import compare, main

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "labeling" / "sheet-template.csv"

AGREEING_ROW = {
    "trial": "stopwatch__abc1234",
    "test_first_verdict": "test-first",
    "first_test_write_step_id": "2",
    "first_test_write_position": "0",
    "first_test_write_path": "stopwatch_test.go",
    "first_implementation_write_step_id": "4",
    "first_implementation_write_position": "1",
    "first_implementation_write_path": "stopwatch.go",
    "test_first_note": "",
    "red_to_green_verdict": "red-to-green",
    "first_seen_red": "toolu_0003",
    "first_seen_green": "toolu_0006",
    "cycles": "1",
    "tests_never_seen_red": "0",
    "refactor_steps": "0",
    "red_to_green_note": "",
}

SCRIPT_LINE = {
    "trial": "stopwatch__abc1234",
    "language": "go",
    "test_first_order": {
        "verdict": "test-first",
        "first_test_write": {"step_id": 2, "position": 0, "path": "stopwatch_test.go"},
        "first_implementation_write": {"step_id": 4, "position": 1, "path": "stopwatch.go"},
    },
    "red_to_green_order": {
        "verdict": "red-to-green",
        "first_seen_red": "toolu_0003",
        "first_seen_green": "toolu_0006",
    },
    "tdd_loop": {"cycles": 1, "tests_never_seen_red": 0, "refactor_steps": 0},
    "bash": {"file_writing_bash": False, "bash_writes_test_or_implementation": False},
}


def write_sheet(tmp_path: Path, rows: list[dict]) -> Path:
    """Fills a copy of the committed template, as the person does."""
    sheet = tmp_path / "sheet.csv"
    shutil.copy(TEMPLATE, sheet)
    with sheet.open(newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    with sheet.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writerows(rows)
    return sheet


def write_output(tmp_path: Path, lines: list[dict]) -> Path:
    out = tmp_path / "trajectory.jsonl"
    out.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return out


def test_a_sheet_that_matches_the_script_agrees_on_both_metrics(tmp_path):
    report = compare(write_sheet(tmp_path, [AGREEING_ROW]), write_output(tmp_path, [SCRIPT_LINE]))

    assert report == {
        "trials": [{
            "trial": "stopwatch__abc1234",
            "test_first": {"agrees": True, "differences": []},
            "red_to_green": {"agrees": True, "differences": []},
        }],
        "only_in_sheet": [],
        "only_in_output": [],
        "agrees_every_time": {"test_first": True, "red_to_green": True},
    }


def test_each_difference_in_verdict_anchor_or_count_is_listed_under_its_metric(tmp_path):
    row = {**AGREEING_ROW,
           "first_implementation_write_position": "0",
           "first_seen_green": "toolu_0007",
           "refactor_steps": "1"}

    report = compare(write_sheet(tmp_path, [row]), write_output(tmp_path, [SCRIPT_LINE]))
    trial = report["trials"][0]

    assert trial["test_first"] == {"agrees": False, "differences": [
        {"field": "first_implementation_write_position", "sheet": "0", "script": "1"},
    ]}
    assert trial["red_to_green"] == {"agrees": False, "differences": [
        {"field": "first_seen_green", "sheet": "toolu_0007", "script": "toolu_0006"},
        {"field": "refactor_steps", "sheet": "1", "script": "0"},
    ]}
    assert report["agrees_every_time"] == {"test_first": False, "red_to_green": False}


def test_a_missing_anchor_is_a_blank_cell_and_agrees_with_a_null_anchor(tmp_path):
    row = {**AGREEING_ROW, "test_first_verdict": "no-implementation",
           "first_implementation_write_step_id": "",
           "first_implementation_write_position": "",
           "first_implementation_write_path": "",
           "test_first_note": "the agent wrote only the test"}
    line = json.loads(json.dumps(SCRIPT_LINE))
    line["test_first_order"].update(verdict="no-implementation", first_implementation_write=None)

    report = compare(write_sheet(tmp_path, [row]), write_output(tmp_path, [line]))

    assert report["trials"][0]["test_first"] == {"agrees": True, "differences": []}


def test_a_trial_on_one_side_only_is_reported_and_breaks_agrees_every_time(tmp_path):
    other = {**SCRIPT_LINE, "trial": "other__def5678"}

    report = compare(write_sheet(tmp_path, [AGREEING_ROW]),
                     write_output(tmp_path, [SCRIPT_LINE, other]))

    assert report["only_in_output"] == ["other__def5678"]
    assert report["only_in_sheet"] == []
    assert report["agrees_every_time"] == {"test_first": False, "red_to_green": False}


def write_results(tmp_path: Path, lines: list[dict]) -> Path:
    """trajectory's result.json of each trial, as `assay experiment` writes them."""
    root = tmp_path / "analysis" / "phase0-tdd"
    for i, line in enumerate(lines):
        folder = root / f"job-{i}" / line["trial"] / "trajectory"
        folder.mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps(
            {"evaluation": "trajectory", "value": line, "error": None}), encoding="utf-8")
    return root


def test_the_experiment_folder_gives_trajectorys_result_json_of_each_trial(tmp_path):
    other = {**SCRIPT_LINE, "trial": "other__def5678"}
    root = write_results(tmp_path, [SCRIPT_LINE, other])
    # A replay result beside it is not a trajectory line.
    (root / "job-0" / "stopwatch__abc1234" / "replay").mkdir()
    (root / "job-0" / "stopwatch__abc1234" / "replay" / "result.json").write_text(
        json.dumps({"evaluation": "replay", "value": {}, "error": None}), encoding="utf-8")

    report = compare(write_sheet(tmp_path, [AGREEING_ROW]), root)

    assert report["trials"][0]["test_first"] == {"agrees": True, "differences": []}
    assert report["trials"][0]["red_to_green"] == {"agrees": True, "differences": []}
    assert report["only_in_output"] == ["other__def5678"]


def test_a_trajectory_result_with_an_error_gives_no_line(tmp_path):
    root = write_results(tmp_path, [SCRIPT_LINE])
    result = root / "job-0" / "stopwatch__abc1234" / "trajectory" / "result.json"
    result.write_text(json.dumps({"evaluation": "trajectory", "value": None,
                                  "error": "dependency replay has an error"}), encoding="utf-8")

    report = compare(write_sheet(tmp_path, [AGREEING_ROW]), root)

    assert report["only_in_sheet"] == ["stopwatch__abc1234"]


def test_the_command_prints_each_difference_and_fails_when_any_exists(tmp_path, capsys):
    row = {**AGREEING_ROW, "test_first_verdict": "same-turn"}

    code = main([str(write_sheet(tmp_path, [row])), str(write_output(tmp_path, [SCRIPT_LINE]))])
    printed = capsys.readouterr().out

    assert code == 1
    assert "stopwatch__abc1234" in printed
    assert "test_first_verdict" in printed and "same-turn" in printed and "test-first" in printed
