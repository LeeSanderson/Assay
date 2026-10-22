"""The Phase 0 summary (PRD section 7, Phase 0).

    uv run python -m analyze.summary results/<job-id>... [--analysis analysis]

reads the trial folders of one or more Phase 0 jobs and their analysis/
outputs (replay-works.json, replay.jsonl, agent-runs.jsonl, cross-check.json),
and writes every Phase 0 acceptance number to analysis/phase0-summary.md and
analysis/phase0-summary.json. It writes nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path

from analyze.agent_runs import CROSS_CHECK_FILE
from analyze.replay import REPO_ROOT
from analyze.trace_check import MixedClaudeCodeVersions, job_claude_code_version, trace_check
from analyze.trajectory import analyze_folder
from analyze.trial import Trial, read_job, read_json, share


SUMMARY_NAME = "phase0-summary"


def summarize(job_dirs: list[Path | str], analysis_root: Path | str) -> dict:
    """Every Phase 0 acceptance value of the jobs, as plain data.

    Raises MixedClaudeCodeVersions if the trials of one job ran more than one
    Claude Code version (L1).
    """
    trials, versions = [], {}
    for job_dir in map(Path, job_dirs):
        job = read_job(job_dir)
        versions[job_dir.name] = job_claude_code_version(job)
        trials += [_trial(job_dir, trial, Path(analysis_root)) for trial in job]
    return {
        "claude_code_versions": versions,
        "trials": trials,
        "shares": _shares(trials),
        "agent_test_runs": _pooled(trials),
        "cost": _cost(trials),
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
    with a cross-check.json (PRD section 5, the cross-check)."""
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
    to the trials with no file-writing Bash call (PRD section 5)."""
    def counted(test) -> dict:
        count = sum(1 for t in trials if test(t["bash"]))
        return {"count": count, "share": share(count, len(trials))}

    return {
        "trials": len(trials),
        "file_writing_bash": counted(lambda b: b["file_writing_bash"]),
        "bash_writes_test_or_implementation":
            counted(lambda b: b["bash_writes_test_or_implementation"]),
        "offline_replay_applies": counted(lambda b: not b["file_writing_bash"]),
    }


def _trial(job_dir: Path, trial: Trial, analysis_root: Path) -> dict:
    out = analysis_root / job_dir.name / trial.name
    metrics = analyze_folder(trial.path, analysis_root)
    failed = trace_check(trial)
    usage = trial.usage
    return {
        "job": job_dir.name,
        "trial": trial.name,
        "trace_check": {"passed": not failed, "failed_checks": failed},
        "replay": read_json(out / "replay-works.json"),
        "test_first_order": metrics["test_first_order"]["verdict"],
        "red_to_green_order": (metrics["red_to_green_order"] or {}).get("verdict"),
        "tdd_loop": metrics["tdd_loop"],
        "bash": metrics["bash"],
        "agent_test_runs": read_json(out / CROSS_CHECK_FILE),
        "model_tier": trial.model_tier,
        "local": trial.local,
        "cost": {
            # L5: Claude Code's total_cost_usd is not a money cost for a local model.
            "cost_usd": 0 if trial.local else usage.cost_usd,
            "input_tokens": usage.input_tokens,
            "cache_tokens": usage.cache_tokens,
            "output_tokens": usage.output_tokens,
            "duration_sec": trial.duration_sec,
            "turns": trial.turns,
        },
    }


def write_summary(job_dirs: list[Path | str], analysis_root: Path | str) -> tuple[Path, Path]:
    """Writes analysis/phase0-summary.md and .json; returns their paths."""
    summary = summarize(job_dirs, analysis_root)
    root = Path(analysis_root)
    root.mkdir(parents=True, exist_ok=True)
    markdown, data = root / f"{SUMMARY_NAME}.md", root / f"{SUMMARY_NAME}.json"
    markdown.write_text(render_markdown(summary), encoding="utf-8")
    data.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return markdown, data


def render_markdown(summary: dict) -> str:
    def pct(value):
        return "-" if value is None else f"{value:.0%}"

    def num(value, digits=0):
        return "-" if value is None else f"{value:,.{digits}f}"

    versions = ", ".join(f"{job} {v or '-'}" for job, v in summary["claude_code_versions"].items())
    lines = ["# Phase 0 summary", "", f"Claude Code version for each job: {versions}.", "",
             "## Trials", "",
             "| Job | Trial | Model tier | Trace check | Replay | Test-first order "
             "| Red-to-green order | TDD loop (cycles / never seen red / refactor steps) "
             "| Coverage | Agreement |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for t in summary["trials"]:
        check = "pass" if t["trace_check"]["passed"] else \
            "fail: " + ", ".join(t["trace_check"]["failed_checks"])
        replay = "not run" if t["replay"] is None else \
            "works" if t["replay"]["works"] else "fails: " + "; ".join(t["replay"]["causes"])
        loop = t["tdd_loop"]
        loop = "-" if loop is None else \
            f"{loop['cycles']} / {loop['tests_never_seen_red']} / {loop['refactor_steps']}"
        runs = t["agent_test_runs"] or {}
        lines.append(
            f"| {t['job']} | {t['trial']} | {t['model_tier']} | {check} | {replay} "
            f"| {t['test_first_order']} | {t['red_to_green_order'] or '-'} | {loop} "
            f"| {pct(runs.get('coverage'))} | {pct(runs.get('agreement'))} |")

    shares = summary["shares"]

    def counted(text, key):
        s = shares[key]
        return f"- {text}: {s['count']} of {shares['trials']} ({pct(s['share'])})."

    runs = summary["agent_test_runs"]
    lines += ["", "## Bash file writes", "",
              counted("Trials with a file-writing `Bash` call", "file_writing_bash"),
              counted("Trials where a `Bash` call writes a test or implementation file",
                      "bash_writes_test_or_implementation"),
              counted("Trials where offline replay applies (no file-writing `Bash` call)",
                      "offline_replay_applies"),
              "", "## Agent test runs", "",
              f"- Coverage: {runs['covered_snapshots']} of {runs['snapshots']} snapshots "
              f"({pct(runs['coverage'])}).",
              f"- Agreement: {runs['agreeing_runs']} of {runs['compared_runs']} compared runs "
              f"({pct(runs['agreement'])}).",
              "", "## Cost for each model tier", "",
              "The local tier's money cost is zero (L5); its token counts are kept. "
              "Values per trial are means.", "",
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
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m analyze.summary",
        description="Write the Phase 0 summary of one or more jobs, as markdown and JSON.")
    parser.add_argument("job_dirs", nargs="+", type=Path, help="results/<job-id>")
    parser.add_argument("--analysis", type=Path, default=REPO_ROOT / "analysis",
                        help="analysis root holding <job-id>/<trial>/; the summary goes here")
    args = parser.parse_args(argv)
    try:
        markdown, data = write_summary(args.job_dirs, args.analysis)
    except MixedClaudeCodeVersions as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"wrote {markdown} and {data}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
