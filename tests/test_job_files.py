"""The three Phase 0 job files, read through Harbor's own job model.

PRD section 5, "Model tiers, and the local tier" and "Version pins". The
smoke trial exercises the job files end to end; these tests only check that
Harbor accepts each file and expands it to the planned trials. The slow test
also launches a job file through `assay run` (issue #31, ADR 0002).
"""

import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml
from harbor.job_plan import JobPlan
from harbor.models.job.config import JobConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = REPO_ROOT / "jobs"


@pytest.fixture(autouse=True)
def run_from_repo_root(monkeypatch):
    # Harbor resolves task and skill paths against the current directory.
    monkeypatch.chdir(REPO_ROOT)


def load_job(name: str) -> JobConfig:
    data = yaml.safe_load((JOBS_DIR / name).read_text(encoding="utf-8"))
    return JobConfig.model_validate(data)


def expand_trials(config: JobConfig):
    tasks = asyncio.run(JobPlan.resolve_task_configs(config))
    return JobPlan.build_trial_configs(config, tasks, job_id=uuid.uuid4())


def trial_key(trial) -> tuple[str, str, str]:
    """(model, condition, language) for one trial config."""
    condition = "instrument-tdd" if trial.agent.skills else "control"
    language = Path(trial.task.path).parts[-2]
    return trial.agent.model_name, condition, language


def test_cross_job_expands_to_the_eight_planned_trials():
    trials = expand_trials(load_job("phase0-cross.yaml"))

    assert sorted(trial_key(t) for t in trials) == sorted(
        (model, condition, language)
        for model in ("anthropic/claude-haiku-5-5", "anthropic/claude-sonnet-5-5")
        for condition in ("control", "instrument-tdd")
        for language in ("go", "typescript")
    )


def test_extra_job_expands_to_haiku_instrument_tdd_in_each_language():
    trials = expand_trials(load_job("phase0-extra.yaml"))

    assert sorted(trial_key(t) for t in trials) == [
        ("anthropic/claude-haiku-5-5", "instrument-tdd", "go"),
        ("anthropic/claude-haiku-5-5", "instrument-tdd", "typescript"),
    ]


def test_local_job_is_one_instrument_tdd_trial_on_one_server_slot():
    config = load_job("phase0-local.yaml")
    trials = expand_trials(config)

    assert len(trials) == 1
    (agent,) = config.agents
    assert agent.skills  # instrument-tdd
    assert agent.concurrency_group is not None  # L3
    assert agent.n_concurrent == 1
    assert config.timeout_multiplier > 1.0  # L4
    # L10: the server address comes from this one host setting only.
    assert agent.env["ANTHROPIC_BASE_URL"] == "${ASSAY_LOCAL_BASE_URL}"


def test_smoke_job_is_one_haiku_instrument_tdd_trial():
    trials = expand_trials(load_job("phase0-smoke.yaml"))

    assert [trial_key(t) for t in trials] == [
        ("anthropic/claude-haiku-5-5", "instrument-tdd", "typescript"),
    ]


JOB_FILES = ("phase0-cross.yaml", "phase0-extra.yaml", "phase0-local.yaml", "phase0-smoke.yaml")


def all_agents():
    return [agent for name in JOB_FILES for agent in load_job(name).agents]


def test_every_agent_in_the_three_jobs_shares_one_claude_code_version():
    versions = {agent.kwargs.get("version") for agent in all_agents()}

    assert len(versions) == 1
    assert None not in versions


def test_every_agent_is_the_instrumented_class_with_the_l9_settings():
    for agent in all_agents():
        assert agent.import_path == "instruments.agent:InstrumentedClaudeCode"
        assert agent.env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] == "1"
        assert agent.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_control_trials_pass_no_variant_flags():
    config = load_job("phase0-cross.yaml")
    controls = [a for a in config.agents if not a.skills]

    assert len(controls) == 2
    for agent in controls:
        assert "config" not in agent.kwargs
        assert not agent.mcp_servers
    assert not config.extra_instruction_paths
    assert not config.extra_instructions


INSTRUMENT_INSTRUCTION = "variants/instrument-tdd/extra-instruction.md"


@pytest.mark.parametrize("name", ["phase0-extra.yaml", "phase0-local.yaml", "phase0-smoke.yaml"])
def test_instrument_only_jobs_name_the_skill_in_an_extra_instruction(name):
    # PRD "The phase 0 instrument": the smoke trial did not load the skill
    # from its description alone, so the prompt names it.
    config = load_job(name)

    assert all(agent.skills for agent in config.agents)
    assert [Path(p).as_posix() for p in config.extra_instruction_paths] == [INSTRUMENT_INSTRUCTION]


def test_server_address_appears_only_in_the_host_setting():
    # Job files may show an example address in a comment; no setting may hold one.
    for path in JOBS_DIR.iterdir():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".yaml":
            text = json.dumps(yaml.safe_load(text))
        assert "://" not in text, path.name


@pytest.mark.slow
def test_a_job_file_trial_through_assay_delivers_the_trace_and_resumes_on_a_re_run(tmp_path):
    # The extra job, cut to its TypeScript task, with the agent swapped for the
    # same class minus the install and the model run. Everything else (skills,
    # kwargs, env) comes from the committed job file.
    data = yaml.safe_load((JOBS_DIR / "phase0-extra.yaml").read_text(encoding="utf-8"))
    data["jobs_dir"] = str(tmp_path)
    data["job_name"] = "trace-delivery"
    data["tasks"] = [{"path": "tasks/typescript/split-second-stopwatch"}]
    (agent,) = data["agents"]
    agent["import_path"] = "tests.no_model_agent:NoModelInstrumentedClaudeCode"
    job_file = tmp_path / "job.yaml"
    job_file.write_text(yaml.safe_dump(data), encoding="utf-8")

    # UTF-8 output: Harbor's progress spinner cannot be written to a cp1252 pipe.
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONIOENCODING": "utf-8"}

    def assay_run():
        return subprocess.run(
            ["uv", "run", "assay", "run", "-c", str(job_file), "-y"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1200,
        )

    result = assay_run()
    assert result.returncode == 0, result.stdout + result.stderr

    (trial_dir,) = [p for p in (tmp_path / "trace-delivery").iterdir() if p.is_dir()]
    trace = trial_dir / "artifacts" / "logs" / "artifacts" / "trace"
    assert (trace / "trace.git").is_dir()
    record = json.loads((trace / "instruments.json").read_text(encoding="utf-8"))
    assert record["harbor_version"] == "0.24.0"

    # A re-run of the same job file resumes: assay's config equals the
    # config.json Harbor saved, so the run reaches Harbor, which has nothing
    # left to run.
    result = assay_run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert (trial_dir / "artifacts").is_dir()

    # A changed job file stops before Harbor, with the hint.
    data["n_attempts"] = 2
    job_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = assay_run()
    assert result.returncode != 0
    assert "--overwrite" in result.stderr
