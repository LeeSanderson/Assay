"""The experiment-local difficulty-ladder summary,
experiments/difficulty-ladder/summary.py (PRD Part II, "The difficulty
ladder"; issue #71), through the CLI's `main` on a copy of the committed
experiment, its job files, variants and task packs, with a fake Harbor and a
fake `Containers`."""

import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from assay.cli import main
from tests.fake_containers import FakeContainers
from tests.test_experiment_failures import exception
from tests.test_phase0_summary import REPO_ROOT, REWARD, FakeHarbor, no_env_file  # noqa: F401

EXPERIMENT = "difficulty-ladder"
HOSTED = ["ladder-hosted-control", "ladder-hosted-tdd"]
LOCAL = ["ladder-local-control", "ladder-local-tdd"]
HAIKU, SONNET, LOCAL_MODEL = ("anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5",
                              "laguna-s-2.1")
RUNG = "split-second-stopwatch"
TIERS = {HAIKU: 0, SONNET: 1, LOCAL_MODEL: 0}  # each tier's agent index in its jobs


def name(language, slug, agent, attempt):
    """A short trial name, unique for each rung (long names pass the Windows path limit)."""
    return f"{slug.split('-')[0]}-{language[:2]}__{agent}{attempt}"


def trial(job, model, language, rung=RUNG):
    """The <job>/<trial> name that the fake Harbor gives a trial."""
    return f"{job}/{name(language, rung, TIERS[model], 0)}"


def agent_time(seconds):
    """A trial change: the agent ran for this many seconds."""
    start = datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)

    def change(builder):
        builder.result["agent_execution"] = {
            "started_at": start.isoformat(),
            "finished_at": (start + timedelta(seconds=seconds)).isoformat()}
    return change


def failed(passed):
    """A trial change: the agent's code passes `passed` of the 29 reference tests."""
    def change(builder):
        builder.reward = {**REWARD, "reward": 0, "reference_passed": passed}
    return change


def timed_out(builder):
    """A trial change: the agent ran out of time, and its code fails the tests."""
    exception("AgentTimeoutError")(builder)
    failed(0)(builder)


def usage(cost_usd, input_tokens, cache_tokens=800, output_tokens=100):
    """A trial change: Claude Code's cost and token counts."""
    def change(builder):
        builder.result["agent_result"].update(
            cost_usd=cost_usd, n_input_tokens=input_tokens, n_cache_tokens=cache_tokens,
            n_output_tokens=output_tokens)
    return change


def changes(*parts):
    def change(builder):
        for part in parts:
            part(builder)
    return change


def harbor(outcomes=None, seconds=120, rungs=(RUNG,)):
    """A fake Harbor whose every trial has an agent time of `seconds`, plus
    the given changes of each <job>/<trial>."""
    outcomes = outcomes or {}
    every = {trial(job, model, language, rung)
             for job, models in ((HOSTED[0], (HAIKU, SONNET)), (HOSTED[1], (HAIKU, SONNET)),
                                 (LOCAL[0], (LOCAL_MODEL,)), (LOCAL[1], (LOCAL_MODEL,)))
             for model in models for language in ("go", "typescript") for rung in rungs}
    return FakeHarbor(name=name, outcomes={
        t: [changes(agent_time(seconds), *outcomes.get(t, []))] for t in every})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the committed ladder experiment, with its job files,
    variants and task packs."""
    shutil.copytree(REPO_ROOT / "experiments" / EXPERIMENT, tmp_path / "experiments" / EXPERIMENT,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for folder in ("jobs", "variants", "tasks"):
        shutil.copytree(REPO_ROOT / folder, tmp_path / folder,
                        ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def add_rung(repo, rung):
    """Adds a stand-in rung to the four jobs of the copy: the rung-1 task
    packs under the rung's slug."""
    for language in ("typescript", "go"):
        shutil.copytree(repo / "tasks" / language / RUNG, repo / "tasks" / language / rung)
    for job in HOSTED + LOCAL:
        path = repo / "jobs" / f"{job}.yaml"
        text = path.read_text(encoding="utf-8")
        line = f"  - path: tasks/go/{RUNG}\n"
        assert line in text
        path.write_text(text.replace(line, line + "".join(
            f"  - path: tasks/{language}/{rung}\n" for language in ("typescript", "go"))),
                        encoding="utf-8")


def experiment(fake, *args):
    return main(["experiment", EXPERIMENT, *args], run_harbor=fake, containers=FakeContainers())


def hosted(*args):
    return [arg for job in HOSTED for arg in ("--job", job)] + list(args)


def summary(repo):
    folder = repo / "analysis" / EXPERIMENT / "summary"
    return (json.loads((folder / "ladder-summary.json").read_text(encoding="utf-8")),
            (folder / "ladder-summary.md").read_text(encoding="utf-8"))


def section(markdown, heading):
    """The text of a `## heading` section of the markdown."""
    return markdown.split(f"## {heading}\n")[1].split("\n## ")[0]


def table(markdown, heading):
    """The rows of a section's table, each by its column headers."""
    lines = [line for line in section(markdown, heading).splitlines() if line.startswith("|")]
    header, *rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    return [dict(zip(header, r)) for r in rows[1:]]


def row(markdown, label, heading="Pass grid"):
    """The cells of the table row of a section that starts with this label."""
    [found] = [line for line in section(markdown, heading).splitlines()
               if line.startswith(f"| {label} |")]
    return [cell.strip() for cell in found.strip("|").split("|")][1:]


def test_the_pass_grid_shows_passed_failed_timeout_and_not_run_cells(repo):
    fake = harbor({trial(HOSTED[0], HAIKU, "go"): [failed(20)],
                   trial(HOSTED[1], SONNET, "typescript"): [timed_out]})

    assert experiment(fake, *hosted()) == 0

    data, markdown = summary(repo)
    assert data["rungs"] == ["split-second-stopwatch", "wordy", "poker", "bowling",
                             "two-bucket", "alphametics"]
    assert "## Pass grid" in markdown
    assert row(markdown, "Model tier · condition · language") == data["rungs"]
    assert row(markdown, f"{HAIKU} · control · go") == ["20/29 ✗"] + ["—"] * 5
    assert row(markdown, f"{HAIKU} · control · typescript")[0] == "29/29 ✓"
    assert row(markdown, f"{SONNET} · instrument-tdd · typescript")[0] == "timeout"
    # The local jobs have not run.
    assert row(markdown, f"{LOCAL_MODEL} · control · go") == ["—"] * 6
    # Rows go by model tier, then condition, then language.
    grid = section(markdown, "Pass grid").strip().split("\n\n")[0].splitlines()[2:]
    assert [line.split(" | ")[0].lstrip("| ") for line in grid] == [
        f"{tier} · {condition} · {language}" for tier in (HAIKU, SONNET, LOCAL_MODEL)
        for condition in ("control", "instrument-tdd") for language in ("go", "typescript")]


def test_the_rollup_totals_every_kept_trial_and_means_the_passed_ones_only(repo):
    add_rung(repo, "wordy")
    fake = harbor({
        trial(HOSTED[0], HAIKU, "go"): [usage(0.30, 1000, 600, 50), agent_time(100)],
        trial(HOSTED[0], HAIKU, "go", "wordy"): [usage(0.70, 3000, 1000, 150), agent_time(900),
                                                 failed(20)],
        trial(HOSTED[0], HAIKU, "typescript"): [failed(3)],
        trial(HOSTED[0], HAIKU, "typescript", "wordy"): [timed_out],
    }, rungs=(RUNG, "wordy"))

    assert experiment(fake, *hosted()) == 0

    data, markdown = summary(repo)
    assert row(markdown, f"{HAIKU} · control · go")[:3] == ["29/29 ✓", "20/29 ✗", "—"]
    assert row(markdown, "Model tier · condition · language", "Rollup") == [
        "Passed", "Input tokens", "Input tokens per passed trial", "Cached tokens",
        "Cached tokens per passed trial", "Output tokens", "Output tokens per passed trial",
        "USD", "USD per passed trial", "Agent time (s)", "Agent time (s) per passed trial"]
    # Totals over the passed and the failed trial; means over the passed one only.
    assert row(markdown, f"{HAIKU} · control · go", "Rollup") == [
        "1 of 2", "4,000", "1,000", "1,600", "600", "200", "50", "1.00", "0.30", "1,000", "100"]
    # No passed trial: every mean is "-".
    assert row(markdown, f"{HAIKU} · control · typescript", "Rollup") == [
        "0 of 2", "2,000", "-", "1,600", "-", "200", "-", "1.00", "-", "240", "-"]
    assert ("Failed trials count in the totals but not in the means per passed trial."
            in section(markdown, "Rollup"))
    [haiku_go] = [r for r in data["rollup"]
                  if (r["model_tier"], r["condition"], r["language"]) == (HAIKU, "control", "go")]
    assert (haiku_go["kept"], haiku_go["passed"]) == (2, 1)
    assert haiku_go["totals"]["cost_usd"] == pytest.approx(1.0)
    assert haiku_go["means_per_passed_trial"]["agent_time_sec"] == 100


def test_a_discarded_trial_is_left_out_of_the_rollup_but_counted_in_the_hosted_cost(repo):
    discarded = trial(HOSTED[1], SONNET, "go")
    fake = harbor({discarded: [exception("ApiOverloadedError")]})

    assert experiment(fake, *hosted()) == 0

    data, markdown = summary(repo)
    assert row(markdown, f"{SONNET} · instrument-tdd · go") == ["—"] * 6
    assert row(markdown, f"{SONNET} · instrument-tdd · go", "Rollup")[:3] == ["-", "-", "-"]
    assert row(markdown, f"{SONNET} · instrument-tdd · typescript", "Rollup")[:2] == [
        "1 of 1", "1,000"]
    cost = data["hosted_cost"]
    assert (cost["kept_usd"], cost["discarded_usd"]) == (pytest.approx(3.5), pytest.approx(0.5))
    assert cost["total_usd"] == pytest.approx(4.0)
    assert "4.00 USD: 3.50 kept + 0.50 discarded" in section(markdown, "Total hosted cost")
    # The discard and the local jobs' trials are missing.
    missing = section(markdown, "Missing trials")
    assert "5 of 12 expected trials missing." in missing
    assert (f"- claude-code · {SONNET} · instrument-tdd · go: 0 of 1 kept\n"
            f"  - `{discarded}` discarded, ApiOverloadedError") in missing
    assert f"- claude-code · {LOCAL_MODEL} · control · go: 0 of 1 kept\n" \
           "  - 1 trial not run yet" in missing
    assert data["missing_trials"]["count"] == 5
    # The sections go in order.
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == ["## Pass grid", "## Rollup", "## Missing trials", "## Trials",
                        "## Total hosted cost"]


def test_a_local_trial_has_no_money_cost_and_gives_its_model_and_date(repo, monkeypatch):
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", "http://localhost:8080")
    local = trial(LOCAL[1], LOCAL_MODEL, "go")

    def started(builder):
        builder.result["started_at"] = "2026-02-03T04:05:06Z"
    fake = harbor({local: [started]})

    assert experiment(fake) == 0

    data, markdown = summary(repo)
    assert data["missing_trials"]["count"] == 0
    # L5: the cost Claude Code reports for a local model is no money cost.
    local_row = row(markdown, f"{LOCAL_MODEL} · instrument-tdd · go", "Rollup")
    assert local_row[:2] == ["1 of 1", "1,000"]
    assert local_row[7:9] == ["-", "-"]
    assert row(markdown, f"{HAIKU} · control · go", "Rollup")[7:9] == ["0.50", "0.50"]
    assert data["hosted_cost"]["total_usd"] == pytest.approx(4.0)
    # The trials table gives the model and the date of each local trial.
    trials = {f"{r['Job']}/{r['Trial']}": r for r in table(markdown, "Trials")}
    assert trials[local]["Local model"] == "laguna-s-2.1, 2026-02-03"
    hosted_row = trials[trial(HOSTED[0], HAIKU, "go")]
    assert (hosted_row["Local model"], hosted_row["Rung"]) == ("-", RUNG)
