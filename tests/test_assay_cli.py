"""`assay run` (issue #31): the launcher's checks around `harbor run`, with
Harbor replaced by a recorder, so no Docker and no Harbor process. And the
load of host settings from `.env` (issue #35), from a `.env` in a temporary
folder in place of the repository's."""

import os
from pathlib import Path

import pytest
import yaml
from dotenv import dotenv_values
from harbor.models.job.config import JobConfig

from assay.cli import main, run_harbor
from instruments.agent import IMPORT_PATH as INSTRUMENTED

REPO_ROOT = Path(__file__).resolve().parent.parent


class Harbor:
    """Records each `harbor run` call instead of running Harbor."""

    def __init__(self, exit_code=0):
        self.calls = []
        self.exit_code = exit_code

    def __call__(self, args):
        self.calls.append(list(args))
        return self.exit_code


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    # Harbor resolves jobs_dir against the current directory, and so does assay.
    monkeypatch.chdir(tmp_path)
    # The repository's own .env stays out of every test.
    monkeypatch.setattr("assay.cli.ENV_FILE", tmp_path / ".env")


def job_file(tmp_path, name="job.yaml", **fields):
    data = {"job_name": "phase0-test", "jobs_dir": "results", **fields}
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_arguments_reach_harbor_unchanged_and_in_order(tmp_path):
    job = job_file(tmp_path)
    harbor = Harbor()

    main(["run", "-y", "-c", str(job), "--n-concurrent", "2", "--overwrite", "--debug"],
         run_harbor=harbor)

    assert harbor.calls == [["-y", "-c", str(job), "--n-concurrent", "2", "--debug"]]


def test_assay_exits_with_harbors_exit_code(tmp_path):
    job = job_file(tmp_path)

    assert main(["run", "-c", str(job)], run_harbor=Harbor(exit_code=3)) == 3


def test_without_a_job_file_the_run_stops_before_harbor(capsys):
    harbor = Harbor()

    assert main(["run", "-y", "--job-name", "adhoc"], run_harbor=harbor) != 0

    assert harbor.calls == []
    assert "job file is required" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["analyze"]])
def test_without_a_known_subcommand_assay_prints_usage(argv, capsys):
    harbor = Harbor()

    assert main(argv, run_harbor=harbor) == 2

    assert harbor.calls == []
    assert "usage: assay run" in capsys.readouterr().err


def test_a_missing_job_file_stops_the_run_before_harbor(capsys):
    harbor = Harbor()

    assert main(["run", "-c", "jobs/missing.yaml"], run_harbor=harbor) != 0

    assert harbor.calls == []
    assert "missing.yaml" in capsys.readouterr().err


def earlier_job(folder, config=None):
    """The results folder of an earlier `harbor run` of the job, with one trial."""
    (folder / "trial__1").mkdir(parents=True)
    if config is not None:
        (folder / "config.json").write_text(config.model_dump_json(), encoding="utf-8")
    return folder


def test_overwrite_deletes_the_results_folder_then_runs_harbor(tmp_path, capsys):
    job = job_file(tmp_path)
    folder = earlier_job(tmp_path / "results" / "phase0-test")
    harbor = Harbor()

    assert main(["run", "-c", str(job), "-y", "--overwrite"], run_harbor=harbor) == 0

    assert not folder.exists()
    assert harbor.calls == [["-c", str(job), "-y"]]
    assert f"deleted {Path('results/phase0-test')}" in capsys.readouterr().out


def test_overwrite_deletes_read_only_files_in_the_results_folder(tmp_path):
    # Git writes its objects read-only, as in the agent's trace.git, and
    # Windows refuses to delete a read-only file.
    job = job_file(tmp_path)
    folder = earlier_job(tmp_path / "results" / "phase0-test")
    git_object = folder / "trial__1" / "trace.git" / "objects" / "0a" / "ba1a59"
    git_object.parent.mkdir(parents=True)
    git_object.write_bytes(b"object")
    git_object.chmod(0o444)

    assert main(["run", "-c", str(job), "--overwrite"], run_harbor=Harbor()) == 0

    assert not folder.exists()


def test_overwrite_with_no_results_folder_deletes_nothing_and_runs(tmp_path):
    job = job_file(tmp_path)
    other = earlier_job(tmp_path / "results" / "another-job")
    harbor = Harbor()

    assert main(["run", "-c", str(job), "--overwrite"], run_harbor=harbor) == 0

    assert other.exists()
    assert harbor.calls == [["-c", str(job)]]


def test_overwrite_with_dry_run_reports_the_folder_and_deletes_nothing(tmp_path, capsys):
    job = job_file(tmp_path)
    folder = earlier_job(tmp_path / "results" / "phase0-test")
    harbor = Harbor()

    main(["run", "-c", str(job), "--overwrite", "--dry-run"], run_harbor=harbor)

    assert folder.exists()
    assert harbor.calls == [["-c", str(job), "--dry-run"]]
    assert f"would delete {Path('results/phase0-test')}" in capsys.readouterr().out


@pytest.mark.parametrize("options, folder", [
    (["--job-name", "renamed"], "results/renamed"),
    (["--job-name=renamed"], "results/renamed"),
    (["--jobs-dir", "elsewhere"], "elsewhere/phase0-test"),
    (["--jobs-dir=elsewhere"], "elsewhere/phase0-test"),
    (["-o", "elsewhere"], "elsewhere/phase0-test"),
    (["-oelsewhere"], "elsewhere/phase0-test"),  # Click's attached short form
    (["-o", "elsewhere", "--job-name", "renamed"], "elsewhere/renamed"),
])
def test_command_line_job_name_and_jobs_dir_win_over_the_job_file(tmp_path, options, folder):
    job = job_file(tmp_path)
    from_file = earlier_job(tmp_path / "results" / "phase0-test")
    from_command_line = earlier_job(tmp_path / folder)

    main(["run", "-c", str(job), "--overwrite", *options], run_harbor=Harbor())

    assert not from_command_line.exists()
    assert from_file.exists()


def config_of(job, **overrides):
    """The JobConfig Harbor saves for `harbor run -c <job>`, as an independent
    source of truth: the job file, validated by Harbor's model."""
    data = {**yaml.safe_load(job.read_text(encoding="utf-8")), **overrides}
    return JobConfig.model_validate(data)


def test_an_earlier_job_with_a_different_config_stops_with_the_overwrite_hint(tmp_path, capsys):
    job = job_file(tmp_path, n_attempts=1)
    folder = earlier_job(tmp_path / "results" / "phase0-test", config_of(job, n_attempts=3))
    harbor = Harbor()

    assert main(["run", "-c", str(job), "-y"], run_harbor=harbor) != 0

    assert harbor.calls == []
    assert folder.exists()
    err = capsys.readouterr().err
    assert str(Path("results/phase0-test")) in err
    assert "--overwrite" in err


def test_an_earlier_job_with_the_same_config_resumes(tmp_path):
    job = job_file(tmp_path)
    folder = earlier_job(tmp_path / "results" / "phase0-test", config_of(job))
    harbor = Harbor()

    assert main(["run", "-c", str(job), "-y"], run_harbor=harbor) == 0

    assert harbor.calls == [["-c", str(job), "-y"]]
    assert (folder / "trial__1").exists()


def test_a_dry_run_after_a_job_file_change_warns_and_still_runs(tmp_path, capsys):
    # Harbor's dry run never reads the job folder, so the check only warns.
    job = job_file(tmp_path, n_attempts=1)
    earlier_job(tmp_path / "results" / "phase0-test", config_of(job, n_attempts=3))
    harbor = Harbor()

    assert main(["run", "-c", str(job), "--dry-run"], run_harbor=harbor) == 0

    assert harbor.calls == [["-c", str(job), "--dry-run"]]
    assert "--overwrite" in capsys.readouterr().err


def test_an_earlier_job_with_skills_resumes(tmp_path):
    # Harbor saves each local skill path as str(Path(value)) (harbor/skills.py),
    # so on Windows the saved config holds back slashes.
    (tmp_path / "variants" / "tdd").mkdir(parents=True)
    job = job_file(tmp_path, agents=[{"name": "oracle", "skills": ["variants/tdd"]}])
    saved = config_of(job)
    saved.agents[0].skills = [str(Path("variants/tdd"))]
    earlier_job(tmp_path / "results" / "phase0-test", saved)
    harbor = Harbor()

    assert main(["run", "-c", str(job)], run_harbor=harbor) == 0

    assert len(harbor.calls) == 1


def test_the_comparison_uses_the_command_line_job_name_and_jobs_dir(tmp_path):
    job = job_file(tmp_path)
    folder = earlier_job(tmp_path / "elsewhere" / "renamed",
                         config_of(job, job_name="renamed", jobs_dir="elsewhere"))
    harbor = Harbor()

    main(["run", "-c", str(job), "-o", "elsewhere", "--job-name=renamed"], run_harbor=harbor)

    assert len(harbor.calls) == 1
    assert (folder / "trial__1").exists()


def test_overwrite_deletes_even_when_the_configs_match(tmp_path):
    job = job_file(tmp_path)
    folder = earlier_job(tmp_path / "results" / "phase0-test", config_of(job))

    main(["run", "-c", str(job), "--overwrite"], run_harbor=Harbor())

    assert not folder.exists()



@pytest.mark.parametrize("options", [["-y"], ["--dry-run"]])
@pytest.mark.parametrize("kwargs", [{"version": "SET-ON-SMOKE-TRIAL-DAY"}, {}])
def test_a_job_without_a_claude_code_version_stops_before_harbor(tmp_path, capsys,
                                                                 kwargs, options):
    job = job_file(tmp_path, agents=[
        {"import_path": INSTRUMENTED, "kwargs": {"version": "2.1.308"}},
        {"import_path": INSTRUMENTED, "kwargs": kwargs},
    ])
    harbor = Harbor()

    assert main(["run", "-c", str(job), *options], run_harbor=harbor) != 0

    assert harbor.calls == []
    err = capsys.readouterr().err
    assert "SET-ON-SMOKE-TRIAL-DAY" in err
    assert "Set the Claude Code version first" in err


def test_a_job_with_a_claude_code_version_runs(tmp_path):
    job = job_file(tmp_path, agents=[
        {"import_path": INSTRUMENTED, "kwargs": {"version": "2.1.308"}},
    ])
    harbor = Harbor()

    assert main(["run", "-c", str(job), "-y"], run_harbor=harbor) == 0

    assert harbor.calls == [["-c", str(job), "-y"]]


# The analysis tools as assay subcommands (issue #32).

TOOLS = {
    "trace-check": "analyze.trace_check",
    "replay": "analyze.replay",
    "agent-runs": "analyze.agent_runs",
    "trajectory": "analyze.trajectory",
    "compare-labels": "analyze.compare_labels",
    "summary": "analyze.summary",
}


@pytest.mark.parametrize("subcommand,module", TOOLS.items())
def test_each_tool_gets_the_remaining_arguments_and_gives_its_exit_code(
        subcommand, module, monkeypatch):
    calls = []

    def tool_main(argv):
        calls.append(list(argv))
        return 7

    monkeypatch.setattr(f"{module}.main", tool_main)

    assert main([subcommand, "results/phase0-cross", "--analysis", "out"]) == 7
    assert calls == [["results/phase0-cross", "--analysis", "out"]]


@pytest.mark.parametrize("subcommand", TOOLS)
def test_each_tools_help_names_the_assay_subcommand(subcommand, capsys):
    with pytest.raises(SystemExit) as exited:
        main([subcommand, "--help"])

    assert exited.value.code == 0
    assert capsys.readouterr().out.startswith(f"usage: assay {subcommand}")


@pytest.mark.parametrize("argv", [[], ["bogus"], ["--help"]])
def test_the_usage_lists_every_subcommand(argv, capsys):
    assert main(argv) == 2

    usage = capsys.readouterr().err
    for subcommand in ["run", *TOOLS]:
        assert f"assay {subcommand}" in usage


def test_compare_labels_runs_end_to_end_through_assay(tmp_path, capsys):
    from tests.test_compare_labels import AGREEING_ROW, SCRIPT_LINE, write_output, write_sheet

    row = {**AGREEING_ROW, "test_first_verdict": "same-turn"}

    code = main(["compare-labels", str(write_sheet(tmp_path, [row])),
                 str(write_output(tmp_path, [SCRIPT_LINE]))])

    assert code == 1
    assert "test_first_verdict" in capsys.readouterr().out


# Host settings from .env (issue #35).

class EnvSeenByHarbor(Harbor):
    """Records the value of `key` that the Harbor process would inherit."""

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.value = None

    def __call__(self, args):
        self.value = os.environ.get(self.key)
        return super().__call__(args)


@pytest.fixture
def unset_key(monkeypatch):
    """A key the shell does not set. Set then deleted, so that monkeypatch
    removes it after the test, whatever assay loads into os.environ."""
    monkeypatch.setenv("ASSAY_TEST_KEY", "")
    monkeypatch.delenv("ASSAY_TEST_KEY")
    return "ASSAY_TEST_KEY"


def env_file(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_key_in_env_file_reaches_harbor(tmp_path, unset_key):
    harbor = EnvSeenByHarbor(unset_key)

    main(["run", "-c", str(job_file(tmp_path))], run_harbor=harbor,
         env_file=env_file(tmp_path, f"{unset_key}=from-file\n"))

    assert harbor.value == "from-file"


def test_a_key_set_in_the_shell_wins_over_env_file(tmp_path, monkeypatch, unset_key):
    monkeypatch.setenv(unset_key, "from-shell")
    harbor = EnvSeenByHarbor(unset_key)

    main(["run", "-c", str(job_file(tmp_path))], run_harbor=harbor,
         env_file=env_file(tmp_path, f"{unset_key}=from-file\n"))

    assert harbor.value == "from-shell"


def test_assay_prints_the_names_of_the_keys_it_loaded_and_not_the_values(
        tmp_path, monkeypatch, capsys, unset_key):
    monkeypatch.setenv("ASSAY_SHELL_KEY", "shell-secret")

    main(["run", "-c", str(job_file(tmp_path))], run_harbor=Harbor(),
         env_file=env_file(tmp_path, f"{unset_key}=file-secret\nASSAY_SHELL_KEY=other-secret\n"))

    output = capsys.readouterr()
    printed = output.out + output.err
    assert unset_key in printed
    assert "ASSAY_SHELL_KEY" not in printed  # set in the shell, so not loaded
    assert "secret" not in printed


def test_without_an_env_file_assay_runs_and_prints_nothing_extra(tmp_path, capsys):
    harbor = Harbor()

    assert main(["run", "-c", str(job_file(tmp_path))], run_harbor=harbor,
                env_file=tmp_path / ".env") == 0

    assert harbor.calls != []
    output = capsys.readouterr()
    assert output.out + output.err == ""


def test_every_subcommand_loads_env_file(tmp_path, capsys, unset_key):
    main(["no-such-subcommand"], env_file=env_file(tmp_path, f"{unset_key}=from-file\n"))

    assert os.environ.get(unset_key) == "from-file"


def test_env_example_holds_no_value_for_any_key():
    keys = dotenv_values(REPO_ROOT / ".env.example")

    assert {"ANTHROPIC_API_KEY", "ASSAY_LOCAL_BASE_URL"} <= keys.keys()
    assert {key: value for key, value in keys.items() if value} == {}


class FakePopen:
    """Stands in for the Harbor process: records its command and environment."""

    started = []

    def __init__(self, command, env):
        FakePopen.started.append((command, env))

    def wait(self):
        return 0


def harbor_env(monkeypatch):
    FakePopen.started = []
    monkeypatch.setattr("assay.cli.subprocess.Popen", FakePopen)
    run_harbor(["-c", "jobs/x.yaml"])
    ((command, env),) = FakePopen.started
    assert command == ["harbor", "run", "-c", "jobs/x.yaml"]
    return env


def test_harbor_runs_with_utf8_file_reads_and_telemetry_off(monkeypatch):
    # Harbor reads trajectory.json without an encoding; on Windows that is
    # cp1252, which fails on a trajectory with other characters.
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("HARBOR_TELEMETRY", raising=False)

    env = harbor_env(monkeypatch)

    assert env["PYTHONUTF8"] == "1"
    assert env["HARBOR_TELEMETRY"] == "0"


def test_a_shell_value_wins_over_the_launcher_defaults(monkeypatch):
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("HARBOR_TELEMETRY", "1")

    env = harbor_env(monkeypatch)

    assert env["PYTHONUTF8"] == "0"
    assert env["HARBOR_TELEMETRY"] == "1"
