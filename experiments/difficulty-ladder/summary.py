"""The difficulty-ladder summary (PRD Part II, "The difficulty ladder").

`assay experiment difficulty-ladder` runs it after the evaluations, on every
invocation that completes. It writes analysis/difficulty-ladder/summary/
ladder-summary.md (for a person) and ladder-summary.json (every value), with
these sections, in order:

1. the pass grid: for each model tier · condition · language, each rung's
   score (`passed/total ✓` or `✗`, `timeout`, or `—` when it has no kept
   trial yet);
2. the rollup: for each model tier · condition · language, the passed trials
   (reward 1) of the kept ones, and the totals over all kept trials and the
   means per passed trial of the tokens, the cost and the agent time;
3. the missing trials, as in Phase 0;
4. the trials table: the Phase 0 columns, the rung, and the model and date of
   each local trial;
5. the total hosted cost, kept plus discarded, with no cap.

The trial values, the cells, the missing trials, the hosted cost and the
trials table come from assay.summary_parts, which the Phase 0 summary
shares. Discarded trials are in no section but the missing trials and the
hosted cost.

Options (`[summary] options = {...}` in experiment.toml): `usd_per_gbp`, the
rate that converts Claude Code's USD to GBP.
"""

from __future__ import annotations

import json
from pathlib import Path

from analyze.trial import ABSENT
from assay.summary import ExperimentView, PlanView, Summary, TrialView
from assay.summary_parts import (CELL_KEYS, TRIAL_COLUMNS, TRIAL_KEY, Column, cells,
                                 discard_causes, hosted_cost, missing_markdown, missing_trials,
                                 num, trial_values, trials_markdown)

SUMMARY_NAME = "ladder-summary"
USD_PER_GBP = 1.27
# The rungs, in ladder order (easiest first): the slug of each rung's task
# packs. This is the one place that orders them; the job files list the packs.
RUNGS = ("split-second-stopwatch", "wordy", "poker", "bowling", "two-bucket", "alphametics")
TIMEOUT = "AgentTimeoutError"  # Harbor's exception when the agent ran out of time


def check_options(options: dict, plan: PlanView) -> None:
    if unknown := sorted(set(options) - {"usd_per_gbp"}):
        raise ValueError(f"unknown option {', '.join(unknown)} (usd_per_gbp)")
    value = options.get("usd_per_gbp", 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"usd_per_gbp must be a number above 0, not {value!r}")


def summarize(view: ExperimentView, options: dict, out: Path) -> None:
    data = ladder_summary(view, options)
    (out / f"{SUMMARY_NAME}.json").write_text(json.dumps(data, indent=2) + "\n",
                                              encoding="utf-8")
    (out / f"{SUMMARY_NAME}.md").write_text(render_markdown(data), encoding="utf-8")


SUMMARY = Summary(summarize, check_options=check_options)


# --- The values -----------------------------------------------------------------


def ladder_summary(view: ExperimentView, options: dict) -> dict:
    trials = [_trial(t) for t in view.trials]
    # A rung that is not in RUNGS (a stand-in pack) goes after them.
    rungs = list(RUNGS) + sorted({t["rung"] for t in trials} - set(RUNGS))
    return {
        "rungs": rungs,
        "trials": trials,
        "grid": _grid(view, trials, rungs),
        "rollup": _rollup(view, trials),
        "cells": cells(view),
        "expected_trials": sum(view.expected.values()),
        "kept_trials": len(trials),
        "discard_causes": discard_causes(view.log),
        "missing_trials": missing_trials(view),
        "hosted_cost": hosted_cost(view, trials, options.get("usd_per_gbp", USD_PER_GBP)),
    }


def _trial(t: TrialView) -> dict:
    """The shared trial values, plus the ladder's own."""
    record = t.record
    return {**trial_values(t),
            "rung": Path(t.task_pack).parts[-1],
            "timeout": record.exception_type == TIMEOUT,
            "passed": (record.reward or {}).get("reward") == 1,
            "agent_time_sec": None if record.agent_time_sec is ABSENT else record.agent_time_sec,
            "started_at": record.started_at}


# The rollup's values of one trial. The local tier's cost is None, not 0: what
# Claude Code reports for a local model is no money cost (L5).
ROLLUP_VALUES = {
    "input_tokens": lambda t: t["cost"]["input_tokens"],
    "cache_tokens": lambda t: t["cost"]["cache_tokens"],
    "output_tokens": lambda t: t["cost"]["output_tokens"],
    "cost_usd": lambda t: None if t["local"] else t["cost"]["cost_usd"],
    "agent_time_sec": lambda t: t["agent_time_sec"],
}


def _total(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _mean(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _rollup(view: ExperimentView, trials: list[dict]) -> list[dict]:
    """For each row: the passed trials (reward 1) of the kept ones, the total
    of each value over every kept trial, and its mean over the passed trials
    only (None when there is none)."""
    out = []
    for row in _rows(view):
        kept = [t for t in trials if _in_row(t, row)]
        passed = [t for t in kept if t["passed"]]
        out.append({**row, "kept": len(kept), "passed": len(passed),
                    "totals": {k: _total([v(t) for t in kept])
                               for k, v in ROLLUP_VALUES.items()},
                    "means_per_passed_trial": {k: _mean([v(t) for t in passed])
                                               for k, v in ROLLUP_VALUES.items()}})
    return out


def _rows(view: ExperimentView) -> list[dict]:
    """One row for each cell, by model tier, then condition, then language."""
    return sorted(({k: c[k] for k in CELL_KEYS} for c in cells(view)),
                  key=lambda c: tuple(str(c[k]) for k in
                                      ("model_tier", "condition", "language", "harness")))


def _in_row(t: dict, row: dict) -> bool:
    return tuple((t["cell"] or {}).get(k) for k in CELL_KEYS) == tuple(row[k] for k in CELL_KEYS)


def _grid(view: ExperimentView, trials: list[dict], rungs: list[str]) -> list[dict]:
    """For each row and rung, each kept trial's score: the reference tests it
    passed of the total, its reward, and whether the agent ran out of time."""
    grid = []
    for row in _rows(view):
        scores = {rung: [] for rung in rungs}
        for t in trials:
            if _in_row(t, row):
                reward = t["reward"] or {}
                scores[t["rung"]].append({
                    "trial": f"{t['job']}/{t['trial']}",
                    "reference_passed": reward.get("reference_passed"),
                    "reference_total": reward.get("reference_total"),
                    "reward": reward.get("reward"), "timeout": t["timeout"]})
        grid.append({**row, "rungs": scores})
    return grid


# --- The markdown ---------------------------------------------------------------


def _label(row: dict) -> str:
    return f"{row['model_tier']} · {row['condition']} · {row['language']}"


def _score(score: dict) -> str:
    if score["timeout"]:
        return "timeout"
    passed, total = (("-" if v is None else v) for v in (score["reference_passed"],
                                                           score["reference_total"]))
    return f"{passed}/{total} {'✓' if score['reward'] == 1 else '✗'}"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
            *("| " + " | ".join(r) + " |" for r in rows)]


def render_markdown(summary: dict) -> str:
    lines = ["# Difficulty ladder summary", ""]
    lines += _grid_markdown(summary)
    lines += _rollup_markdown(summary)
    lines += missing_markdown(summary["missing_trials"], summary["expected_trials"])
    rungs = summary["rungs"]
    lines += trials_markdown(summary["trials"], TRIAL_COLUMNS_LADDER, (*TRIAL_KEY, *LADDER_KEY),
                             order=lambda t: (str(t["model_tier"]),
                                              str((t["cell"] or {}).get("condition")),
                                              t["language"], rungs.index(t["rung"]),
                                              t["job"], t["trial"]))
    h = summary["hosted_cost"]
    lines += ["", "## Total hosted cost", "",
              f"{num(h['total_usd'], 2)} USD: {num(h['kept_usd'], 2)} kept + "
              f"{num(h['discarded_usd'], 2)} discarded (£{h['total_gbp']:.2f} at "
              f"1 GBP = {h['usd_per_gbp']} USD). There is no cap."]
    return "\n".join(lines) + "\n"


def _local_model(t: dict) -> str:
    """A local trial's model and the date it started, so that results from
    different runs of the local server show; "-" for a hosted trial."""
    if not t["local"]:
        return "-"
    return f"{t['model_tier']}, {(t['started_at'] or '-')[:10]}"


def _ladder_columns(columns) -> tuple[Column, ...]:
    """The Phase 0 columns, with the rung after the language and the local
    model after the model tier."""
    out = []
    for c in columns:
        out.append(c)
        if c.header == "Model tier":
            out.append(Column("Local model", _local_model))
        if c.header == "Language":
            out.append(Column("Rung", lambda t: t["rung"]))
    return tuple(out)


TRIAL_COLUMNS_LADDER = _ladder_columns(TRIAL_COLUMNS)
LADDER_KEY = (
    "- **Local model:** the model name and the start date of a local trial, so that results "
    "from different runs of the local server show; **Rung:** the slug of the task pack.",
    "- **Seconds:** the whole trial; the rollup's agent time is the agent's run only.",
)


ROLLUP_COLUMNS = (  # the rollup value, its header, and its digits
    ("input_tokens", "Input tokens", 0),
    ("cache_tokens", "Cached tokens", 0),
    ("output_tokens", "Output tokens", 0),
    ("cost_usd", "USD", 2),
    ("agent_time_sec", "Agent time (s)", 0),
)


def _rollup_markdown(summary: dict) -> list[str]:
    header = ["Model tier · condition · language", "Passed"]
    for _, name, _ in ROLLUP_COLUMNS:
        header += [name, f"{name} per passed trial"]
    rows = []
    for r in summary["rollup"]:
        cells = [_label(r), f"{r['passed']} of {r['kept']}" if r["kept"] else "-"]
        for key, _, digits in ROLLUP_COLUMNS:
            cells += [num(r["totals"][key], digits),
                      num(r["means_per_passed_trial"][key], digits)]
        rows.append(cells)
    return ["## Rollup", "", *_table(header, rows), "",
            "Passed: the kept trials with reward 1, of all the kept trials of the row; "
            "discarded trials are not counted. The totals count every kept trial. Failed "
            "trials count in the totals but not in the means per passed trial. `-`: no passed "
            "trial for a mean, or the local tier's cost, which is no money cost (L5). "
            "Agent time is the agent's run only, without the container setup, the harness "
            "installation and the verifier.", ""]


def _grid_markdown(summary: dict) -> list[str]:
    rows = [[_label(row)] + [", ".join(_score(s) for s in row["rungs"][rung]) or "—"
                             for rung in summary["rungs"]]
            for row in summary["grid"]]
    return ["## Pass grid", "",
            *_table(["Model tier · condition · language", *summary["rungs"]], rows), "",
            "One column for each rung, easiest first. A cell gives the reference tests passed "
            "of the total, with ✓ when they all pass (reward 1) and ✗ otherwise; `timeout` "
            "when the agent ran out of time; `—` when the rung has no kept trial yet.", ""]
