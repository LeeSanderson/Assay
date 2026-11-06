"""The Phase 0 summary (PRD v3 section 17, "The phase0-tdd experiment").

`assay experiment phase0-tdd` runs it after the evaluations, on every
invocation that completes. It writes analysis/phase0-tdd/summary/
phase0-summary.md (for a person) and phase0-summary.json: each Phase 0
acceptance number, and also

- each trial missing from a short cell, with the cause of its discard or
  halt, or that it has not run yet;
- the cost of the hosted trials against the £15 cap: the kept trials' cost
  plus the cost of each discarded trial in the experiment log;
- whether the local trial's tool arguments are present. The values that come
  from the server log are recorded outside the summary.

The markdown gives the acceptance numbers, the missing trials and one table
of the trials; the JSON also keeps each value the markdown leaves out. The
trial values, the cells, the missing trials and the trials table come from
assay.summary_parts, which the difficulty-ladder summary shares.

Every kept trial passed the validity check (acceptance 3); a trial that
failed it was discarded, and shows in its cell's discarded count and in the
discard causes.

Options (`[summary] options = {...}` in experiment.toml): `usd_per_gbp`, the
rate that converts Claude Code's USD to GBP (set it to the rate on the day),
and `cap_gbp`.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from analyze.trial import share
from assay.summary import ExperimentView, PlanView, Summary, TrialView
from assay.summary_parts import (cells, discard_causes, hosted_cost, missing_markdown,
                                 missing_trials, num, of, trial_values, trials_markdown)

SUMMARY_NAME = "phase0-summary"
CAP_GBP = 15
USD_PER_GBP = 1.27
PERSON_CHECK = ("Check both against a person's labels with `assay compare-labels` "
                "(PRD section 16); the summary does not give that half of 1 and 6.")


def check_options(options: dict, plan: PlanView) -> None:
    if unknown := sorted(set(options) - {"usd_per_gbp", "cap_gbp"}):
        raise ValueError(f"unknown option {', '.join(unknown)} (usd_per_gbp, cap_gbp)")
    for key in ("usd_per_gbp", "cap_gbp"):
        value = options.get(key, 1)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{key} must be a number above 0, not {value!r}")


def summarize(view: ExperimentView, options: dict, out: Path) -> None:
    data = phase0_summary(view, options)
    (out / f"{SUMMARY_NAME}.json").write_text(json.dumps(data, indent=2) + "\n",
                                              encoding="utf-8")
    (out / f"{SUMMARY_NAME}.md").write_text(render_markdown(data), encoding="utf-8")


SUMMARY = Summary(summarize, check_options=check_options)


# --- The values -----------------------------------------------------------------


def phase0_summary(view: ExperimentView, options: dict) -> dict:
    usd_per_gbp = options.get("usd_per_gbp", USD_PER_GBP)
    cap_gbp = options.get("cap_gbp", CAP_GBP)
    trials = [trial_values(t) for t in view.trials]
    unflagged = [t for t in trials if not (t["web_access"] or {}).get("flagged")]
    versions: dict[str, set[str]] = {}
    for t in view.trials:
        versions.setdefault(t.job, set())
        if t.record.identity.version:
            versions[t.job].add(t.record.identity.version)
    cost = hosted_cost(view, trials, usd_per_gbp)
    replayed = [t for t in trials if t["replay"] is not None]
    return {
        "claude_code_versions": {job: sorted(v) for job, v in versions.items()},
        "trials": trials,
        "replay_works": {"count": sum(1 for t in replayed if t["replay"]["works"]),
                         "of": len(trials)},
        "shares": _shares(trials),
        "agent_test_runs": _pooled(trials),
        # The same values without the trials that may have read the solution from the web.
        "unflagged": {"shares": _shares(unflagged), "agent_test_runs": _pooled(unflagged)},
        "cost": _cost(trials),
        "cells": cells(view),
        "expected_trials": sum(view.expected.values()),
        "kept_trials": len(trials),
        "discard_causes": discard_causes(view.log),
        "missing_trials": missing_trials(view),
        "hosted_cost": {**cost, "cap_gbp": cap_gbp, "within_cap": cost["total_gbp"] <= cap_gbp},
        "local_trials": [_local_trial(t) for t in view.trials if t.record.local],
    }


def _local_trial(t: TrialView) -> dict:
    """The local trial's Phase 0 values that its record gives (Risk 9 and 10).
    The prefix cache hits come from ATIF only when the server reports cached
    tokens; the background requests are not in the record at all."""
    record = t.record
    first_agent = next((c.step_id for c in record.tool_calls), None)
    system = next((s for s in record.system_step_ids
                   if first_agent is not None and s > first_agent), None)
    cached = list(record.cached_tokens)
    return {
        "job": t.job,
        "trial": t.trial,
        "duration_sec": record.duration_sec,
        "tool_calls_after_system_message": None if system is None
        else sum(1 for c in record.tool_calls if c.step_id > system),
        "tool_arguments_present": bool(record.tool_calls)
        and all(c.arguments for c in record.tool_calls),
        "cached_tokens_per_turn": cached if any(c is not None for c in cached) else None,
    }


def _cost(trials: list[dict]) -> dict:
    """For each model tier: the total money cost, and the mean of each cost
    value per trial (a trial without the value is left out of its mean)."""
    tiers: dict[str, list[dict]] = {}
    for t in trials:
        tiers.setdefault(t["model_tier"], []).append(t)
    out = {}
    for tier, group in tiers.items():
        costs = [t["cost"] for t in group]
        per_trial = {}
        for key in costs[0]:
            values = [c[key] for c in costs if c[key] is not None]
            per_trial[key] = share(sum(values), len(values))
        out[tier] = {
            "local": any(t["local"] for t in group),
            "trials": len(group),
            "total_cost_usd": sum(c["cost_usd"] or 0 for c in costs),
            "per_trial": per_trial,
        }
    return out


def _pooled(trials: list[dict]) -> dict:
    """Coverage and agreement over the snapshots and runs of all the trials
    with an agent-runs value (PRD section 16, the cross-check)."""
    checks = [t["agent_test_runs"] for t in trials if t["agent_test_runs"]]
    totals = {k: sum(c[k] for c in checks)
              for k in ("snapshots", "covered_snapshots", "compared_runs", "agreeing_runs")}
    return {
        "snapshots": totals["snapshots"],
        "covered_snapshots": totals["covered_snapshots"],
        "coverage": share(totals["covered_snapshots"], totals["snapshots"]),
        "compared_runs": totals["compared_runs"],
        "agreeing_runs": totals["agreeing_runs"],
        "agreement": share(totals["agreeing_runs"], totals["compared_runs"]),
    }


def _shares(trials: list[dict]) -> dict:
    """Risk 2: trials with a file-writing Bash call, and trials where a Bash
    call writes a test or implementation file. Risk 1: offline replay applies
    to the trials with no file-writing Bash call. Also the trials with an
    ad-hoc run, which the cross-check does not see."""
    def counted(test) -> dict:
        count = sum(1 for t in trials if test(t))
        return {"count": count, "share": share(count, len(trials))}

    def bash(t, key):
        return (t["bash"] or {}).get(key)

    return {
        "trials": len(trials),
        "file_writing_bash": counted(lambda t: bash(t, "file_writing_bash")),
        "bash_writes_test_or_implementation":
            counted(lambda t: bash(t, "bash_writes_test_or_implementation")),
        "offline_replay_applies": counted(
            lambda t: t["bash"] is not None and not bash(t, "file_writing_bash")),
        "ad_hoc_runs": counted(lambda t: (t["ad_hoc_runs"] or {}).get("count", 0) > 0),
        "web_access": counted(lambda t: (t["web_access"] or {}).get("flagged")),
    }


# --- The markdown ---------------------------------------------------------------


def counted(shares, key) -> str:
    return of(shares[key]["count"], shares["trials"])


def render_markdown(summary: dict) -> str:
    versions = ", ".join(f"{job} {', '.join(v) or '-'}"
                         for job, v in summary["claude_code_versions"].items()) or "-"
    lines = ["# Phase 0 summary", "", f"Claude Code version for each job: {versions}.", ""]
    lines += _acceptance_markdown(summary)
    lines += missing_markdown(summary["missing_trials"], summary["expected_trials"])
    lines += trials_markdown(summary["trials"])
    return "\n".join(lines) + "\n"


def _acceptance_markdown(summary: dict) -> list[str]:
    shares, runs = summary["shares"], summary["agent_test_runs"]
    flagged = shares["web_access"]["count"]
    unflagged = summary["unflagged"]

    def without_web(text) -> str:
        """The value again without the web-access trials, when a trial is flagged."""
        return f" (without the {flagged} web-access trials: {text})" if flagged else ""

    def bash(s) -> str:
        return (f"{counted(s, 'file_writing_bash')} trials have a file-writing `Bash` call; "
                f"in {counted(s, 'bash_writes_test_or_implementation')} a `Bash` call writes a "
                "test or implementation file")

    def tested(r) -> str:
        return (f"tested after edit {of(r['covered_snapshots'], r['snapshots'])} snapshots; "
                f"read matches replay {of(r['agreeing_runs'], r['compared_runs'])} runs")

    trials = summary["trials"]

    def verdicts(key) -> str:
        found = Counter(t[key] for t in trials if t[key] is not None)
        split = ", ".join(f"{v} {n}" for v, n in sorted(found.items()))
        return (f"`trajectory` gives a verdict on {sum(found.values())} of {len(trials)} trials"
                + (f" ({split})" if split else ""))

    loops = sum(1 for t in trials if t["tdd_loop"] is not None)
    missing = summary["missing_trials"]["count"]
    replays = [t for t in summary["trials"] if not (t["replay"] or {}).get("works")]
    works = summary["replay_works"]
    h = summary["hosted_cost"]
    lines = ["## Phase 0 acceptance", "",
             f"- **1. Test-first order:** {verdicts('test_first_order')}.",
             f"- **2. Bash file writes:** {bash(shares)}{without_web(bash(unflagged['shares']))}.",
             "- **3. Validity:** every kept trial passed the validity check"
             + (f"; {missing} trials missing (see Missing trials)." if missing else "."),
             f"- **4. Replay:** works on {works['count']} of {works['of']} trials."]
    for t in replays:
        why = "not run" if t["replay"] is None else "; ".join(t["replay"]["causes"]) or "fails"
        lines.append(f"  - `{t['job']}/{t['trial']}`: {why}")
    lines += [
        f"- **5. Agent test runs:** {tested(runs)}{without_web(tested(unflagged['agent_test_runs']))}.",
        f"- **6. Red-to-green order and TDD loop:** {verdicts('red_to_green_order')}, and the "
        f"TDD loop on {loops} of {len(trials)}.",
        f"- **7. Cost:** £{h['total_gbp']:.2f} of the £{h['cap_gbp']} cap, "
        f"{'within' if h['within_cap'] else 'over'} it ({num(h['total_usd'], 2)} USD: "
        f"{num(h['kept_usd'], 2)} kept + {num(h['discarded_usd'], 2)} discarded; "
        f"1 GBP = {h['usd_per_gbp']} USD assumed)."]
    for t in summary["local_trials"]:
        present = "present" if t["tool_arguments_present"] else "missing"
        lines.append(f"- **8. Local trial `{t['job']}/{t['trial']}`:** tool arguments "
                     f"{present} in the trajectory.")
    if not summary["local_trials"]:
        lines.append("- **8. Local trial:** not run yet.")
    return lines + ["", PERSON_CHECK, ""]
