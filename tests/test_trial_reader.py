"""The trial reader over a fake trial folder (spec #15, seam 1)."""

import subprocess

from analyze.trial import ABSENT, Identity, PathChange, Totals, Usage, read_job, read_trial
from tests.trial_builder import COMMITTED_DIGEST, TrialBuilder


def test_reader_joins_each_tool_call_with_its_observation_in_atif_order(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": "package stopwatch\n"})
    step = trial.step()
    read_id = step.call("Read", {"file_path": "/app/stopwatch.go"}, result="package stopwatch")
    bash_id = step.call("Bash", {"command": "go test ./..."},
                        result="Exit code 1\nFAIL", is_error=True)
    silent_id = trial.step().call("Bash", {"command": "sleep 999"}, result=None)

    t = read_trial(trial.build())

    assert [(c.step_id, c.position, c.tool_use_id, c.function_name) for c in t.tool_calls] == [
        (2, 0, read_id, "Read"), (2, 1, bash_id, "Bash"), (3, 0, silent_id, "Bash"),
    ]
    assert (t.tool_calls[1].arguments, t.tool_calls[1].result, t.tool_calls[1].is_error) == (
        {"command": "go test ./..."}, "Exit code 1\nFAIL", True,
    )
    assert (t.tool_calls[0].is_error, t.tool_calls[2].result, t.tool_calls[2].is_error) == (
        False, ABSENT, ABSENT,
    )


def test_reader_gives_trace_lines_joined_by_tool_use_id_and_a_real_trace_git(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": "package stopwatch\n"})
    write_id = trial.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                                 files={"stopwatch_test.go": "package stopwatch\n"})

    t = read_trial(trial.build())

    assert [line.event for line in t.trace] == ["seed", "call"]
    (line,) = t.trace_lines_for(write_id)
    assert (line.changed, line.paths) == (True, (PathChange("A", "stopwatch_test.go"),))
    files = subprocess.run(
        ["git", "--git-dir", str(t.trace_git), "ls-tree", "-r", "--name-only", line.commit],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert files == ["stopwatch.go", "stopwatch_test.go"]


def test_reader_gives_the_language_versions_and_the_json_files(make_trial):
    trial = make_trial("typescript", claude_code_version="2.1.7")
    trial.reward = {"reward": 1, "agent_tests_total": 3}
    trial.seed({"a.ts": "export {}\n"})

    t = read_trial(trial.build())

    assert t.language == "typescript"
    assert t.task_path == ("tasks", "typescript", "split-second-stopwatch")
    assert t.agent_version == "2.1.7"
    assert t.requested_version == "2.1.7"
    assert t.reward == {"reward": 1, "agent_tests_total": 3}
    assert t.instruments["harbor_version"] == "0.24.0"


def test_reader_gives_the_model_tier_usage_duration_and_turns(make_trial):
    trial = make_trial("go")
    trial.lock["agent"].update(model_name="laguna-s-2.1", env={"ANTHROPIC_BASE_URL": "x"})
    trial.result.update(started_at="2026-01-01T00:00:00Z", finished_at="2026-01-01T00:01:30Z",
                        agent_result={"n_input_tokens": 10, "n_cache_tokens": 4,
                                      "n_output_tokens": 3, "cost_usd": 0.25})
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"})
    trial.step("system")
    trial.step().call("Read", {"file_path": "/app/stopwatch.go"})

    t = read_trial(trial.build())

    assert (t.model_tier, t.local, t.duration_sec, t.turns) == ("laguna-s-2.1", True, 90, 2)
    assert t.usage == Usage(cost_usd=0.25, input_tokens=10, cache_tokens=4, output_tokens=3)
    assert t.system_step_ids == (3,)


def test_read_job_reads_each_trial_folder_in_name_order(tmp_path):
    for name in ("b__2", "a__1"):
        TrialBuilder(tmp_path / "job", name=name).build()
    (tmp_path / "job" / "lock.json").write_text("{}", encoding="utf-8")  # the job's own file

    assert [t.name for t in read_job(tmp_path / "job")] == ["a__1", "b__2"]


def test_reader_gives_none_for_missing_files(make_trial):
    trial = make_trial("go")
    trial.instruments = None
    trial.result = None
    path = trial.build()

    t = read_trial(path)

    assert (t.reward, t.instruments, t.trace) == (None, None, ())
    assert (t.usage, t.duration_sec) == (Usage(None, None, None, None), None)


# --- the Claude Code reader: the trial record (PRD v3 section 8) -------------

def test_reader_builds_steps_with_their_tokens_cost_and_tool_calls(make_trial):
    trial = make_trial("go")
    step = trial.step(metrics={"prompt_tokens": 120, "cached_tokens": 100,
                               "completion_tokens": 7, "cost_usd": 0.02})
    read_id = step.call("Read", {"file_path": "/app/stopwatch.go"})
    bash_id = step.call("Bash", {"command": "go test ./...", "description": "run tests"})

    t = read_trial(trial.build())

    user, agent = t.steps
    assert (user.step_id, user.source, user.tool_calls) == (1, "user", ())
    assert (agent.step_id, agent.source, agent.timestamp) == (2, "agent", "2026-01-01T00:00:02.000Z")
    assert (agent.input_tokens, agent.cached_tokens, agent.output_tokens, agent.cost_usd) == (
        120, 100, 7, 0.02)
    assert [c.tool_use_id for c in agent.tool_calls] == [read_id, bash_id]
    assert (agent.tool_calls[1].name, agent.tool_calls[1].arguments) == (
        "Bash", {"command": "go test ./...", "description": "run tests"})


def test_reader_sets_the_kind_of_each_tool_call_and_the_command_of_a_shell_call(make_trial):
    trial = make_trial("go")
    step = trial.step()
    for name, arguments in [("Bash", {"command": "go test ./..."}), ("WebFetch", {"url": "u"}),
                            ("WebSearch", {"query": "q"}), ("Skill", {"skill": "tdd"}),
                            ("Edit", {"file_path": "/app/a.go"}), ("mcp__x__y", {})]:
        step.call(name, arguments)

    t = read_trial(trial.build())

    assert [(c.kind, c.command) for c in t.tool_calls] == [
        ("shell", "go test ./..."), ("web", None), ("web", None), ("skill", None),
        ("other", None), ("other", None),
    ]


def test_reader_marks_each_missing_optional_part_absent(make_trial):
    trial = make_trial("go")
    step = trial.step()  # no metrics: no cost for the step
    silent_id = step.call("Bash", {"command": "sleep 999"}, result=None)
    passed_id = step.call("Bash", {"command": "true"}, result="ok", is_error=False)
    failed_id = step.call("Bash", {"command": "false"}, result="Exit code 1\n", is_error=True)
    unflagged_id = step.call("Read", {"file_path": "/app/a.go"}, result="x", is_error=None)

    t = read_trial(trial.build())

    calls = {c.tool_use_id: c for c in t.tool_calls}
    assert t.steps[1].cost_usd is ABSENT
    assert (calls[silent_id].result, calls[silent_id].is_error, calls[silent_id].exit_code) == (
        ABSENT, ABSENT, ABSENT)
    assert (calls[passed_id].result, calls[passed_id].is_error, calls[passed_id].exit_code) == (
        "ok", False, ABSENT)
    assert (calls[failed_id].is_error, calls[failed_id].exit_code) == (True, 1)
    assert calls[unflagged_id].is_error is ABSENT
    assert all(c.duration_sec is ABSENT for c in t.tool_calls)  # Claude Code gives no call time


def test_reader_joins_the_history_to_each_call(make_trial):
    trial = make_trial("go")
    trial.seed({"stopwatch.go": "package stopwatch\n"})
    write_id = trial.step().call("Write", {"file_path": "/app/a_test.go", "content": "x"},
                                 files={"a_test.go": "x"})
    trial.finish()

    t = read_trial(trial.build())

    (call,) = t.tool_calls
    (line,) = t.history_for(call)
    assert (line.event, line.tool_use_id, line.paths) == (
        "call", write_id, (PathChange("A", "a_test.go"),))
    assert (t.granularity, t.calls_may_overlap) == ("per-tool-call", True)
    assert [line.event for line in t.trace] == ["seed", "call", "final"]


def test_reader_builds_the_totals_and_the_identity(make_trial):
    trial = make_trial("typescript", claude_code_version="2.1.7")
    trial.lock["agent"]["model_name"] = "claude-haiku-4-5"
    trial.lock["task"]["digest"] = "sha256:pack"
    trial.result.update(started_at="2026-01-01T00:00:00Z", finished_at="2026-01-01T00:02:00Z",
                        agent_result={"n_input_tokens": 50, "n_cache_tokens": 40,
                                      "n_output_tokens": 9, "cost_usd": 0.5})
    trial.seed({"a.ts": "export {}\n"})
    trial.finish()

    t = read_trial(trial.build())

    assert t.totals == Totals(input_tokens=50, cached_tokens=40, output_tokens=9,
                              cost_usd=0.5, duration_sec=120)
    assert t.identity == Identity(
        harness="claude-code", pinned_version="2.1.7", version="2.1.7",
        model_tier="claude-haiku-4-5",
        task_pack="tasks/typescript/split-second-stopwatch", task_pack_digest="sha256:pack",
        variant_digest="", instruments_digest=COMMITTED_DIGEST, harbor_version="0.24.0",
    )
    assert t.missing_core() == []


def test_the_variant_digest_comes_from_the_part_digests_harbor_locked(make_trial):
    control = make_trial("go")
    variant = make_trial("go")
    variant.lock["skills"] = [{"name": "tdd", "source": "s", "digest": "sha256:skill"}]
    other = make_trial("go")
    other.lock["extra_instructions"] = [{"path": "p", "digest": "sha256:extra"}]

    digests = [read_trial(t.build()).identity.variant_digest for t in (control, variant, other)]

    assert digests[0] == ""
    assert digests[1].startswith("sha256:") and digests[2].startswith("sha256:")
    assert digests[1] != digests[2]


def test_the_reader_names_each_required_core_field_it_could_not_build(make_trial):
    trial = make_trial("go")
    trial.instruments = None
    trial.result = None
    del trial.lock["agent"]["model_name"]

    t = read_trial(trial.build())

    assert set(t.missing_core()) >= {
        "history.granularity", "totals.input_tokens", "totals.cost_usd",
        "totals.duration_sec", "identity.model_tier", "identity.instruments_digest",
        "identity.harbor_version",
    }
    assert "identity.variant_digest" not in t.missing_core()  # empty is the control
