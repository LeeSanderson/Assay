"""The experiment-local Phase 0 summary, experiments/phase0-tdd/summary.py
(PRD v3 section 17; issue #66, spec #58 criterion 9), through the CLI's
`main` on a copy of the committed experiment, its job files, variants and
task packs, with a fake Harbor and a fake `Containers`."""

import json
import shutil
from pathlib import Path

import pytest

from assay.cli import job_config, main
from tests.fake_containers import FakeContainers, gives
from tests.test_experiment_failures import exception
from tests.trial_builder import TrialBuilder

REPO_ROOT = Path(__file__).resolve().parents[1]
REWARD = {"reward": 1, "reference_compiles": 1, "reference_passed": 29, "reference_total": 29,
          "agent_tests_compile": 1, "agent_tests_passed": 1, "agent_tests_total": 1}
HOSTED = ["phase0-cross-control", "phase0-cross-tdd", "phase0-extra"]
LOCAL_MODEL = "laguna-s-2.1"
TEST_FILES = {"go": "stopwatch_test.go", "typescript": "stopwatch.test.ts"}


class FakeHarbor:
    """Plays `harbor run`: one fixture trial for each task, agent and attempt
    that has no result.json yet. The trial seeds, writes one test file and
    finishes; it ran the pinned Claude Code version of its agent, with the
    agent's model and env in its lock.json. `cost` gives each trial's
    cost_usd; `outcomes` gives a <job>/<trial> a list of changes, one for each
    run of it; `bodies` gives a <job>/<trial> its own steps before the
    test file is written."""

    def __init__(self, cost=0.5, outcomes=None, bodies=None):
        self.cost = cost
        self.outcomes = {name: list(changes) for name, changes in (outcomes or {}).items()}
        self.bodies = bodies or {}
        self.ran = []

    def __call__(self, args):
        args = list(args)
        config = job_config(Path(args[args.index("-c") + 1]), args)
        folder = (config.jobs_dir / config.job_name).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text(config.model_dump_json(), encoding="utf-8")
        for task in config.tasks:
            language, slug = Path(task.path).parts[-2:]
            for a, agent in enumerate(config.agents):
                for attempt in range(config.n_attempts):
                    name = f"{language}__{a}{attempt}"
                    if (folder / name / "result.json").exists():
                        continue
                    if (folder / name).exists():
                        shutil.rmtree(folder / name)
                    dumped = agent.model_dump(mode="json")
                    builder = TrialBuilder(folder, language=language, name=name,
                                           claude_code_version=agent.kwargs["version"])
                    builder.lock["agent"] = dumped
                    builder.lock["task"]["path"] = f"tasks\\{language}\\{slug}"
                    builder.result["agent_result"]["cost_usd"] = self.cost
                    builder.seed(gives({**REWARD, "agent_tests_total": 0}))
                    if body := self.bodies.get(f"{config.job_name}/{name}"):
                        body(builder)
                    test = TEST_FILES[language]
                    builder.step().call("Write", {"file_path": f"/app/{test}"},
                                        files={**gives(REWARD), test: "test\n"})
                    builder.finish()
                    builder.reward = REWARD
                    changes = self.outcomes.get(f"{config.job_name}/{name}")
                    if changes:
                        changes.pop(0)(builder)
                    builder.build()
                    (folder / name / "config.json").write_text(
                        json.dumps({"trial_name": name, "agent": dumped}), encoding="utf-8")
                    shutil.rmtree(builder.app)
                    self.ran.append(f"{config.job_name}/{name}")
        return 0


@pytest.fixture(autouse=True)
def no_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr("assay.cli.ENV_FILE", tmp_path / "no.env")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the committed Phase 0 experiment, with its job files,
    variants and task packs."""
    shutil.copytree(REPO_ROOT / "experiments" / "phase0-tdd", tmp_path / "experiments" / "phase0-tdd",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for folder in ("jobs", "variants", "tasks"):
        shutil.copytree(REPO_ROOT / folder, tmp_path / folder,
                        ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def experiment(harbor, *args):
    return main(["experiment", "phase0-tdd", *args], run_harbor=harbor,
                containers=FakeContainers())


def hosted(*args):
    return [arg for job in HOSTED for arg in ("--job", job)] + list(args)


def summary(repo):
    folder = repo / "analysis" / "phase0-tdd" / "summary"
    return (json.loads((folder / "phase0-summary.json").read_text(encoding="utf-8")),
            (folder / "phase0-summary.md").read_text(encoding="utf-8"))


def cell(data, model, condition, language):
    [found] = [c for c in data["cells"] if (c["model_tier"], c["condition"], c["language"])
               == (model, condition, language)]
    return found


def log(repo):
    path = repo / "analysis" / "phase0-tdd" / "experiment-log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_hosted_jobs_give_every_acceptance_number_and_a_short_cell_for_the_local_job(repo):
    assert experiment(FakeHarbor(), *hosted()) == 0

    data, markdown = summary(repo)
    assert [e["files"] for e in log(repo) if e["event"] == "summary-written"] == [[
        "analysis/phase0-tdd/summary/phase0-summary.json",
        "analysis/phase0-tdd/summary/phase0-summary.md"]]
    assert len(data["trials"]) == 10
    first = data["trials"][0]
    assert first["job"] == "phase0-cross-control"
    assert first["cell"]["condition"] == "control"
    assert first["replay"] == {"works": True, "causes": []}
    assert first["test_first_order"] == "no-implementation"  # it writes a test file only
    assert first["red_to_green_order"] == "not-observed"
    assert first["tdd_loop"] == {"cycles": 0, "tests_never_seen_red": 0, "refactor_steps": 0}
    assert first["agent_test_runs"]["snapshots"] == 2
    assert first["errors"] == {}
    # Acceptance 2, 4 and 5.
    assert data["shares"]["trials"] == 10
    assert data["shares"]["file_writing_bash"] == {"count": 0, "share": 0.0}
    assert data["replay_works"] == {"count": 10, "of": 10}
    assert data["agent_test_runs"]["snapshots"] == 20
    # The local job has not run: its cell is short, not a failure.
    local = cell(data, LOCAL_MODEL, "instrument-tdd", "typescript")
    assert (local["expected"], local["kept"], local["short"]) == (1, 0, True)
    haiku = cell(data, "anthropic/claude-haiku-5-5", "instrument-tdd", "typescript")
    assert (haiku["expected"], haiku["kept"], haiku["discarded"], haiku["halted"],
            haiku["short"]) == (2, 2, 0, 0, False)
    assert data["expected_trials"] == 11 and data["kept_trials"] == 10
    # Acceptance 7: ten hosted trials at 0.50 USD.
    cap = data["hosted_cost"]
    assert (cap["kept_usd"], cap["discarded_usd"]) == (pytest.approx(5.0), 0)
    assert cap["total_usd"] == pytest.approx(5.0)
    assert cap["within_cap"] is True
    assert data["claude_code_versions"] == {job: ["2.1.308"] for job in HOSTED}
    for text in ("## Cells", "short", "Replay works on 10 of 10 trials",
                 "no-implementation", "Coverage", "Agreement", "of the £15 cap"):
        assert text in markdown


def test_the_cap_counts_each_discarded_trial_and_the_cells_count_it(repo):
    harbor = FakeHarbor(outcomes={"phase0-cross-tdd/go__10": [exception("ApiOverloadedError")]})

    assert experiment(harbor, *hosted("--retries", "1")) == 0

    data, markdown = summary(repo)
    sonnet_go = cell(data, "anthropic/claude-sonnet-5-5", "instrument-tdd", "go")
    assert (sonnet_go["expected"], sonnet_go["kept"], sonnet_go["discarded"],
            sonnet_go["short"]) == (1, 1, 1, False)
    cap = data["hosted_cost"]
    assert (cap["kept_usd"], cap["discarded_usd"]) == (pytest.approx(5.0), pytest.approx(0.5))
    assert cap["total_usd"] == pytest.approx(5.5)
    assert data["discard_causes"] == [{"cause": "ApiOverloadedError", "count": 1,
                                       "unlisted": False}]
    assert "ApiOverloadedError" in markdown


def test_a_halted_trial_counts_once_as_halted_and_its_cost_once(repo):
    halt = exception("ApiUsageLimitError")
    harbor = FakeHarbor(outcomes={"phase0-cross-control/go__00": [halt]})
    assert experiment(harbor, *hosted()) == 3

    assert experiment(harbor, *hosted()) == 0

    data, _ = summary(repo)
    haiku_go = cell(data, "anthropic/claude-haiku-5-5", "control", "go")
    assert (haiku_go["kept"], haiku_go["discarded"], haiku_go["halted"]) == (1, 0, 1)
    assert data["hosted_cost"]["discarded_usd"] == pytest.approx(0.5)


def test_an_unresolved_discard_leaves_its_cell_short(repo):
    harbor = FakeHarbor(outcomes={"phase0-extra/go__00": [exception("SomethingNewError")]})

    assert experiment(harbor, *hosted()) == 0

    data, markdown = summary(repo)
    haiku_go = cell(data, "anthropic/claude-haiku-5-5", "instrument-tdd", "go")
    assert (haiku_go["expected"], haiku_go["kept"], haiku_go["discarded"],
            haiku_go["short"]) == (2, 1, 1, True)
    assert data["discard_causes"] == [{"cause": "SomethingNewError", "count": 1,
                                       "unlisted": True}]


def local_trial(builder):
    """The local trial: a Read, then a system step in the middle of the
    conversation; the Write of the test file follows."""
    builder.step(metrics={"cached_tokens": 900}).call("Read", {"file_path": "/app/x.ts"})
    builder.step("system")


def test_the_local_trial_values_come_from_its_record_and_its_cost_is_not_hosted(
        repo, monkeypatch):
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", "http://localhost:8080")
    harbor = FakeHarbor(bodies={"phase0-local/typescript__00": local_trial})

    assert experiment(harbor) == 0

    data, markdown = summary(repo)
    [local] = data["local_trials"]
    assert local["job"] == "phase0-local"
    assert local["duration_sec"] == 300
    assert local["tool_calls_after_system_message"] == 1
    assert local["tool_arguments_present"] is True
    assert local["cached_tokens_per_turn"] == [900, None]  # the Write's step has none
    assert cell(data, LOCAL_MODEL, "instrument-tdd", "typescript")["short"] is False
    # L5: a local trial's cost_usd is no money cost.
    assert data["hosted_cost"]["kept_usd"] == pytest.approx(5.0)
    assert data["cost"][LOCAL_MODEL]["total_cost_usd"] == 0
    assert "Background requests: record by hand from the server log." in markdown
    assert "Prefix cache hits for each turn: cached tokens 900, - (ATIF)." in markdown
