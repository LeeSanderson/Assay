"""The parts that more than one experiment-local summary needs (issue #68).

An experiment-local summary (see assay.summary) builds its values from the
ExperimentView. These are the values and the markdown that the Phase 0
summary and the difficulty-ladder summary share, so neither copies them:

- `check_number_options`: the options check of a summary whose options are
  all numbers above 0;
- `trial_values`: the values of one kept trial, as a dict for the JSON;
- `money_cost_usd`: the money cost of one kept trial, the one place of the
  L5 rule that a local trial has none;
- `hosted_cost`: the cost of the hosted trials, kept plus discarded;
- `cells`: each cell's expected, kept, discarded and halted trials, and
  whether it is short; `cell_key` gives a cell's key;
- `discard_causes`: the causes of the discarded and halted trials;
- `missing_trials` and `missing_markdown`: the trials missing from each short
  cell, with the cause of each discard or halt, or that it has not run yet;
- `trials_markdown`: the trials table and its key, from the trial values.
  Its columns are a sequence of `Column`, so a summary can add its own
  (`TRIAL_COLUMNS` gives the Phase 0 columns, `TRIAL_KEY` their key);
- `markdown_table`, `score`, `num`, `pct` and `of`: the markdown pieces.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

from assay.summary import ExperimentView, TrialView

CELL_KEYS = ("harness", "model_tier", "condition", "language")


def check_number_options(options: dict, keys: Sequence[str]) -> None:
    """Raises ValueError for an option that is not one of `keys`, or for a
    value that is not a number above 0."""
    if unknown := sorted(set(options) - set(keys)):
        raise ValueError(f"unknown option {', '.join(unknown)} ({', '.join(keys)})")
    for key in keys:
        value = options.get(key, 1)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{key} must be a number above 0, not {value!r}")


# --- The values -----------------------------------------------------------------


def trial_values(t: TrialView) -> dict:
    """One kept trial: its cell and outcome, the values of its evaluations
    and its cost. A local trial's cost_usd is 0, the price that L5 gives the
    local model; whether a trial has a money cost is `money_cost_usd`."""
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
        "language": t.cell.language if t.cell is not None else t.pack_language,
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
            "cost_usd": 0 if record.local else usage.cost_usd,
            "input_tokens": usage.input_tokens,
            "cache_tokens": usage.cache_tokens,
            "output_tokens": usage.output_tokens,
            "duration_sec": record.duration_sec,
            "turns": record.turns,
        },
    }


def money_cost_usd(t: dict) -> float | None:
    """The money cost of a kept trial (a `trial_values` dict) in USD. L5: the
    cost that Claude Code reports for a local model is no money cost, so a
    local trial has none (None). Every summary takes the rule from here."""
    return None if t["local"] else t["cost"]["cost_usd"]


def hosted_cost(view: ExperimentView, trials: Sequence[dict], usd_per_gbp: float) -> dict:
    """The cost of the hosted trials: the kept trials (`trial_values` dicts)
    plus each discarded trial in the experiment log, in USD and GBP."""
    local_tiers = {t["model_tier"] for t in trials if t["local"]}
    discards = [e for e in view.log if e["event"] == "trial-discarded"]
    # A halted trial is logged at the halt, and again as trial-discarded
    # (after_halt) when the next invocation deletes it: its cost counts once,
    # from the trial-discarded line.
    discarded_usd = sum(e.get("cost_usd") or 0 for e in discards
                        if (e.get("cell") or {}).get("model_tier") not in local_tiers)
    kept_usd = sum(money_cost_usd(t) or 0 for t in trials)
    total_usd = kept_usd + discarded_usd
    return {"kept_usd": kept_usd, "discarded_usd": discarded_usd, "total_usd": total_usd,
            "total_gbp": total_usd / usd_per_gbp, "usd_per_gbp": usd_per_gbp}


def cell_key(cell: dict | None) -> tuple:
    """A cell's levels, in CELL_KEYS order; None for each level of no cell."""
    return tuple((cell or {}).get(k) for k in CELL_KEYS)


def cells(view: ExperimentView) -> list[dict]:
    """Each cell: the expected trials, and the kept, discarded and halted
    trials. A short cell holds fewer kept trials than expected. The cells go
    by condition, then model tier, then language."""
    expected = Counter({cell_key(asdict(c)): n for c, n in view.expected.items()})
    kept = Counter(cell_key(asdict(t.cell) if t.cell else None) for t in view.trials)
    discarded = Counter(cell_key(e.get("cell")) for e in view.log
                        if e["event"] == "trial-discarded" and not e.get("after_halt"))
    halted = Counter(cell_key(e.get("cell")) for e in view.log if e["event"] == "halt")
    keys = sorted(set(expected) | set(kept) | set(discarded) | set(halted),
                  key=lambda k: tuple(str(v) for v in (k[2], k[1], k[3], k[0])))
    return [{**dict(zip(CELL_KEYS, key)), "expected": expected[key], "kept": kept[key],
             "discarded": discarded[key], "halted": halted[key],
             "short": kept[key] < expected[key]} for key in keys]


def _cause(event) -> str:
    cause = event.get("cause") or {}
    return cause.get("exception") or ", ".join(cause.get("failed_checks", []))


def discard_causes(log) -> list[dict]:
    """The causes of the discarded and halted trials, by exception type or
    failed check; an unlisted exception type is marked for a person to classify."""
    counts: Counter[tuple[str, bool]] = Counter()
    for e in log:
        if e["event"] == "halt" or (e["event"] == "trial-discarded" and not e.get("after_halt")):
            counts[(_cause(e), bool((e.get("cause") or {}).get("unlisted")))] += 1
    return [{"cause": name, "count": n, "unlisted": unlisted}
            for (name, unlisted), n in sorted(counts.items())]


def missing_trials(view: ExperimentView) -> dict:
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
        key = cell_key(asdict(t.cell) if t.cell else None)
        kept.setdefault(key, []).append(f"{t.job}/{t.trial}")
    short = []
    for c in cells(view):
        if not c["short"]:
            continue
        key = tuple(c[k] for k in CELL_KEYS)
        missing = c["expected"] - c["kept"]
        found = [e for e in lost if cell_key(e.get("cell")) == key][-missing:]
        short.append({**{k: c[k] for k in CELL_KEYS}, "expected": c["expected"],
                      "kept": c["kept"], "kept_trials": sorted(kept.get(key, [])),
                      "trials": [entry(e) for e in found],
                      "not_run": missing - len(found)})
    return {"count": sum(c["expected"] - c["kept"] for c in short), "cells": short,
            "halted_without_cell": [entry(e) for e in lost
                                    if e["event"] == "halt" and e.get("cell") is None]}


# --- The markdown ---------------------------------------------------------------


def pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"


def num(value, digits=0) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def of(count, total) -> str:
    """`count of total (share)`, or "-" when there is no total."""
    return "-" if not total else f"{count} of {total} ({pct(count / total)})"


def _lost(t: dict) -> str:
    mark = " (an unlisted exception type: classify it)" if t["unlisted"] else ""
    return f"`{t['job']}/{t['trial']}` {t['outcome']}, {t['cause']}{mark}"


def missing_markdown(missing: dict, expected_trials: int) -> list[str]:
    """The Missing trials section from `missing_trials`, or nothing when no
    trial is missing."""
    if not missing["count"] and not missing["halted_without_cell"]:
        return []
    lines = ["## Missing trials", "",
             f"{missing['count']} of {expected_trials} expected trials missing.", ""]
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


@dataclass(frozen=True)
class Column:
    """One column of the trials table: its header, and its text for the
    values of one trial (a `trial_values` dict, with whatever a summary adds)."""

    header: str
    text: Callable[[dict], str]


def _passed(reward: dict, prefix: str) -> str:
    passed, total = reward.get(f"{prefix}_passed"), reward.get(f"{prefix}_total")
    return "-" if total is None else f"{passed} of {total}"


def score(reward: dict, of_word: str = " of ") -> str:
    """The reference tests passed of the total (`29 of 29`, or with
    `of_word="/"` `29/29`), with ✓ for reward 1 and ✗ for reward 0; "-" when
    the reward gives no total."""
    passed, total = reward.get("reference_passed"), reward.get("reference_total")
    if total is None:
        return "-"
    mark = {1: " ✓", 0: " ✗"}.get(reward.get("reward"), "")
    return f"{passed}{of_word}{total}{mark}"


def markdown_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """The lines of a markdown table."""
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
            *("| " + " | ".join(r) + " |" for r in rows)]


def _tdd_loop(t: dict) -> str:
    loop = t["tdd_loop"]
    return "-" if loop is None else \
        f"{loop['cycles']} / {loop['tests_never_seen_red']} / {loop['refactor_steps']}"


def _skill(t: dict) -> str:
    skill = t["skill_load"]
    return "-" if skill is None else ("before first file write"
                                      if skill["before_first_file_write"]
                                      else "after first file write" if skill["loaded"]
                                      else "no")


def _web(t: dict) -> str:
    web = t["web_access"]
    return "-" if web is None else \
        ", ".join(map(str, web["step_ids"])) if web["flagged"] else "no"


def _runs(t: dict, count: str, total: str) -> str:
    runs = t["agent_test_runs"] or {}
    return of(runs.get(count), runs.get(total))


TRIAL_COLUMNS: tuple[Column, ...] = (
    Column("Job", lambda t: t["job"]),
    Column("Trial", lambda t: t["trial"]),
    Column("Model tier", lambda t: t["model_tier"]),
    Column("Condition", lambda t: (t["cell"] or {}).get("condition", "-")),
    Column("Language", lambda t: t["language"]),
    Column("Score", lambda t: score(t["reward"] or {})),
    Column("Test-first order", lambda t: t["test_first_order"] or "-"),
    Column("Red-to-green order", lambda t: t["red_to_green_order"] or "-"),
    Column("TDD loop", _tdd_loop),
    Column("Agent tests", lambda t: _passed(t["reward"] or {}, "agent_tests")),
    Column("Tested after edit", lambda t: _runs(t, "covered_snapshots", "snapshots")),
    Column("Read matches replay", lambda t: _runs(t, "agreeing_runs", "compared_runs")),
    Column("Bash writes", lambda t: t["bash_writes"] or "-"),
    Column("Ad-hoc runs", lambda t: str((t["ad_hoc_runs"] or {}).get("count") or "-")),
    Column("Skill loaded", _skill),
    Column("Web access", _web),
    Column("Errors", lambda t: "; ".join(f"{name}: {error}"
                                         for name, error in t["errors"].items()) or "-"),
    Column("USD", lambda t: f"{num(t['cost']['cost_usd'], 2)}"
                            f"{' (local)' if t['local'] else ''}"),
    Column("Tokens in / cache / out",
           lambda t: " / ".join(num(t["cost"][k])
                                for k in ("input_tokens", "cache_tokens", "output_tokens"))),
    Column("Seconds", lambda t: num(t["cost"]["duration_sec"])),
    Column("Turns", lambda t: num(t["cost"]["turns"])),
)

TRIAL_KEY = (
    "- **Red-to-green order**, from the agent's test runs that agree with the replay (the "
    "seen states): `red-to-green` (the first seen state is red, and a later one is green), "
    "`green-first` (the first seen state is green: the agent did not see the tests fail), "
    "`never-green` (every seen state is red) or `not-observed` (no seen state); `-` when "
    "there is no replay.",
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
)


def _trial_order(t: dict) -> tuple:
    cell = t["cell"] or {}
    return (str(cell.get("condition")), str(t["model_tier"]), t["language"], t["job"],
            t["trial"])


def trials_markdown(trials: Sequence[dict], columns: Sequence[Column] = TRIAL_COLUMNS,
                    key: Sequence[str] = TRIAL_KEY,
                    order: Callable[[dict], tuple] = _trial_order) -> list[str]:
    """The Trials section: one row for each trial, in `order` (by default by
    condition, then model tier, then language), and the key under the table."""
    rows = [[c.text(t) for c in columns] for t in sorted(trials, key=order)]
    return ["## Trials", "", *markdown_table([c.header for c in columns], rows), "", *key]
