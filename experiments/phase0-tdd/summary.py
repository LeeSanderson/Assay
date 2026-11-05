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
of the trials; the JSON also keeps each value the markdown leaves out.

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
from assay.summary import ExperimentView, PlanView, Summary, TrialView

SUMMARY_NAME = "phase0-summary"
CAP_GBP = 15
USD_PER_GBP = 1.27
PERSON_CHECK = ("Check both against a person's labels with `assay compare-labels` "
                "(PRD section 16); the summary does not give that half of 1 and 6.")
CELL_KEYS = ("harness", "model_tier", "condition", "language")


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
    trials = [_trial(t) for t in view.trials]
    unflagged = [t for t in trials if not (t["web_access"] or {}).get("flagged")]
    versions: dict[str, set[str]] = {}
    for t in view.trials:
        versions.setdefault(t.job, set())
        if t.record.identity.version:
            versions[t.job].add(t.record.identity.version)
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
        "missing_trials": _missing(view),
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
    bash = trajectory.get("bash")
    return {
        "job": t.job,
        "trial": t.trial,
        "cell": asdict(t.cell) if t.cell is not None else None,
        "language": t.cell.language if t.cell is not None else Path(t.task_pack).parts[-2],
        "reward": record.reward,
        "replay": None if replay is None else {"works": replay["works"],
                                               "causes": replay["causes"]},
        "test_first_order": (trajectory.get("test_first_order") or {}).get("verdict"),
        "red_to_green_order": (trajectory.get("red_to_green_order") or {}).get("verdict"),
        "tdd_loop": trajectory.get("tdd_loop"),
        "bash": bash,
        "bash_writes": None if bash is None
        else "test/impl" if bash["bash_writes_test_or_implementation"]
        else "yes" if bash["file_writing_bash"] else "no",
        "skill_load": trajectory.get("skill_load"),
        "ad_hoc_runs": trajectory.get("ad_hoc_runs"),
        "web_access": trajectory.get("web_access"),
        "agent_test_runs": None if runs is None else runs["cross_check"],
        "errors": {name: error for name, error in t.errors.items() if error is not None},
        "model_tier": record.identity.model_tier,
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


def _cause(event) -> str:
    cause = event.get("cause") or {}
    return cause.get("exception") or ", ".join(cause.get("failed_checks", []))


def _causes(log) -> list[dict]:
    """The causes of the discarded and halted trials, by exception type or
    failed check; an unlisted exception type is marked for a person to classify."""
    counts: Counter[tuple[str, bool]] = Counter()
    for e in log:
        if e["event"] == "halt" or (e["event"] == "trial-discarded" and not e.get("after_halt")):
            counts[(_cause(e), bool((e.get("cause") or {}).get("unlisted")))] += 1
    return [{"cause": name, "count": n, "unlisted": unlisted}
            for (name, unlisted), n in sorted(counts.items())]


def _missing(view: ExperimentView) -> dict:
    """The trials missing from each short cell: the last discards and the
    unresolved halts of the cell, one for each missing trial, and the rest
    not run yet. A halt is resolved when the next invocation deletes its
    trial (trial-discarded, after_halt); an unresolved halt with no cell is
    listed on its own."""
    resolved = {(e["job"], e["trial"]) for e in view.log
                if e["event"] == "trial-discarded" and e.get("after_halt")}
    lost = [e for e in view.log
            if (e["event"] == "trial-discarded" and not e.get("after_halt"))
            or (e["event"] == "halt" and (e["job"], e["trial"]) not in resolved)]

    def entry(e) -> dict:
        cause = e.get("cause") or {}
        return {"job": e["job"], "trial": e["trial"],
                "outcome": "halted" if e["event"] == "halt" else "discarded",
                "cause": cause.get("exception")
                or "failed check " + ", ".join(cause.get("failed_checks", [])),
                "unlisted": bool(cause.get("unlisted"))}

    kept: dict[tuple, list[str]] = {}
    for t in view.trials:
        key = _cell_key(asdict(t.cell) if t.cell else None)
        kept.setdefault(key, []).append(f"{t.job}/{t.trial}")
    cells = []
    for c in _cells(view):
        if not c["short"]:
            continue
        key = tuple(c[k] for k in CELL_KEYS)
        missing = c["expected"] - c["kept"]
        found = [e for e in lost if _cell_key(e.get("cell")) == key][-missing:]
        cells.append({**{k: c[k] for k in CELL_KEYS}, "expected": c["expected"],
                      "kept": c["kept"], "kept_trials": sorted(kept.get(key, [])),
                      "trials": [entry(e) for e in found],
                      "not_run": missing - len(found)})
    return {"count": sum(c["expected"] - c["kept"] for c in cells), "cells": cells,
            "halted_without_cell": [entry(e) for e in lost
                                    if e["event"] == "halt" and e.get("cell") is None]}


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


def of(count, total) -> str:
    """`count of total (share)`, or "-" when there is no total."""
    return "-" if not total else f"{count} of {total} ({pct(count / total)})"


def counted(shares, key) -> str:
    return of(shares[key]["count"], shares["trials"])


def render_markdown(summary: dict) -> str:
    versions = ", ".join(f"{job} {', '.join(v) or '-'}"
                         for job, v in summary["claude_code_versions"].items()) or "-"
    lines = ["# Phase 0 summary", "", f"Claude Code version for each job: {versions}.", ""]
    lines += _acceptance_markdown(summary)
    lines += _missing_markdown(summary)
    lines += _trials_markdown(summary)
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


def _lost(t: dict) -> str:
    mark = " (an unlisted exception type: classify it)" if t["unlisted"] else ""
    return f"`{t['job']}/{t['trial']}` {t['outcome']}, {t['cause']}{mark}"


def _missing_markdown(summary: dict) -> list[str]:
    missing = summary["missing_trials"]
    if not missing["count"] and not missing["halted_without_cell"]:
        return []
    lines = ["## Missing trials", "",
             f"{missing['count']} of {summary['expected_trials']} expected trials missing.", ""]
    for c in missing["cells"]:
        cell = " · ".join(str(c[k]) for k in CELL_KEYS)
        names = ", ".join(f"`{name}`" for name in c["kept_trials"])
        lines.append(f"- {cell}: {c['kept']} of {c['expected']} kept"
                     + (f" ({names})" if names else ""))
        lines += [f"  - {_lost(t)}" for t in c["trials"]]
        if c["not_run"]:
            lines.append(f"  - {c['not_run']} trial{'s' if c['not_run'] > 1 else ''} "
                         "not run yet")
    for t in missing["halted_without_cell"]:
        lines.append(f"- no cell: {_lost(t)}")
    return lines + ["", "The next invocation runs these again.", ""]


TRIAL_COLUMNS = ("Job", "Trial", "Model tier", "Condition", "Language", "Score",
                 "Test-first order", "Red-to-green order", "TDD loop", "Agent tests",
                 "Tested after edit", "Read matches replay", "Bash writes", "Ad-hoc runs",
                 "Skill loaded", "Web access", "Errors", "USD", "Tokens in / cache / out",
                 "Seconds", "Turns")

TRIAL_KEY = [
    "- **TDD loop:** cycles / tests never seen red / refactor steps.",
    "- **Score:** the withheld reference tests that pass on the final repository, with ✓ when "
    "they all pass and compile (reward 1) and ✗ otherwise; **Agent tests:** the agent's own "
    "tests that pass.",
    "- **Tested after edit** and **Read matches replay** check the instrument, not the agent. "
    "Tested after edit: the snapshots after which the agent ran its tests before its next "
    "file write. Read matches replay: the agent's full test runs whose red or green, as read "
    "from their output, matches the replay of the same snapshot.",
    "- **Bash writes:** whether a `Bash` call wrote a file (`yes`), and whether it wrote a "
    "test or implementation file (`test/impl`); test-first order cannot see such a write.",
    "- **Ad-hoc runs:** scripts the agent wrote and ran, which the cross-check does not see.",
    "- **Web access:** the steps of a web tool call that did not fail, or of a `Bash` command "
    "with a URL, `curl`, `wget` or `git clone`.",
    "- **USD:** the local tier's money cost is zero (L5).",
]


def _trials_markdown(summary: dict) -> list[str]:
    lines = ["## Trials", "",
             "| " + " | ".join(TRIAL_COLUMNS) + " |",
             "|" + "---|" * len(TRIAL_COLUMNS)]

    def order(t):
        cell = t["cell"] or {}
        return (str(cell.get("condition")), str(t["model_tier"]), t["language"], t["job"],
                t["trial"])

    for t in sorted(summary["trials"], key=order):
        loop = t["tdd_loop"]
        loop = "-" if loop is None else \
            f"{loop['cycles']} / {loop['tests_never_seen_red']} / {loop['refactor_steps']}"
        reward = t["reward"] or {}
        runs = t["agent_test_runs"] or {}
        skill = t["skill_load"]
        skill = "-" if skill is None else ("before first file write"
                                           if skill["before_first_file_write"]
                                           else "after first file write" if skill["loaded"]
                                           else "no")
        web = t["web_access"]
        web = "-" if web is None else \
            ", ".join(map(str, web["step_ids"])) if web["flagged"] else "no"
        ad_hoc = (t["ad_hoc_runs"] or {}).get("count") or "-"
        errors = "; ".join(f"{name}: {error}" for name, error in t["errors"].items()) or "-"
        c = t["cost"]
        usd = f"{num(c['cost_usd'], 2)}{' (local)' if t['local'] else ''}"
        tokens = " / ".join(num(c[k]) for k in ("input_tokens", "cache_tokens", "output_tokens"))
        cells = [
            t["job"], t["trial"], t["model_tier"], (t["cell"] or {}).get("condition", "-"),
            t["language"], _score(reward), t["test_first_order"] or "-",
            t["red_to_green_order"] or "-", loop, _passed(reward, "agent_tests"),
            of(runs.get("covered_snapshots"), runs.get("snapshots")),
            of(runs.get("agreeing_runs"), runs.get("compared_runs")),
            t["bash_writes"] or "-", str(ad_hoc), skill, web, errors, usd, tokens,
            num(c["duration_sec"]), num(c["turns"])]
        lines.append("| " + " | ".join(cells) + " |")
    return lines + ["", *TRIAL_KEY]


def _score(reward: dict) -> str:
    passed = _passed(reward, "reference")
    mark = {1: " ✓", 0: " ✗"}.get(reward.get("reward"), "")
    return passed + mark if passed != "-" else passed


def _passed(reward: dict, prefix: str) -> str:
    passed, total = reward.get(f"{prefix}_passed"), reward.get(f"{prefix}_total")
    return "-" if total is None else f"{passed} of {total}"
