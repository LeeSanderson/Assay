"""The four difficulty-ladder job files (PRD Part II, "The difficulty
ladder"; issue #71), read through Harbor's own job model."""

import importlib.util
from pathlib import Path

import pytest

from tests.test_job_files import (INSTRUMENT_INSTRUCTION, REPO_ROOT, expand_trials, load_job,
                                  run_from_repo_root, trial_key)  # noqa: F401 (fixture)

HOSTED = ("anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5")
LOCAL = ("laguna-s-2.1",)
JOBS = {  # in run order: job file -> (model tiers, condition)
    "ladder-hosted-control.yaml": (HOSTED, "control"),
    "ladder-hosted-tdd.yaml": (HOSTED, "instrument-tdd"),
    "ladder-local-control.yaml": (LOCAL, "control"),
    "ladder-local-tdd.yaml": (LOCAL, "instrument-tdd"),
}


def ladder_rungs() -> list[str]:
    """The rungs that the summary orders (RUNGS in the experiment's
    summary.py) whose task packs exist in both languages. A rung ticket adds
    its packs; this list follows."""
    spec = importlib.util.spec_from_file_location(
        "ladder_summary", REPO_ROOT / "experiments" / "difficulty-ladder" / "summary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [rung for rung in module.RUNGS
            if all((REPO_ROOT / "tasks" / language / rung).is_dir()
                   for language in ("typescript", "go"))]


RUNGS = ladder_rungs()


def test_rung_one_is_on_the_ladder():
    assert RUNGS[0] == "split-second-stopwatch"


def ladder_key(trial) -> tuple[str, str, str, str]:
    """(model, condition, language, rung) for one trial config."""
    return (*trial_key(trial), Path(trial.task.path).parts[-1])


@pytest.mark.parametrize("name", JOBS)
def test_each_ladder_job_expands_to_its_tiers_and_condition_on_every_rung_and_language(name):
    tiers, condition = JOBS[name]

    trials = expand_trials(load_job(name))

    assert sorted(ladder_key(t) for t in trials) == sorted(
        (tier, condition, language, rung)
        for tier in tiers for language in ("go", "typescript") for rung in RUNGS)


def test_the_four_ladder_jobs_hold_twelve_trials_on_each_rung():
    trials = [t for name in JOBS for t in expand_trials(load_job(name))]

    assert len(trials) == 12 * len(RUNGS)
    assert len({ladder_key(t) for t in trials}) == len(trials)


def test_every_ladder_agent_shares_the_phase0_claude_code_version_and_l9_settings():
    agents = [a for name in (*JOBS, "phase0-cross-tdd.yaml") for a in load_job(name).agents]

    assert len({a.kwargs.get("version") for a in agents}) == 1
    for agent in agents:
        assert agent.import_path == "instruments.agent:InstrumentedClaudeCode"
        assert agent.env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] == "1"
        assert agent.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


@pytest.mark.parametrize("name", JOBS)
def test_every_ladder_job_has_one_attempt(name):
    assert load_job(name).n_attempts == 1


@pytest.mark.parametrize("name", ["ladder-hosted-control.yaml", "ladder-local-control.yaml"])
def test_control_ladder_jobs_give_no_variant_parts(name):
    config = load_job(name)

    for agent in config.agents:
        assert not agent.skills
        assert "config" not in agent.kwargs
        assert not agent.mcp_servers
    assert not config.extra_instruction_paths
    assert not config.extra_instructions


@pytest.mark.parametrize("name", ["ladder-hosted-tdd.yaml", "ladder-local-tdd.yaml"])
def test_tdd_ladder_jobs_give_the_skill_and_its_extra_instruction(name):
    config = load_job(name)

    assert all(agent.skills for agent in config.agents)
    assert [Path(p).as_posix() for p in config.extra_instruction_paths] == [INSTRUMENT_INSTRUCTION]


@pytest.mark.parametrize("name", ["ladder-local-control.yaml", "ladder-local-tdd.yaml"])
def test_local_ladder_jobs_use_one_server_slot_and_timeout_multiplier_3(name):
    config = load_job(name)

    (agent,) = config.agents
    assert agent.concurrency_group is not None  # L3
    assert agent.n_concurrent == 1
    assert config.n_concurrent_trials == 1
    assert config.timeout_multiplier == 3.0  # L4
    assert agent.env["ANTHROPIC_BASE_URL"] == "${ASSAY_LOCAL_BASE_URL}"  # L10
