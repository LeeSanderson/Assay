"""PROTOTYPE (wayfinder #49): throwaway. Reads experiment.toml the way
`assay experiment` would, and prints the plan, the expected cells, the code
digests, a resume walk-through and sample experiment-log lines. Runs nothing.

    uv run python experiments/phase0-tdd/plan_PROTOTYPE.py
"""

import ast
import hashlib
import json
import tomllib
from collections import Counter
from pathlib import Path

import yaml

from analyze.experiment_contract_PROTOTYPE import BUILT_INS

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOCAL_BASE_URL = "ASSAY_LOCAL_BASE_URL"
# Built-in name -> the real module, so the code digest is computed on real code.
REAL_MODULES = {"replay": "analyze.replay", "agent-runs": "analyze.agent_runs",
                "trajectory": "analyze.trajectory"}


def module_file(name: str) -> Path | None:
    path = ROOT.joinpath(*name.split(".")).with_suffix(".py")
    return path if path.is_file() else None


def import_closure(module: str) -> list[Path]:
    """The module and every repository module it imports, transitively."""
    seen, todo = {}, [module]
    while todo:
        name = todo.pop()
        path = module_file(name)
        if name in seen or path is None:
            continue
        seen[name] = path
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                todo.append(node.module)
            elif isinstance(node, ast.Import):
                todo += [a.name for a in node.names]
    return sorted(seen.values())


def code_digest(module: str) -> tuple[str, list[str]]:
    h = hashlib.sha256()
    files = import_closure(module)
    for f in files:
        h.update(f.relative_to(ROOT).as_posix().encode() + b"\0" + f.read_bytes())
    return h.hexdigest()[:12], [f.relative_to(ROOT).as_posix() for f in files]


def main() -> None:
    exp = tomllib.loads((HERE / "experiment.toml").read_text(encoding="utf-8"))
    name = exp["name"]

    print(f"== {name}: jobs, in order (results/{name}/<job_name>/)")
    expected = Counter()
    for job in exp["jobs"]:
        config = yaml.safe_load((ROOT / job["file"]).read_text(encoding="utf-8"))
        k = config.get("n_attempts", 1)
        for agent in config["agents"]:
            local = LOCAL_BASE_URL in json.dumps(agent.get("env") or {})
            tier = "local/reference" if local else agent["model_name"]
            for task in config["tasks"]:
                language = Path(task["path"]).parts[-2]
                expected[("claude-code", tier, job["condition"], language)] += k
        print(f"  {config['job_name']:<22} condition={job['condition']:<15} {job['file']}")

    print("\n== expected trials per cell (harness, model tier, condition, language)")
    for cell, n in sorted(expected.items()):
        print(f"  {n}  {cell}")
    declared = exp["factors"]["model_tier"]["levels"]
    if stray := {c[1] for c in expected} - set(declared):
        print(f"  !! model tiers not declared as levels: {stray}")

    print("\n== evaluations: run order, dependency check, code digest")
    listed = []
    for entry in exp["evaluations"]:
        e = BUILT_INS[entry["use"]]
        missing = [d for d in e.depends_on if d not in listed]
        status = "ok" if not missing else f"ERROR: needs {missing} listed before it"
        digest, files = code_digest(REAL_MODULES[e.name])
        print(f"  {e.name:<11} depends_on={list(e.depends_on)!s:<26} {status}")
        print(f"  {'':<11} code={digest} over {', '.join(files)}")
        listed.append(e.name)
    print(f"  summary     {exp['summary']['use']} options={exp['summary']['options']}")

    print("\n== resume walk-through for one trial (inputs: record, task_pack, options, deps, pins)")
    for change, effect in [
        ("nothing", "replay reused, agent-runs reused, trajectory reused; summary reruns"),
        ("analyze/agent_runs.py edited",
         "replay reused; agent-runs reruns (code); trajectory reruns only if agent-runs' "
         "value changed -- but trajectory imports agent_runs, so its code digest moved too: reruns"),
        ("analyze/shell.py edited",
         "every evaluation that imports shell (agent-runs, trajectory) reruns; replay reused"),
        ("tasks/go/... pack edited", "every evaluation reruns for Go trials (task_pack part)"),
        ("an infrastructure failure is rerun",
         "the new trial has no results: every evaluation runs for it; an *online* one "
         "would rerun for every trial"),
    ]:
        print(f"  {change:<36} -> {effect}")

    print(f"\n== sample analysis/{name}/experiment-log.jsonl")
    cell = {"harness": "claude-code", "model_tier": "anthropic/claude-haiku-5-5",
            "condition": "control", "language": "go"}
    for line in [
        {"event": "invocation-started", "argv": ["phase0-tdd"], "assay_commit": "64e87be",
         "harbor_version": "0.24.0"},
        {"event": "job-started", "job": "phase0-cross-control",
         "file": "jobs/phase0-cross-control.yaml", "condition": "control"},
        {"event": "job-finished", "job": "phase0-cross-control", "exit_code": 0, "trials": 4,
         "duration_sec": 1510.2},
        {"event": "trial-discarded", "job": "phase0-cross-control",
         "trial": "split-second-stopwatch__Xy12", "cell": cell,
         "task_pack": "tasks/go/split-second-stopwatch",
         "cause": {"exception": "OverloadedError"}, "input_tokens": 41200,
         "cache_tokens": 180000, "output_tokens": 3900, "cost_usd": 0.21,
         "duration_sec": 312.0},
        {"event": "halt", "job": "phase0-cross-tdd", "trial": "split-second-stopwatch__Ab34",
         "cause": {"failed_checks": ["claude_code_version"]},
         "message": "Claude Code 2.1.309 ran; the job pins 2.1.308"},
        {"event": "invocation-finished", "outcome": "halted"},
    ]:
        print("  " + json.dumps({"at": "2026-10-27T10:00:00Z", "invocation": "i-7f3a", **line}))


if __name__ == "__main__":
    main()
