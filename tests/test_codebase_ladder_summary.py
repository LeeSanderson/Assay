"""The experiment-local codebase-ladder summary,
experiments/codebase-ladder/summary.py (PRD section 20, "The summary"; issue
#82), through the CLI's `main` on a copy of the committed experiment, its job
files, variants and task packs, with a fake Harbor and a fake `Containers`.
Modeled on test_ladder_summary.py."""

from __future__ import annotations

import json
import re
import shutil

import pytest

from assay.cli import main
from tests.fake_containers import FakeContainers
from tests.test_experiment_failures import exception
from tests.test_ladder_summary import (agent_time, changes, name, row, section, table,
                                       timed_out, usage)
from tests.test_phase0_summary import REPO_ROOT, REWARD, FakeHarbor, no_env_file  # noqa: F401

EXPERIMENT = "codebase-ladder"
HOSTED = ["codebase-ladder-hosted-control", "codebase-ladder-hosted-tdd"]
LOCAL = ["codebase-ladder-local-control", "codebase-ladder-local-tdd"]
HAIKU, SONNET, LOCAL_MODEL = ("anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5",
                              "laguna-s-2.1")
TIERS = {HAIKU: 0, SONNET: 1, LOCAL_MODEL: 0}  # each tier's agent index in its jobs
POKER, STUB = "poker", "shop-promotions-stub"  # rungs A and B
RUNGS = (POKER, STUB)
HEADERS = ["A: poker", "B: shop-promotions-stub", "C: shop-promotions-small",
           "D: shop-returns-small", "E: shop-returns-medium"]
# A purpose-written pack's reward: the feature tests and the seed suite.
CODEBASE_REWARD = {**REWARD, "seed_suite_passed": 40, "seed_suite_total": 40}


def trial(job, model, language, rung=POKER):
    """The <job>/<trial> name that the fake Harbor gives a trial."""
    return f"{job}/{name(language, rung, TIERS[model], 0)}"


def rewarded(**fields):
    """A trial change: the verifier's reward, with these fields changed."""
    def change(builder):
        builder.reward = {**CODEBASE_REWARD, **fields}
    return change


def harbor(outcomes=None, seconds=120):
    """A fake Harbor whose every trial has an agent time of `seconds` and a
    reward with seed-suite counts, plus the given changes of each <job>/<trial>."""
    outcomes = outcomes or {}
    every = {trial(job, model, language, rung)
             for job, models in ((HOSTED[0], (HAIKU, SONNET)), (HOSTED[1], (HAIKU, SONNET)),
                                 (LOCAL[0], (LOCAL_MODEL,)), (LOCAL[1], (LOCAL_MODEL,)))
             for model in models for language in ("go", "typescript") for rung in RUNGS}
    return FakeHarbor(name=name, outcomes={
        t: [changes(agent_time(seconds), rewarded(), *outcomes.get(t, []))] for t in every})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the committed codebase-ladder experiment, with its job files,
    variants and the task packs of rungs A and B."""
    shutil.copytree(REPO_ROOT / "experiments" / EXPERIMENT, tmp_path / "experiments" / EXPERIMENT,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for folder in ("jobs", "variants"):
        shutil.copytree(REPO_ROOT / folder, tmp_path / folder,
                        ignore=shutil.ignore_patterns("__pycache__"))
    for rung in RUNGS:
        for language in ("typescript", "go"):
            shutil.copytree(REPO_ROOT / "tasks" / language / rung,
                            tmp_path / "tasks" / language / rung,
                            ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    # Only rungs A and B in the four jobs, so that the tests do not depend on
    # how many rungs the committed jobs hold.
    tasks = "tasks:\n" + "".join(f"  - path: tasks/{language}/{rung}\n"
                                 for rung in RUNGS for language in ("typescript", "go"))
    for job in HOSTED + LOCAL:
        path = tmp_path / "jobs" / f"{job}.yaml"
        text, found = re.subn(r"^tasks:\n.*?(?=^agents:)", tasks + "\n",
                              path.read_text(encoding="utf-8"), flags=re.M | re.S)
        assert found == 1, path
        path.write_text(text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def experiment(fake, *args):
    return main(["experiment", EXPERIMENT, *args], run_harbor=fake, containers=FakeContainers())


def hosted(*args):
    return [arg for job in HOSTED for arg in ("--job", job)] + list(args)


def summary(repo):
    folder = repo / "analysis" / EXPERIMENT / "summary"
    return (json.loads((folder / "codebase-ladder-summary.json").read_text(encoding="utf-8")),
            (folder / "codebase-ladder-summary.md").read_text(encoding="utf-8"))


def test_the_pass_grid_marks_passed_failed_seed_suite_broken_timeout_and_not_run_cells(repo):
    fake = harbor({
        # The feature is not complete; the seed suite is intact: no seed mark.
        trial(HOSTED[0], HAIKU, "go", STUB): [rewarded(reward=0, reference_passed=20)],
        # The feature is not complete, and the agent broke the seed suite.
        trial(HOSTED[0], HAIKU, "typescript", STUB): [
            rewarded(reward=0, reference_passed=24, reference_total=30, seed_suite_passed=38)],
        # The feature is complete, but the agent broke the seed suite.
        trial(HOSTED[1], SONNET, "go", STUB): [rewarded(reward=0, seed_suite_passed=39)],
        trial(HOSTED[1], SONNET, "typescript", STUB): [timed_out],
    })

    assert experiment(fake, *hosted()) == 0

    data, markdown = summary(repo)
    assert data["rungs"] == ["poker", "shop-promotions-stub", "shop-promotions-small",
                             "shop-returns-small", "shop-returns-medium"]
    assert markdown.startswith("# Codebase ladder summary\n")
    assert row(markdown, "Model tier · condition · language") == HEADERS
    assert row(markdown, f"{HAIKU} · control · go") == ["29/29 ✓", "20/29 ✗"] + ["—"] * 3
    assert row(markdown, f"{HAIKU} · control · typescript")[:2] == [
        "29/29 ✓", "24/30 ✗ seed 38/40"]
    assert row(markdown, f"{SONNET} · instrument-tdd · go")[1] == "29/29 ✗ seed 39/40"
    assert row(markdown, f"{SONNET} · instrument-tdd · typescript")[1] == "timeout"
    # The local jobs have not run.
    assert row(markdown, f"{LOCAL_MODEL} · control · go") == ["—"] * 5
    [stub] = [s for r in data["grid"]
              if (r["model_tier"], r["condition"], r["language"]) == (HAIKU, "control",
                                                                      "typescript")
              for s in r["rungs"][STUB]]
    assert (stub["seed_suite_passed"], stub["seed_suite_total"]) == (38, 40)
    # Rows go by model tier, then condition, then language.
    grid = section(markdown, "Pass grid").strip().split("\n\n")[0].splitlines()[2:]
    assert [line.split(" | ")[0].lstrip("| ") for line in grid] == [
        f"{tier} · {condition} · {language}" for tier in (HAIKU, SONNET, LOCAL_MODEL)
        for condition in ("control", "instrument-tdd") for language in ("go", "typescript")]


def test_the_pass_grid_notes_the_seed_mark_the_poker_floor_and_the_provisional_boundary(repo):
    assert experiment(harbor(), *hosted()) == 0

    _, markdown = summary(repo)
    note = section(markdown, "Pass grid")
    assert "`seed passed/total`" in note
    assert "Rung A is the poker task pack of the difficulty ladder, without change." in note
    assert ("Each failure boundary is provisional while each cell has one repetition."
            in note)


def test_a_trial_without_seed_suite_counts_shows_no_seed_mark(repo):
    # Rung A's poker packs and any trial run before the verifier wrote the
    # seed-suite counts.
    def without_seed_suite(builder):
        builder.reward = {**REWARD, "reward": 0, "reference_passed": 3}
    fake = harbor({trial(HOSTED[0], HAIKU, "go"): [without_seed_suite]})

    assert experiment(fake, *hosted()) == 0

    _, markdown = summary(repo)
    assert row(markdown, f"{HAIKU} · control · go")[0] == "3/29 ✗"


def test_the_rollup_missing_trials_trials_table_and_hosted_cost(repo):
    discarded = trial(HOSTED[1], SONNET, "go", STUB)
    fake = harbor({
        trial(HOSTED[0], HAIKU, "go"): [usage(0.30, 1000, 600, 50), agent_time(100)],
        trial(HOSTED[0], HAIKU, "go", STUB): [usage(0.70, 3000, 1000, 150), agent_time(900),
                                              rewarded(reward=0, seed_suite_passed=30)],
        discarded: [exception("ApiOverloadedError")],
    })

    assert experiment(fake, *hosted()) == 0

    data, markdown = summary(repo)
    # Rollup: totals over the passed and the failed trial; means over the passed one only.
    assert row(markdown, f"{HAIKU} · control · go", "Rollup") == [
        "1 of 2", "4,000", "1,000", "1,600", "600", "200", "50", "1.00", "0.30", "1,000", "100"]
    assert ("Failed trials count in the totals but not in the means per passed trial."
            in section(markdown, "Rollup"))
    # The discard and the local jobs' trials are missing.
    missing = section(markdown, "Missing trials")
    assert "9 of 24 expected trials missing." in missing
    assert (f"- claude-code · {SONNET} · instrument-tdd · go: 1 of 2 kept"
            in missing)
    assert f"  - `{discarded}` discarded, ApiOverloadedError" in missing
    assert data["missing_trials"]["count"] == 9
    # The trials table names each trial's rung, and keeps its score.
    trials = {f"{r['Job']}/{r['Trial']}": r for r in table(markdown, "Trials")}
    stub = trials[trial(HOSTED[0], HAIKU, "go", STUB)]
    assert (stub["Rung"], stub["Local model"], stub["Score"]) == (
        "B: shop-promotions-stub", "-", "29 of 29 ✗")
    assert trials[trial(HOSTED[0], HAIKU, "go")]["Rung"] == "A: poker"
    # The hosted cost: 15 kept trials, 13 at 0.50 and two at 0.30 and 0.70,
    # plus the discard.
    cost = data["hosted_cost"]
    assert cost["kept_usd"] == pytest.approx(7.5)
    assert cost["discarded_usd"] == pytest.approx(0.5)
    assert "8.00 USD: 7.50 kept + 0.50 discarded" in section(markdown, "Total hosted cost")
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == ["## Pass grid", "## Rollup", "## Missing trials", "## Trials",
                        "## Total hosted cost"]


def test_a_local_trial_has_no_money_cost_and_gives_its_model_and_date(repo, monkeypatch):
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", "http://localhost:8080")
    local = trial(LOCAL[1], LOCAL_MODEL, "go", STUB)

    def started(builder):
        builder.result["started_at"] = "2026-02-03T04:05:06Z"
    fake = harbor({local: [started]})

    assert experiment(fake) == 0

    data, markdown = summary(repo)
    assert data["missing_trials"]["count"] == 0
    assert "## Missing trials" not in markdown
    local_row = row(markdown, f"{LOCAL_MODEL} · instrument-tdd · go", "Rollup")
    assert local_row[:2] == ["2 of 2", "2,000"]
    assert local_row[7:9] == ["-", "-"]
    trials = {f"{r['Job']}/{r['Trial']}": r for r in table(markdown, "Trials")}
    assert trials[local]["Local model"] == "laguna-s-2.1, 2026-02-03"
    assert data["hosted_cost"]["total_usd"] == pytest.approx(8.0)
