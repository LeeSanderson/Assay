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
shares; the grid, the rollup and the ladder columns are the ladder parts
there, which the codebase-ladder summary shares. Discarded trials are in no section but the missing trials and the
hosted cost.

Options (`[summary] options = {...}` in experiment.toml): `usd_per_gbp`, the
rate that converts Claude Code's USD to GBP.
"""

from __future__ import annotations

import json
from pathlib import Path

from assay.summary import ExperimentView, PlanView, Summary
from assay.summary_parts import (TRIAL_KEY, cells, check_number_options, discard_causes,
                                 grid_markdown, hosted_cost, hosted_cost_markdown,
                                 ladder_columns, ladder_grid, ladder_rollup, ladder_rungs,
                                 ladder_trial, ladder_trial_order, missing_markdown,
                                 missing_trials, rollup_markdown, trials_markdown)

SUMMARY_NAME = "ladder-summary"
USD_PER_GBP = 1.27
# The rungs, in ladder order (easiest first): the slug of each rung's task
# packs. This is the one place that orders them; the job files list the packs.
RUNGS = ("split-second-stopwatch", "wordy", "poker", "bowling", "two-bucket", "alphametics")


def check_options(options: dict, plan: PlanView) -> None:
    check_number_options(options, ("usd_per_gbp",))


def summarize(view: ExperimentView, options: dict, out: Path) -> None:
    data = ladder_summary(view, options)
    (out / f"{SUMMARY_NAME}.json").write_text(json.dumps(data, indent=2) + "\n",
                                              encoding="utf-8")
    (out / f"{SUMMARY_NAME}.md").write_text(render_markdown(data), encoding="utf-8")


SUMMARY = Summary(summarize, check_options=check_options)


def ladder_summary(view: ExperimentView, options: dict) -> dict:
    trials = [ladder_trial(t) for t in view.trials]
    rungs = ladder_rungs(RUNGS, trials)
    return {
        "rungs": rungs,
        "trials": trials,
        "grid": ladder_grid(view, trials, rungs),
        "rollup": ladder_rollup(view, trials),
        "cells": cells(view),
        "expected_trials": sum(view.expected.values()),
        "kept_trials": len(trials),
        "discard_causes": discard_causes(view.log),
        "missing_trials": missing_trials(view),
        "hosted_cost": hosted_cost(view, trials, options.get("usd_per_gbp", USD_PER_GBP)),
    }


TRIAL_COLUMNS_LADDER = ladder_columns()
LADDER_KEY = (
    "- **Local model:** the model name and the start date of a local trial, so that results "
    "from different runs of the local server show; **Rung:** the slug of the task pack.",
    "- **Seconds:** the whole trial; the rollup's agent time is the agent's run only.",
)
GRID_NOTE = (
    "One column for each rung, easiest first. A cell gives the reference tests passed "
    "of the total, with ✓ when they all pass (reward 1) and ✗ otherwise; `timeout` "
    "when the agent ran out of time; `—` when the rung has no kept trial yet.")


def render_markdown(summary: dict) -> str:
    lines = ["# Difficulty ladder summary", ""]
    lines += grid_markdown(summary, GRID_NOTE)
    lines += rollup_markdown(summary)
    lines += missing_markdown(summary["missing_trials"], summary["expected_trials"])
    lines += trials_markdown(summary["trials"], TRIAL_COLUMNS_LADDER, (*TRIAL_KEY, *LADDER_KEY),
                             order=ladder_trial_order(summary["rungs"]))
    lines += hosted_cost_markdown(summary["hosted_cost"])
    return "\n".join(lines) + "\n"