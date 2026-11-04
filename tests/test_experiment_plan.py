"""`assay experiment <name> --dry-run` (issue #60): the plan of an experiment,
through the CLI's `main`, with a Harbor runner that must never be called."""

from pathlib import Path

import pytest
import yaml

from assay.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


def never_harbor(args):
    raise AssertionError(f"a dry run called Harbor: {args}")


@pytest.fixture(autouse=True)
def no_env_file(tmp_path, monkeypatch):
    # The repository's own .env stays out of every test.
    monkeypatch.setattr("assay.cli.ENV_FILE", tmp_path / "no.env")


def test_the_phase0_dry_run_prints_the_jobs_conditions_and_expected_trials_by_cell(
        monkeypatch, capsys):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", "http://192.0.2.1:8080")
    before = {p for p in (REPO_ROOT / "results").rglob("*")} \
        if (REPO_ROOT / "results").exists() else set()

    assert main(["experiment", "phase0-tdd", "--dry-run"], run_harbor=never_harbor) == 0

    out = capsys.readouterr().out
    for job in ["phase0-cross-control", "phase0-cross-tdd", "phase0-extra", "phase0-local"]:
        assert job in out
    assert out.index("phase0-cross-control") < out.index("phase0-cross-tdd") \
        < out.index("phase0-extra") < out.index("phase0-local")
    cells = [line.split() for line in out.splitlines() if line.startswith("  cell ")]
    # cell <n> <harness> <model tier> <condition> <language>
    assert sorted((c[3], c[4], c[5], int(c[1])) for c in cells) == sorted([
        ("anthropic/claude-haiku-5-5", "control", "typescript", 1),
        ("anthropic/claude-haiku-5-5", "control", "go", 1),
        ("anthropic/claude-sonnet-5-5", "control", "typescript", 1),
        ("anthropic/claude-sonnet-5-5", "control", "go", 1),
        ("anthropic/claude-haiku-5-5", "instrument-tdd", "typescript", 2),
        ("anthropic/claude-haiku-5-5", "instrument-tdd", "go", 2),
        ("anthropic/claude-sonnet-5-5", "instrument-tdd", "typescript", 1),
        ("anthropic/claude-sonnet-5-5", "instrument-tdd", "go", 1),
        ("laguna-s-2.1", "instrument-tdd", "typescript", 1),
    ])
    assert {c[2] for c in cells} == {"claude-code"}
    assert "11 expected trials" in out
    after = {p for p in (REPO_ROOT / "results").rglob("*")} \
        if (REPO_ROOT / "results").exists() else set()
    assert after == before
    assert not (REPO_ROOT / "results" / "phase0-tdd").exists()
    assert not (REPO_ROOT / "analysis" / "phase0-tdd").exists()


# A small repository in a temporary folder: two variant folders, a job file
# per test, and experiments/exp/experiment.toml.

AGENT = {"import_path": "instruments.agent:InstrumentedClaudeCode",
         "model_name": "anthropic/claude-haiku-5-5", "kwargs": {"version": "2.1.308"}}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for variant in ["tdd", "other"]:
        skill = tmp_path / "variants" / variant / "skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {variant}\n---\n", encoding="utf-8")
        (tmp_path / "variants" / variant / "extra.md").write_text("Use it.", encoding="utf-8")
    (tmp_path / "loose" / "skill").mkdir(parents=True)
    (tmp_path / "loose" / "skill" / "SKILL.md").write_text("---\nname: loose\n---\n")
    (tmp_path / "tasks" / "go" / "slug").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write_job(repo, name, agents=None, **fields):
    data = {"job_name": name, "n_attempts": 1, "tasks": [{"path": "tasks/go/slug"}],
            "agents": agents if agents is not None else [AGENT], **fields}
    (repo / "jobs").mkdir(exist_ok=True)
    (repo / "jobs" / f"{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return f"jobs/{name}.yaml"


def write_experiment(repo, *job_files, extra=""):
    folder = repo / "experiments" / "exp"
    folder.mkdir(parents=True, exist_ok=True)
    jobs = ", ".join(f'"{file}"' for file in job_files)
    (folder / "experiment.toml").write_text(f"jobs = [{jobs}]\n{extra}", encoding="utf-8")


def plan(*args):
    return main(["experiment", "exp", "--dry-run", *args], run_harbor=never_harbor)


def test_an_agent_with_no_parts_is_the_control(repo, capsys):
    write_experiment(repo, write_job(repo, "a"))

    assert plan() == 0

    assert "cell 1 claude-code anthropic/claude-haiku-5-5 control go" in capsys.readouterr().out


def test_an_unknown_key_refuses_the_plan(repo, capsys):
    write_experiment(repo, write_job(repo, "a"), extra='name = "exp"\n')

    assert plan() == 2

    assert "unknown key name" in capsys.readouterr().err


def test_jobs_placed_under_summary_refuse_the_plan(repo, capsys):
    write_job(repo, "a")
    (repo / "experiments" / "exp").mkdir(parents=True)
    (repo / "experiments" / "exp" / "experiment.toml").write_text(
        '[summary]\nuse = "./summary.py"\njobs = ["jobs/a.yaml"]\n', encoding="utf-8")

    assert plan() == 2

    assert "unknown key summary.jobs" in capsys.readouterr().err


def test_an_options_table_for_an_unlisted_evaluation_refuses_the_plan(repo, capsys):
    write_experiment(repo, write_job(repo, "a"), extra=(
        'evaluations = ["replay"]\n[evaluation-options."./checks.py"]\nstrict = true\n'))

    assert plan() == 2

    assert "./checks.py" in capsys.readouterr().err


def test_an_unset_variable_in_a_selected_job_refuses_the_plan(repo, capsys, monkeypatch):
    monkeypatch.delenv("ASSAY_TEST_UNSET", raising=False)
    local = {**AGENT, "env": {"ANTHROPIC_BASE_URL": "${ASSAY_TEST_UNSET}"}}
    write_experiment(repo, write_job(repo, "a"), write_job(repo, "local", [local]))

    assert plan() == 2
    assert "${ASSAY_TEST_UNSET}" in capsys.readouterr().err

    # A job that is not selected needs no variable set.
    assert plan("--job", "a") == 0
    monkeypatch.setenv("ASSAY_TEST_UNSET", "http://192.0.2.1:8080")
    assert plan("--job", "local") == 0


def test_an_unknown_job_name_refuses_the_plan(repo, capsys):
    write_experiment(repo, write_job(repo, "a"))

    assert plan("--job", "nope") == 2

    assert "nope" in capsys.readouterr().err


@pytest.mark.parametrize("version", [None, "stable", "SET-ON-SMOKE-TRIAL-DAY"])
def test_an_unpinned_harness_version_refuses_the_plan(repo, capsys, version):
    agent = {**AGENT, "kwargs": {} if version is None else {"version": version}}
    write_experiment(repo, write_job(repo, "a", [agent]))

    assert plan() == 2

    assert "not a pinned" in capsys.readouterr().err


def test_parts_from_one_variant_folder_name_the_condition(repo, capsys):
    tdd = {**AGENT, "skills": ["variants/tdd/skill"]}
    write_experiment(repo, write_job(repo, "a", [tdd],
                                     extra_instruction_paths=["variants/tdd/extra.md"]))

    assert plan() == 0

    assert "cell 1 claude-code anthropic/claude-haiku-5-5 tdd go" in capsys.readouterr().out


@pytest.mark.parametrize("skills, extra, refusal", [
    (["variants/tdd/skill"], ["variants/other/extra.md"], "more than one variant folder"),
    (["variants/tdd/skill", "variants/other/skill"], [], "more than one variant folder"),
    (["loose/skill"], [], "outside variants/"),
])
def test_parts_from_two_variant_folders_or_outside_variants_refuse_the_plan(
        repo, capsys, skills, extra, refusal):
    agent = {**AGENT, "skills": skills}
    write_experiment(repo, write_job(repo, "a", [agent], extra_instruction_paths=extra))

    assert plan() == 2

    assert refusal in capsys.readouterr().err


def test_the_condition_digest_follows_the_content_of_the_parts(repo, capsys):
    write_experiment(repo, write_job(repo, "a", [{**AGENT, "skills": ["variants/tdd/skill"]}]))
    plan()
    digests = [word for word in capsys.readouterr().out.split() if word.startswith("sha256:")]

    (repo / "variants" / "tdd" / "skill" / "SKILL.md").write_text("---\nname: tdd\n---\nmore")
    plan()

    assert len(digests) == 1
    assert digests[0] not in capsys.readouterr().out
