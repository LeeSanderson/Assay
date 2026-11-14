"""The codebase-ladder summary (PRD section 20, "The summary"; issue #82).

`assay experiment codebase-ladder` runs it after the evaluations, on every
invocation that completes. It writes analysis/codebase-ladder/summary/
codebase-ladder-summary.md (for a person) and codebase-ladder-summary.json
(every value), with the sections of the difficulty-ladder summary, in order:

1. the pass grid: for each model tier · condition · language, each rung's
   score, rungs A to E (`passed/total ✓` or `✗`, `timeout`, or `—` when it
   has no kept trial yet). A trial that broke the seed suite adds its
   seed-suite count (`24/30 ✗ seed 38/40`), also when it completed the
   feature or timed out (`timeout seed 38/40`). The column of rung A names its task, poker, and a note says that
   each failure boundary is provisional while each cell has one repetition;
2. the rollup, 3. the missing trials, 4. the trials table and 5. the total
   hosted cost, as in the difficulty-ladder summary.

Everything but the seed-suite mark, the rung headers and the notes comes from
the ladder parts of assay.summary_parts, which the difficulty-ladder summary
shares.

Options (`[summary] options = {...}` in experiment.toml): `usd_per_gbp`, the
rate that converts Claude Code's USD to GBP.
"""

from __future__ import annotations

import json
from pathlib import Path

from assay.summary import ExperimentView, PlanView, Summary
from assay.summary_parts import (TRIAL_KEY, cells, check_number_options, discard_causes,
                                 grid_entry, grid_markdown, grid_score, hosted_cost,
                                 hosted_cost_markdown, ladder_columns, ladder_grid,
                                 ladder_rollup, ladder_rungs, ladder_trial, ladder_trial_order,
                                 missing_markdown, missing_trials, rollup_markdown,
                                 trials_markdown)

SUMMARY_NAME = "codebase-ladder-summary"
USD_PER_GBP = 1.27
# The rungs, in ladder order (A to E): the slug of each rung's task packs.
# This is the one place that orders them; the job files list the packs.
RUNGS = ("poker", "shop-promotions-stub", "shop-promotions-small", "shop-returns-small",
         "shop-returns-medium")
LETTERS = dict(zip(RUNGS, "ABCDE"))


def check_options(options: dict, plan: PlanView) -> None:
    check_number_options(options, ("usd_per_gbp",))


def summarize(view: ExperimentView, options: dict, out: Path) -> None:
    data = codebase_ladder_summary(view, options)
    (out / f"{SUMMARY_NAME}.json").write_text(json.dumps(data, indent=2) + "\n",
                                              encoding="utf-8")
    (out / f"{SUMMARY_NAME}.md").write_text(render_markdown(data), encoding="utf-8")


SUMMARY = Summary(summarize, check_options=check_options)


def codebase_ladder_summary(view: ExperimentView, options: dict) -> dict:
    trials = [ladder_trial(t) for t in view.trials]
    rungs = ladder_rungs(RUNGS, trials)
    return {
        "rungs": rungs,
        "trials": trials,
        "grid": ladder_grid(view, trials, rungs, entry=_grid_entry),
        "rollup": ladder_rollup(view, trials),
        "cells": cells(view),
        "expected_trials": sum(view.expected.values()),
        "kept_trials": len(trials),
        "discard_causes": discard_causes(view.log),
        "missing_trials": missing_trials(view),
        "hosted_cost": hosted_cost(view, trials, options.get("usd_per_gbp", USD_PER_GBP)),
    }


def _grid_entry(t: dict) -> dict:
    """The difficulty ladder's grid entry, plus the seed-suite counts (None
    when the reward has none)."""
    reward = t["reward"] or {}
    return {**grid_entry(t), "seed_suite_passed": reward.get("seed_suite_passed"),
            "seed_suite_total": reward.get("seed_suite_total")}


def _grid_cell(s: dict) -> str:
    """The difficulty ladder's score, with ` seed passed/total` when the
    trial broke the seed suite, whether it completed or timed out."""
    text = grid_score(s)
    passed, total = s["seed_suite_passed"], s["seed_suite_total"]
    if total and passed is not None and passed < total:
        text += f" seed {passed}/{total}"
    return text


def rung_label(rung: str) -> str:
    """`A: poker`: the rung's letter and its task; a stand-in rung by its slug."""
    return f"{LETTERS[rung]}: {rung}" if rung in LETTERS else rung


TRIAL_COLUMNS_CODEBASE = ladder_columns(lambda t: rung_label(t["rung"]))
CODEBASE_KEY = (
    "- **Local model:** the model name and the start date of a local trial, so that results "
    "from different runs of the local server show; **Rung:** the rung's letter and the slug "
    "of its task pack.",
    "- **Score:** for rungs B to E, the reference tests are the feature tests; reward 1 also "
    "needs each test of the seed suite to pass.",
    "- **Seconds:** the whole trial; the rollup's agent time is the agent's run only.",
)
GRID_NOTE = (
    "One column for each rung, A to E. A cell gives the feature tests passed of the total, "
    "with ✓ when they and the seed suite all pass (reward 1) and ✗ otherwise, and "
    "`seed passed/total` when the trial broke the seed suite (the existing code); `timeout` "
    "when the agent ran out of time, with the seed mark too when its code broke the seed suite; `—` when the rung has no kept trial yet. "
    "Rung A is the poker task pack of the difficulty ladder, without change. "
    "Each failure boundary is provisional while each cell has one repetition.")


def render_markdown(summary: dict) -> str:
    lines = ["# Codebase ladder summary", ""]
    lines += grid_markdown(summary, GRID_NOTE, [rung_label(r) for r in summary["rungs"]],
                           _grid_cell)
    lines += rollup_markdown(summary)
    lines += missing_markdown(summary["missing_trials"], summary["expected_trials"])
    lines += trials_markdown(summary["trials"], TRIAL_COLUMNS_CODEBASE,
                             (*TRIAL_KEY, *CODEBASE_KEY),
                             order=ladder_trial_order(summary["rungs"]))
    lines += hosted_cost_markdown(summary["hosted_cost"])
    return "\n".join(lines) + "\n"
