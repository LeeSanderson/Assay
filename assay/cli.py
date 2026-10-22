"""The `assay` command, the one supported way to start an Assay job (ADR 0002).

    uv run assay run -c jobs/<file>.yaml -y [--overwrite] [harbor run options]

`assay run` takes only `--overwrite`; every other argument goes to
`harbor run` unchanged and in the same order. Before Harbor starts, it finds
the job's results folder, <jobs_dir>/<job_name>/, and:

- with --overwrite, deletes the folder (with --dry-run, says it would);
- without, stops with a hint when the folder holds results that Harbor cannot
  resume because the config differs (with --dry-run, only warns). Results
  with the same config resume.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml
from harbor.models.job.config import JobConfig, migrate_legacy_job_config
from harbor.skills import resolve_skill_sources

USAGE = "usage: assay run -c jobs/<file>.yaml [--overwrite] [harbor run options]"
OVERWRITE = "--overwrite"

HarborRunner = Callable[[Sequence[str]], int]


def run_harbor(args: Sequence[str]) -> int:
    """`harbor run <args>` as a subprocess; returns its exit code."""
    sys.stdout.flush()  # assay's own lines come before Harbor's
    process = subprocess.Popen(["harbor", "run", *args])
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
    folder = config.jobs_dir / config.job_name

    # Harbor's dry run never creates or reads the job folder, so a dry run
    # deletes nothing and only warns.
    dry_run = "--dry-run" in harbor_args
    if overwrite:
        if dry_run:
            print(f"would delete {folder}" if folder.exists()
                  else f"nothing to delete: {folder} does not exist")
        elif folder.exists():
            shutil.rmtree(folder)
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


def main(argv: Sequence[str] | None = None, run_harbor: HarborRunner = run_harbor) -> int:
    command, *args = list(sys.argv[1:] if argv is None else argv) or [""]
    if command != "run":
        print(USAGE, file=sys.stderr)
        return 2
    return run(args, run_harbor)


if __name__ == "__main__":
    raise SystemExit(main())
