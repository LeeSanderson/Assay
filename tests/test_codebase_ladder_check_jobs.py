"""The two job files that check the purpose-written packs of the codebase
ladder before it runs (PRD section 20, "The checks of a purpose-written
pack"; issue #81): the blind solve (Opus in control) and the smoke job (Haiku
with instrument-tdd), each one trial on every purpose-written pack. Read
through Harbor's own job model."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.job_files import INSTRUMENT_INSTRUCTION, expand_trials, load_job, trial_key
from tests.task_packs import CODEBASE_PACKS, REPO_ROOT

pytestmark = pytest.mark.usefixtures("run_from_repo_root")

PACK_PATHS = sorted(p.path.relative_to(REPO_ROOT).as_posix() for p in CODEBASE_PACKS)


def _task_paths(trials) -> list[str]:
    return sorted(Path(t.task.path).as_posix() for t in trials)


def test_blind_solve_is_one_opus_control_trial_on_each_purpose_written_pack():
    config = load_job("codebase-ladder-blind-solve.yaml")
    trials = expand_trials(config)

    assert {trial_key(t)[:2] for t in trials} == {("anthropic/claude-opus-5-5", "control")}
    assert _task_paths(trials) == PACK_PATHS
    assert not config.extra_instruction_paths


def test_smoke_job_is_one_haiku_instrument_tdd_trial_on_each_purpose_written_pack():
    config = load_job("codebase-ladder-smoke.yaml")
    trials = expand_trials(config)

    assert {trial_key(t)[:2] for t in trials} == {("anthropic/claude-haiku-5-5",
                                                   "instrument-tdd")}
    assert _task_paths(trials) == PACK_PATHS
    assert [str(p).replace("\\", "/") for p in config.extra_instruction_paths] == [
        INSTRUMENT_INSTRUCTION]
