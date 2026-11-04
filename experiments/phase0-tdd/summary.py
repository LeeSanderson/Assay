"""The Phase 0 summary (PRD v3 section 17, "The phase0-tdd experiment").

`assay experiment phase0-tdd` runs it after the evaluations, on every
invocation that completes. It writes analysis/phase0-tdd/summary/
phase0-summary.md (for a person) and phase0-summary.json: each Phase 0
acceptance number, and also

- for each cell, the discarded, halted and kept trials against the expected
  trials, with each short cell marked;
- the cost of the hosted trials against the £15 cap: the kept trials' cost
  plus the cost of each discarded trial in the experiment log;
- the local trial's values from its trial record. The values that come from
  the server log stay by hand.

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
from dataclasses import asdict
from pathlib import Path

from analyze.trial import share
from assay.summary import ExperimentView, Summary, TrialView

SUMMARY_NAME = "phase0-summary"
CAP_GBP = 15
USD_PER_GBP = 1.27
BY_HAND = "record by hand from the server log"
CELL_KEYS = ("harness", "model_tier", "condition", "language")


def check_options(options: dict) -> None:
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
    trials = [_trial(t) for t in view.trials]
    unflagged = [t for t in trials if not (t["web_access"] or {}).get("flagged")]
    versions: dict[str, set[str]] = {}
    for t in view.trials:
        versions.setdefault(t.job, set())
        if t.record.agent_version:
            versions[t.job].add(t.record.agent_version)
    local_tiers = {t["model_tier"] for t in trials if t["local"]}
    discards = [e for e in view.log if e["event"] == "trial-discarded"]
    # A halted trial is logged at the halt, and again as trial-discarded
    # (after_halt) when the next invocation deletes it: its cost counts once,
    # from the trial-discarded line.
    discarded_usd = sum(e.get("cost_usd") or 0 for e in discards
                        if (e.get("cell") or {}).get("model_tier") not in local_tiers)
    kept_usd = sum(t["cost"]["cost_usd"] or 0 for t in trials if not t["local"])
    total_usd = kept_usd + discarded_usd
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
        "cells": _cells(view),
        "expected_trials": sum(view.expected.values()),
        "kept_trials": len(trials),
        "discard_causes": _causes(view.log),
        "hosted_cost": {
            "kept_usd": kept_usd, "discarded_usd": discarded_usd, "total_usd": total_usd,
            "total_gbp": total_usd / usd_per_gbp, "usd_per_gbp": usd_per_gbp,
            "cap_gbp": cap_gbp, "within_cap": total_usd / usd_per_gbp <= cap_gbp,
        },
        "local_trials": [_local_trial(t) for t in view.trials if t.record.local],
    }


def _trial(t: TrialView) -> dict:
    replay = t.values.get("replay")
    trajectory = t.values.get("trajectory") or {}
    runs = t.values.get("agent-runs")
    record = t.record
    usage = record.usage
    return {
        "job": t.job,
        "trial": t.trial,
        "cell": asdict(t.cell) if t.cell is not None else None,
        "replay": None if replay is None else {"works": replay["works"],
                                               "causes": replay["causes"]},
        "test_first_order": (trajectory.get("test_first_order") or {}).get("verdict"),
        "red_to_green_order": (trajectory.get("red_to_green_order") or {}).get("verdict"),
        "tdd_loop": trajectory.get("tdd_loop"),
        "bash": trajectory.get("bash"),
        "skill_load": trajectory.get("skill_load"),
        "ad_hoc_runs": trajectory.get("ad_hoc_runs"),
        "web_access": trajectory.get("web_access"),
        "agent_test_runs": None if runs is None else runs["cross_check"],
        "errors": {name: error for name, error in t.errors.items() if error is not None},
        "model_tier": record.model_tier,
        "local": record.local,
        "cost": {
            # L5: Claude Code's total_cost_usd is not a money cost for a local model.
            "cost_usd": 0 if record.local else usage.cost_usd,
            "input_tokens": usage.input_tokens,
            "cache_tokens": usage.cache_tokens,
            "output_tokens": usage.output_tokens,
            "duration_sec": record.duration_sec,
            "turns": record.turns,
        },
    }


def _cell_key(cell: dict | None) -> tuple:
    return tuple((cell or {}).get(k) for k in CELL_KEYS)


def _cells(view: ExperimentView) -> list[dict]:
    """Each cell: the expected trials, and the kept, discarded and halted
    trials. A short cell holds fewer kept trials than expected."""
    expected = Counter({_cell_key(asdict(c)): n for c, n in view.expected.items()})
    kept = Counter(_cell_key(asdict(t.cell) if t.cell else None) for t in view.trials)
    discarded = Counter(_cell_key(e.get("cell")) for e in view.log
                        if e["event"] == "trial-discarded" and not e.get("after_halt"))
    halted = Counter(_cell_key(e.get("cell")) for e in view.log if e["event"] == "halt")
    keys = sorted(set(expected) | set(kept) | set(discarded) | set(halted),
                  key=lambda k: tuple(str(v) for v in (k[2], k[1], k[3], k[0])))
    return [{**dict(zip(CELL_KEYS, key)), "expected": expected[key], "kept": kept[key],
             "discarded": discarded[key], "halted": halted[key],
             "short": kept[key] < expected[key]} for key in keys]


def _causes(log) -> list[dict]:
    """The causes of the discarded and halted trials, by exception type or
    failed check; an unlisted exception type is marked for a person to classify."""
    counts: Counter[tuple[str, bool]] = Counter()
    for e in log:
        if e["event"] == "halt" or (e["event"] == "trial-discarded" and not e.get("after_halt")):
            cause = e.get("cause") or {}
            name = cause.get("exception") or ", ".join(cause.get("failed_checks", []))
            counts[(name, bool(cause.get("unlisted")))] += 1
    return [{"cause": name, "count": n, "unlisted": unlisted}
            for (name, unlisted), n in sorted(counts.items())]


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


def pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"


def num(value, digits=0) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def render_markdown(summary: dict) -> str:
    versions = ", ".join(f"{job} {', '.join(v) or '-'}"
                         for job, v in summary["claude_code_versions"].items()) or "-"
    lines = ["# Phase 0 summary", "", f"Claude Code version for each job: {versions}.", ""]
    lines += _cells_markdown(summary)
    lines += ["", "## Trials", "",
              "Every trial here passed the validity check; a trial that failed it was "
              "discarded and counts in its cell.", "",
              "| Job | Trial | Model tier | Condition | Replay | Test-first order "
              "| Red-to-green order | TDD loop (cycles / never seen red / refactor steps) "
              "| Coverage | Agreement | Skill loaded | Web access (steps) | Errors |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in summary["trials"]:
        replay = "not run" if t["replay"] is None else \
            "works" if t["replay"]["works"] else "fails: " + "; ".join(t["replay"]["causes"])
        loop = t["tdd_loop"]
        loop = "-" if loop is None else \
            f"{loop['cycles']} / {loop['tests_never_seen_red']} / {loop['refactor_steps']}"
        runs = t["agent_test_runs"] or {}
        skill = t["skill_load"]
        skill = "-" if skill is None else ("before first file write"
                                           if skill["before_first_file_write"]
                                           else "after first file write" if skill["loaded"]
                                           else "no")
        web = t["web_access"]
        web = "-" if web is None else \
            ", ".join(map(str, web["step_ids"])) if web["flagged"] else "no"
        errors = "; ".join(f"{name}: {error}" for name, error in t["errors"].items()) or "-"
        condition = (t["cell"] or {}).get("condition", "-")
        lines.append(
            f"| {t['job']} | {t['trial']} | {t['model_tier']} | {condition} | {replay} "
            f"| {t['test_first_order'] or '-'} | {t['red_to_green_order'] or '-'} | {loop} "
            f"| {pct(runs.get('coverage'))} | {pct(runs.get('agreement'))} | {skill} | {web} "
            f"| {errors} |")
    works = summary["replay_works"]
    lines += ["", "## Replay", "",
              f"- Replay works on {works['count']} of {works['of']} trials."]

    def counted(shares, text, key):
        s = shares[key]
        return f"- {text}: {s['count']} of {shares['trials']} ({pct(s['share'])})."

    def sections(shares, runs, level):
        return [
            "", f"{level} Bash file writes", "",
            counted(shares, "Trials with a file-writing `Bash` call", "file_writing_bash"),
            counted(shares, "Trials where a `Bash` call writes a test or implementation file",
                    "bash_writes_test_or_implementation"),
            counted(shares, "Trials where offline replay applies (no file-writing `Bash` call)",
                    "offline_replay_applies"),
            "", f"{level} Agent test runs", "",
            f"- Coverage: {runs['covered_snapshots']} of {runs['snapshots']} snapshots "
            f"({pct(runs['coverage'])}).",
            f"- Agreement: {runs['agreeing_runs']} of {runs['compared_runs']} compared runs "
            f"({pct(runs['agreement'])}).",
            counted(shares, "Trials with an ad-hoc run (a script the agent wrote, not in the "
                            "cross-check)", "ad_hoc_runs"),
        ]

    unflagged = summary["unflagged"]
    lines += sections(summary["shares"], summary["agent_test_runs"], "##")
    lines += ["", "## Web access", "",
              counted(summary["shares"], "Trials that may have reached the web", "web_access"),
              "", "These trials stay in the data above. A web tool call that did not fail, or "
              "a `Bash` command with a URL, `curl`, `wget` or `git clone`, flags a trial.",
              "", "## Without the web-access trials"]
    lines += sections(unflagged["shares"], unflagged["agent_test_runs"], "###")
    lines += ["", "## Cost for each model tier", "",
              "Kept trials only. The local tier's money cost is zero (L5); its token counts "
              "are kept. Values per trial are means.", "",
              "| Model tier | Trials | Total USD | USD per trial | Input tokens | Cache tokens "
              "| Output tokens | Seconds | Turns |",
              "|---|---|---|---|---|---|---|---|---|"]
    for tier, c in summary["cost"].items():
        p = c["per_trial"]
        name = f"{tier} (local)" if c["local"] else tier
        lines.append(
            f"| {name} | {c['trials']} | {num(c['total_cost_usd'], 2)} | {num(p['cost_usd'], 2)} "
            f"| {num(p['input_tokens'])} | {num(p['cache_tokens'])} | {num(p['output_tokens'])} "
            f"| {num(p['duration_sec'])} | {num(p['turns'], 1)} |")
    h = summary["hosted_cost"]
    lines += ["", "## The £15 cap", "",
              f"Hosted trials: {num(h['kept_usd'], 2)} USD kept + {num(h['discarded_usd'], 2)} "
              f"USD discarded (from the experiment log) = {num(h['total_usd'], 2)} USD = "
              f"£{h['total_gbp']:.2f} of the £{h['cap_gbp']} cap "
              f"({'within' if h['within_cap'] else 'over'} the cap; "
              f"1 GBP = {h['usd_per_gbp']} USD assumed). Each trial that ran again counts."]
    for t in summary["local_trials"]:
        after = t["tool_calls_after_system_message"]
        cached = t["cached_tokens_per_turn"]
        lines += ["", f"## Local trial {t['job']}/{t['trial']}", "",
                  f"- Time: {num(t['duration_sec'])} seconds.",
                  f"- Tool arguments present in the trajectory: "
                  f"{'yes' if t['tool_arguments_present'] else 'no'}.",
                  "- Tool calls after a system message in the middle of the conversation: "
                  + (f"none in the trajectory; {BY_HAND}." if after is None else f"{after}."),
                  "- Prefix cache hits for each turn: "
                  + (f"{BY_HAND}." if cached is None
                     else f"cached tokens {', '.join(num(c) for c in cached)} (ATIF)."),
                  f"- Background requests: {BY_HAND}."]
    return "\n".join(lines) + "\n"


def _cells_markdown(summary: dict) -> list[str]:
    lines = ["## Cells", "",
             f"{summary['kept_trials']} of {summary['expected_trials']} expected trials kept. "
             "A short cell holds fewer kept trials than its jobs promise: a job that has not "
             "run yet, or a discarded trial that was not replaced. It is not a failure.", "",
             "| Harness | Model tier | Condition | Language | Expected | Kept | Discarded "
             "| Halted | |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c in summary["cells"]:
        lines.append(
            f"| {c['harness'] or '-'} | {c['model_tier'] or '-'} | {c['condition'] or '-'} "
            f"| {c['language'] or '-'} | {c['expected']} | {c['kept']} | {c['discarded']} "
            f"| {c['halted']} | {'short' if c['short'] else ''} |")
    if summary["discard_causes"]:
        lines += ["", "Causes of the discarded and halted trials:", ""]
        for cause in summary["discard_causes"]:
            mark = " (an unlisted exception type: classify it)" if cause["unlisted"] else ""
            lines.append(f"- {cause['cause']}: {cause['count']}{mark}")
    return lines
