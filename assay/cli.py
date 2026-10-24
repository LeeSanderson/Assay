"""The `assay` command, the one supported way to start an Assay job (ADR 0002)
and the one way to run the analysis tools on its results.

    uv run assay run -c jobs/<file>.yaml -y [--overwrite] [harbor run options]
    uv run assay <subcommand> [args]   (each analysis tool's `main` in the `analyze` package)

Every subcommand first loads `.env` from the repository root: it sets each key
the shell has not set (a shell variable wins) and prints the names of the
keys it set, never the values.

`assay run` takes only `--overwrite`; every other argument goes to
`harbor run` unchanged and in the same order. It runs Harbor with its
telemetry off (HARBOR_TELEMETRY=0) unless the shell or `.env` sets
HARBOR_TELEMETRY. Before Harbor starts, it stops
when an InstrumentedClaudeCode agent's Claude Code version is not `stable`,
`latest` or X.Y.Z, for example the placeholder or no version (with --dry-run
too). It reads the version from the job file only, not from --ak. Then it
finds the job's results folder, <jobs_dir>/<job_name>/, and:

- with --overwrite, deletes the folder (with --dry-run, says it would);
- without, stops with a hint when the folder holds results that Harbor cannot
  resume because the config differs (with --dry-run, only warns). Results
  with the same config resume.
"""

from __future__ import annotations

import importlib
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

import yaml
from dotenv import dotenv_values
from harbor.models.job.config import JobConfig, migrate_legacy_job_config
from harbor.skills import resolve_skill_sources

from instruments.agent import IMPORT_PATH, VersionNotSetError, check_version_set

class Tool(NamedTuple):
    module: str  # in `analyze`; `assay` calls its main(argv)
    about: str


# Each analysis tool by its subcommand, in the order of the analysis process.
TOOLS = {
    "trace-check": Tool("analyze.trace_check", "check the trace of each trial of a job"),
    "replay": Tool("analyze.replay", "replay the trace snapshots of a job's trials"),
    "agent-runs": Tool("analyze.agent_runs", "cross-check the agent's test runs with the replay"),
    "trajectory": Tool("analyze.trajectory", "measure test-first and red-to-green order"),
    "compare-labels": Tool("analyze.compare_labels",
                           "compare the labeling sheet with trajectory's output"),
    "summary": Tool("analyze.summary", "write the Phase 0 summary"),
}
USAGE = "\n".join([
    "usage: assay run -c jobs/<file>.yaml [--overwrite] [harbor run options]",
    "       assay <subcommand> [args]   (assay <subcommand> --help shows its arguments)",
    "",
    "subcommands:",
    "  assay run             start a job with harbor run",
    *(f"  assay {name:<15} {tool.about}" for name, tool in TOOLS.items()),
])
OVERWRITE = "--overwrite"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"  # at the repository root
TELEMETRY = "HARBOR_TELEMETRY"  # harbor/telemetry.py; "0" turns it off
UTF8_MODE = "PYTHONUTF8"  # "1": Python's UTF-8 mode, the default encoding for files

HarborRunner = Callable[[Sequence[str]], int]


def run_harbor(args: Sequence[str]) -> int:
    """`harbor run <args>` as a subprocess; returns its exit code."""
    sys.stdout.flush()  # assay's own lines come before Harbor's
    # Harbor's telemetry sender flashes a console window on Windows and sends
    # the job's model names and cost off the machine. Harbor reads files such
    # as trajectory.json without an encoding, which on Windows is cp1252 and
    # fails on other characters; UTF-8 mode fixes that. A shell value wins.
    env = {TELEMETRY: "0", UTF8_MODE: "1", **os.environ}
    process = subprocess.Popen(["harbor", "run", *args], env=env)
    while True:
        try:
            return process.wait()
        except KeyboardInterrupt:
            # Ctrl-C reaches Harbor too, which stops its trials and cleans up;
            # wait for it rather than kill it.
            continue


def option_values(args: Sequence[str], *names: str) -> list[str]:
    """Every value given to the option `names`, in order, read as Click reads
    it: `--opt value`, `--opt=value`, `-o value` and `-ovalue`."""
    values = []
    for i, arg in enumerate(args):
        if arg in names and i + 1 < len(args):
            values.append(args[i + 1])
        elif arg.startswith("--") and arg.split("=", 1)[0] in names:
            values.append(arg.split("=", 1)[1])
        elif not arg.startswith("--") and arg[:2] in names and len(arg) > 2:
            values.append(arg[2:])
    return values


def job_config(job_file: Path, args: Sequence[str]) -> JobConfig:
    """The JobConfig `harbor run <args>` builds from the job file, with the
    command line's --job-name and --jobs-dir applied over it (harbor/cli/jobs.py,
    build_job_config) and its skills resolved (harbor/job.py, Job.create), so it
    equals the config Harbor compares with an earlier run's config.json."""
    config = migrate_legacy_job_config(yaml.safe_load(job_file.read_text()) or {})
    defaults: dict[str, object] = {"agents": [{}], "retry": {}, "environment": {}, "verifier": {}}
    for key, default in defaults.items():
        config.setdefault(key, default)
    if job_names := option_values(args, "--job-name"):
        config["job_name"] = job_names[-1]
    if jobs_dirs := option_values(args, "-o", "--jobs-dir"):
        config["jobs_dir"] = Path(jobs_dirs[-1])
    config = JobConfig.model_validate(config)
    for agent in config.agents:
        if sources := [s for s in agent.skills if isinstance(s, str)]:
            agent.skills = [str(s) for s in resolve_skill_sources(sources)]
    return config


def delete_folder(folder: Path) -> None:
    """Delete the folder and all in it, read-only files too: Git writes its
    objects read-only (the agent's trace.git), and Windows will not delete a
    read-only file."""
    def make_writable_and_retry(function, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        function(path)
    shutil.rmtree(folder, onexc=make_writable_and_retry)


def error(message: str) -> int:
    """Print the error; return the exit code that stops the run."""
    print(f"error: assay run: {message}", file=sys.stderr)
    return 2


def run(args: Sequence[str], run_harbor: HarborRunner = run_harbor) -> int:
    overwrite = OVERWRITE in args
    harbor_args = [arg for arg in args if arg != OVERWRITE]
    job_files = option_values(harbor_args, "-c", "--config")
    if not job_files:
        return error("a job file is required (-c jobs/<file>.yaml)")
    if len(job_files) > 1:
        return error("give one job file (-c), not several")
    try:
        config = job_config(Path(job_files[0]), harbor_args)
    except (OSError, ValueError, yaml.YAMLError) as e:
        return error(f"cannot read job file {job_files[0]}: {e}")
    # The same check InstrumentedClaudeCode.setup() makes, here before Harbor
    # builds the task image.
    try:
        for agent in config.agents:
            if agent.import_path == IMPORT_PATH:
                check_version_set(agent.kwargs.get("version"))
    except VersionNotSetError as e:
        return error(str(e))
    folder = config.jobs_dir / config.job_name

    # Harbor's dry run never creates or reads the job folder, so a dry run
    # deletes nothing and only warns.
    dry_run = "--dry-run" in harbor_args
    if overwrite:
        if dry_run:
            print(f"would delete {folder}" if folder.exists()
                  else f"nothing to delete: {folder} does not exist")
        elif folder.exists():
            delete_folder(folder)
            print(f"deleted {folder}")
    elif (folder / "config.json").exists():
        # Harbor resumes a job only when its saved config equals the new one
        # (harbor/job.py, _maybe_init_existing_job); say what to do when not.
        existing = JobConfig.model_validate_json((folder / "config.json").read_text())
        if existing != config:
            message = (f"{folder} holds results of this job with a different config, so "
                       f"Harbor cannot resume it. Re-run with --overwrite to delete "
                       f"{folder} and start fresh.")
            if not dry_run:
                return error(message)
            print(f"warning: assay run: {message}", file=sys.stderr)
    return run_harbor(harbor_args)


def load_env_file(env_file: Path) -> None:
    """Set each key of the file that the shell has not set (python-dotenv's
    override=False), and print the names of the keys set, never the values.
    Printed to stderr, so a tool's stdout stays its own."""
    loaded = {key: value for key, value in dotenv_values(env_file).items()
              if key not in os.environ and value is not None}
    os.environ.update(loaded)
    if loaded:
        print(f"assay: loaded {', '.join(loaded)} from {env_file}", file=sys.stderr)


def main(argv: Sequence[str] | None = None, run_harbor: HarborRunner = run_harbor,
         env_file: Path | None = None) -> int:
    load_env_file(env_file or ENV_FILE)
    command, *args = list(sys.argv[1:] if argv is None else argv) or [""]
    if command == "run":
        return run(args, run_harbor)
    if command in TOOLS:
        return importlib.import_module(TOOLS[command].module).main(args)
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
