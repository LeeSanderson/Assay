"""The four codebase-ladder job files and the plan of the experiment (PRD
section 20, "The matrix"; issue #82), read through Harbor's own job model.
Modeled on test_ladder_job_files.py."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

from assay.cli import main
from tests.job_files import INSTRUMENT_INSTRUCTION, REPO_ROOT, expand_trials, load_job, trial_key
from tests.task_packs import CODEBASE_PACKS

pytestmark = pytest.mark.usefixtures("run_from_repo_root")

HOSTED = ("anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5")
LOCAL = ("laguna-s-2.1",)
JOBS = {  # in run order: job file -> (model tiers, condition)
    "codebase-ladder-hosted-control.yaml": (HOSTED, "control"),
    "codebase-ladder-hosted-tdd.yaml": (HOSTED, "instrument-tdd"),
    "codebase-ladder-local-control.yaml": (LOCAL, "control"),
    "codebase-ladder-local-tdd.yaml": (LOCAL, "instrument-tdd"),
}
# The rungs that are built so far, in ladder order (PRD section 20, "The
# rungs"): rung A is the poker pack, unchanged; rungs B and C the first
# purpose-written packs. A later rung adds its slug here.
BUILT_RUNGS = ("poker", "shop-promotions-stub", "shop-promotions-small")
PLANNED_RUNGS = ("poker", "shop-promotions-stub", "shop-promotions-small",
                 "shop-returns-small", "shop-returns-medium")


def load_summary_module():
    spec = importlib.util.spec_from_file_location(
        "codebase_ladder_summary",
        REPO_ROOT / "experiments" / "codebase-ladder" / "summary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_summary_orders_the_five_planned_rungs_a_to_e():
    assert load_summary_module().RUNGS == PLANNED_RUNGS


def test_the_experiment_runs_the_four_jobs_in_ladder_order_with_the_ladder_evaluations():
    config = tomllib.loads(
        (REPO_ROOT / "experiments" / "codebase-ladder" / "experiment.toml").read_text("utf-8"))

    assert config["jobs"] == [f"jobs/{name}" for name in JOBS]
    assert config["evaluations"] == ["replay", "agent-runs", "trajectory"]
    assert config["summary"]["use"] == "./summary.py"


def ladder_key(trial) -> tuple[str, str, str, str]:
    """(model, condition, language, rung) for one trial config."""
    return (*trial_key(trial), Path(trial.task.path).parts[-1])


@pytest.mark.parametrize("name", JOBS)
def test_each_job_expands_to_its_tiers_and_condition_on_every_built_rung_and_language(name):
    tiers, condition = JOBS[name]

    trials = expand_trials(load_job(name))

    assert sorted(ladder_key(t) for t in trials) == sorted(
        (tier, condition, language, rung)
        for tier in tiers for language in ("go", "typescript") for rung in BUILT_RUNGS)


def test_the_jobs_list_the_packs_in_rung_order_typescript_then_go():
    for name in JOBS:
        paths = [Path(t.path).as_posix() for t in load_job(name).tasks]
        assert paths == [f"tasks/{language}/{rung}" for rung in BUILT_RUNGS
                         for language in ("typescript", "go")], name


def test_every_purpose_written_pack_is_in_the_jobs():
    paths = {Path(t.path).as_posix() for t in load_job("codebase-ladder-hosted-control.yaml").tasks}

    assert {p.path.relative_to(REPO_ROOT).as_posix() for p in CODEBASE_PACKS} <= paths


def test_the_four_jobs_hold_12_trials_for_each_built_rung():
    trials = [t for name in JOBS for t in expand_trials(load_job(name))]

    assert len(trials) == 12 * len(BUILT_RUNGS)  # 8 hosted and 4 local on each rung
    assert sum(1 for t in trials if t.agent.model_name in LOCAL) == 4 * len(BUILT_RUNGS)
    assert len({ladder_key(t) for t in trials}) == len(trials)


def test_every_purpose_written_pack_has_an_agent_timeout_of_3600_seconds_and_poker_keeps_1800():
    for name in JOBS:
        for task in load_job(name).tasks:
            config = tomllib.loads((REPO_ROOT / task.path / "task.toml").read_text("utf-8"))
            slug = Path(task.path).parts[-1]
            assert config["agent"]["timeout_sec"] == (1800 if slug == "poker" else 3600), task


def test_every_agent_shares_the_phase0_claude_code_version_and_l9_settings():
    agents = [a for name in (*JOBS, "ladder-hosted-control.yaml") for a in load_job(name).agents]

    assert len({a.kwargs.get("version") for a in agents}) == 1
    for agent in agents:
        assert agent.import_path == "instruments.agent:InstrumentedClaudeCode"
        assert agent.env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] == "1"
        assert agent.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


@pytest.mark.parametrize("name", JOBS)
def test_every_job_has_one_attempt(name):
    assert load_job(name).n_attempts == 1


@pytest.mark.parametrize("name", ["codebase-ladder-hosted-control.yaml",
                                  "codebase-ladder-local-control.yaml"])
def test_control_jobs_give_no_variant_parts(name):
    config = load_job(name)

    for agent in config.agents:
        assert not agent.skills
        assert "config" not in agent.kwargs
        assert not agent.mcp_servers
    assert not config.extra_instruction_paths
    assert not config.extra_instructions


@pytest.mark.parametrize("name", ["codebase-ladder-hosted-tdd.yaml",
                                  "codebase-ladder-local-tdd.yaml"])
def test_tdd_jobs_give_the_skill_and_its_extra_instruction(name):
    config = load_job(name)

    assert all(agent.skills for agent in config.agents)
    assert [Path(p).as_posix() for p in config.extra_instruction_paths] == [INSTRUMENT_INSTRUCTION]


@pytest.mark.parametrize("name", ["codebase-ladder-hosted-control.yaml",
                                  "codebase-ladder-hosted-tdd.yaml"])
def test_hosted_jobs_keep_harbors_timeouts(name):
    config = load_job(name)

    assert config.timeout_multiplier == 1.0
    assert all("ANTHROPIC_BASE_URL" not in agent.env for agent in config.agents)


@pytest.mark.parametrize("name", ["codebase-ladder-local-control.yaml",
                                  "codebase-ladder-local-tdd.yaml"])
def test_local_jobs_use_one_server_slot_timeout_multiplier_3_and_the_one_address_setting(name):
    config = load_job(name)

    (agent,) = config.agents
    assert agent.concurrency_group is not None  # L3
    assert agent.n_concurrent == 1
    assert config.n_concurrent_trials == 1
    assert config.timeout_multiplier == 3.0  # L4
    assert agent.env["ANTHROPIC_BASE_URL"] == "${ASSAY_LOCAL_BASE_URL}"  # L10
    # The address itself is in no job file.
    assert "://" not in (REPO_ROOT / "jobs" / name).read_text(encoding="utf-8")


def test_the_dry_run_plans_12_trials_for_each_built_rung_at_no_cost(monkeypatch, capsys):
    monkeypatch.setattr("assay.cli.ENV_FILE", REPO_ROOT / "no.env")
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", "http://192.0.2.1:8080")

    def never_harbor(args):
        raise AssertionError(f"a dry run called Harbor: {args}")

    assert main(["experiment", "codebase-ladder", "--dry-run"], run_harbor=never_harbor) == 0

    out = capsys.readouterr().out
    names = [Path(name).stem for name in JOBS]
    assert [out.index(n) for n in names] == sorted(out.index(n) for n in names)
    assert f"{12 * len(BUILT_RUNGS)} expected trials" in out  # 36 on rungs A to C
    cells = [line.split() for line in out.splitlines() if line.startswith("  cell ")]
    # cell <n> <harness> <model tier> <condition> <language>: n is the rungs of the cell.
    assert sorted((c[3], c[4], c[5], int(c[1])) for c in cells) == sorted(
        (tier, condition, language, len(BUILT_RUNGS))
        for tiers, condition in JOBS.values() for tier in tiers
        for language in ("typescript", "go"))
