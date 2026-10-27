"""PROTOTYPE (wayfinder #49): today's analyze/summary.py on the summary contract,
on paper. Experiment-local, because Phase 0's acceptance numbers are its own.
"""

from analyze.experiment_contract_PROTOTYPE import ExperimentView, Summary


def _summarize(view: ExperimentView, options: dict, out) -> None:
    trials = [{
        "job": t.job, "trial": t.trial, "cell": t.cell,
        # was: read_json(analysis/<job>/<trial>/replay-works.json)
        "replay": {k: t.results["replay"][k] for k in ("works", "causes")},
        # was: analyze_folder(...) called again here; now trajectory's stored value
        **t.results["trajectory"],
        # was: read_json(.../cross-check.json)
        "agent_test_runs": t.results["agent-runs"]["cross_check"],
        "cost": "from the trial record: cost_usd (0 when local), tokens, time, turns",
    } for t in view.trials]

    # Fit gained: the 15 GBP criterion counts "each trial that runs again". Today
    # that is unknowable once the trial folder is replaced; now the log has it.
    discarded_usd = sum(e.get("cost_usd") or 0 for e in view.log
                        if e["event"] == "trial-discarded"
                        and e["cell"]["model_tier"] != "local/reference")

    # Friction: the trace-check pass/fail column goes away (only passing trials
    # reach the summary); failures show as discarded counts per cell instead.

    # Friction: _local_trial reads ATIF details (system steps, cached tokens per
    # turn) that are not trial-record fields. Either they join the record (#50),
    # or a small local-tier evaluation extracts them -- which needs the raw Harbor
    # trial folder, so TrialInput would need an escape hatch to it.
    ...  # render phase0-summary.md / .json into `out`, as today


SUMMARY = Summary(summarize=_summarize)
