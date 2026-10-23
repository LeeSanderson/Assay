"""The Phase 0 summary (spec #15, seam 1; PRD section 7, Phase 0; L5):
fake job folders with their analysis/ outputs in, markdown and JSON out."""

import json

import pytest

from analyze.agent_runs import cross_check_job
from analyze.summary import USD_PER_GBP, render_markdown, summarize, write_summary
from analyze.trace_check import MixedClaudeCodeVersions
from tests.trial_builder import TrialBuilder

GO_STUB = "package stopwatch\n"
GO_TEST = "package stopwatch\n\nfunc TestNew(t *testing.T) {}\n"


class Job:
    """A fake results/<job-id>/ folder, with analysis/<job-id>/ beside it."""

    def __init__(self, tmp_path, name):
        self.dir = tmp_path / "results" / name
        self.analysis = tmp_path / "analysis"
        self._count = 0

    def trial(self, *, model="anthropic/claude-haiku-5-5", local=False, version="2.1.0",
              cost=0.5, tokens=(1000, 200, 300), seconds=60, **kwargs) -> TrialBuilder:
        self._count += 1
        b = TrialBuilder(self.dir, name=f"split-second-stopwatch__t{self._count:06d}",
                         claude_code_version=version, **kwargs)
        b.lock["agent"]["model_name"] = model
        if local:
            b.lock["agent"]["env"] = {"ANTHROPIC_BASE_URL": "${ASSAY_LOCAL_BASE_URL}"}
        b.result.update(
            started_at="2026-01-01T00:00:00Z",
            finished_at=f"2026-01-01T00:{seconds // 60:02d}:{seconds % 60:02d}Z",
            agent_result={"n_input_tokens": tokens[0], "n_cache_tokens": tokens[1],
                          "n_output_tokens": tokens[2], "cost_usd": cost},
        )
        b.seed({"stopwatch.go": GO_STUB, "go.mod": "module stopwatch\n"})
        return b

    def out(self, b: TrialBuilder):
        return self.analysis / self.dir.name / b.dir.name

    def replayed(self, b: TrialBuilder, states=None, works=True, causes=()):
        """Builds the trial and writes its replay.jsonl and replay-works.json."""
        b.build()
        out = b.write_replay(states, analysis_dir=self.out(b))
        (out / "replay-works.json").write_text(
            json.dumps({"works": works, "causes": list(causes)}), encoding="utf-8")


def red_to_green_trial(job, **kwargs):
    """A trial that writes a test, sees it red, writes the implementation, sees it green."""
    b = job.trial(**kwargs)
    test = b.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                         files={"stopwatch_test.go": GO_TEST})
    b.step().call("Bash", {"command": "go test ./..."},
                  result="Exit code 1\n--- FAIL: TestNew", is_error=True)
    impl = b.step().call("Write", {"file_path": "/app/stopwatch.go"},
                         files={"stopwatch.go": GO_STUB + "func New() {}\n"})
    b.step().call("Bash", {"command": "go test ./..."}, result="ok\n")
    job.replayed(b, {test: "fail", impl: "pass"})
    return b


def test_each_trial_gives_its_trace_check_replay_and_order_verdicts(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    b = red_to_green_trial(job)
    cross_check_job(job.dir, job.analysis)

    trial = summarize([job.dir], job.analysis)["trials"][0]

    assert trial["job"] == "phase0-cross"
    assert trial["trial"] == b.dir.name
    assert trial["trace_check"] == {"passed": True, "failed_checks": []}
    assert trial["replay"] == {"works": True, "causes": []}
    assert trial["test_first_order"] == "test-first"
    assert trial["red_to_green_order"] == "red-to-green"
    assert trial["tdd_loop"] == {"cycles": 1, "tests_never_seen_red": 0, "refactor_steps": 0}


def test_each_trial_records_whether_the_skill_loaded_before_the_first_file_write(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    b = job.trial()
    b.step().call("Skill", {"skill": "tdd"}, result="Launching skill: tdd")
    b.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                  files={"stopwatch_test.go": GO_TEST})
    b.build()

    markdown, data = write_summary([job.dir], job.analysis)

    trial = json.loads(data.read_text(encoding="utf-8"))["trials"][0]
    assert trial["skill_load"] == {"loaded": True, "before_first_file_write": True}
    assert "| Skill loaded |" in markdown.read_text(encoding="utf-8")


def test_a_failing_trial_lists_its_failed_checks_and_a_trial_not_replayed_has_no_replay(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    b = job.trial()
    b.instruments = None
    b.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                  files={"stopwatch_test.go": GO_TEST})
    b.build()

    trial = summarize([job.dir], job.analysis)["trials"][0]

    assert trial["trace_check"] == {"passed": False, "failed_checks": ["instruments", "harbor-version"]}
    assert trial["replay"] is None
    assert trial["red_to_green_order"] is None


def test_the_shares_count_trials_with_file_writing_bash_and_bash_test_or_implementation_writes(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    plain = job.trial()  # writes through Write only
    plain.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": GO_TEST})
    plain.build()
    other = job.trial()  # a Bash call writes a file that is neither test nor implementation
    other.step().call("Bash", {"command": "echo x > notes.txt"}, files={"notes.txt": "x\n"})
    other.build()
    classed = job.trial()  # a Bash call writes the test file
    classed.step().call("Bash", {"command": "cat > stopwatch_test.go"},
                        files={"stopwatch_test.go": GO_TEST})
    classed.build()

    shares = summarize([job.dir], job.analysis)["shares"]

    assert shares["trials"] == 3
    assert shares["file_writing_bash"] == {"count": 2, "share": pytest.approx(2 / 3)}
    assert shares["bash_writes_test_or_implementation"] == {"count": 1, "share": pytest.approx(1 / 3)}
    # Risk 1: offline replay applies to a trial with no file-writing Bash call.
    assert shares["offline_replay_applies"] == {"count": 1, "share": pytest.approx(1 / 3)}


def test_throwaway_tests_and_ad_hoc_runs_are_counted_for_each_trial_and_in_the_shares(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    job.trial().build()
    checked = job.trial()  # writes a throwaway test and a script, and runs the script
    checked.step().call("Write", {"file_path": "/app/stopwatch.go"},
                        files={"stopwatch.go": GO_STUB + "func New() {}\n"})
    checked.step().call("Bash", {"command": (
        "cat > /tmp/try_test.go <<'EOF'\npackage x\nEOF\n"
        "cat > /tmp/main.go <<'EOF'\npackage main\nEOF\ngo run /tmp/main.go")})
    checked.build()

    summary = summarize([job.dir], job.analysis)
    markdown = render_markdown(summary)

    assert summary["trials"][1]["test_first_order"] == "throwaway-tests"
    assert summary["trials"][1]["ad_hoc_runs"] == {"count": 1, "first_step_id": 3}
    assert summary["shares"]["ad_hoc_runs"] == {"count": 1, "share": pytest.approx(1 / 2)}
    assert "| throwaway-tests |" in markdown
    assert "Trials with an ad-hoc run (a script the agent wrote, not in the cross-check): " \
           "1 of 2 (50%)." in markdown


def test_web_access_trials_are_kept_and_counted_and_an_unflagged_view_leaves_them_out(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    job.trial().build()
    fetched = job.trial()
    fetched.step().call("WebFetch", {"url": "https://example.com/proof.go"}, result="package x")
    fetched.step().call("Bash", {"command": "echo x > notes.txt"}, files={"notes.txt": "x\n"})
    fetched.build()

    summary = summarize([job.dir], job.analysis)
    markdown = render_markdown(summary)

    assert len(summary["trials"]) == 2
    assert summary["trials"][1]["web_access"] == {"flagged": True, "step_ids": [2]}
    assert summary["shares"]["web_access"] == {"count": 1, "share": pytest.approx(1 / 2)}
    unflagged = summary["unflagged"]
    assert unflagged["shares"]["trials"] == 1
    assert unflagged["shares"]["file_writing_bash"] == {"count": 0, "share": 0}
    assert unflagged["agent_test_runs"]["snapshots"] == 0
    assert "| Web access (steps) |" in markdown
    assert f"| {fetched.dir.name} |" in markdown and "| no | 2 |" in markdown
    assert "Trials that may have reached the web: 1 of 2 (50%)." in markdown
    assert "## Without the web-access trials" in markdown


def test_the_markdown_gives_where_offline_replay_applies_as_trials_without_file_writing_bash(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    job.trial().build()
    other = job.trial()
    other.step().call("Bash", {"command": "go mod tidy"}, files={"go.sum": "x\n"})
    other.build()

    markdown, _ = write_summary([job.dir], job.analysis)

    text = markdown.read_text(encoding="utf-8")
    assert "Trials where offline replay applies (no file-writing `Bash` call): 1 of 2 (50%)." in text


def test_agent_test_runs_give_coverage_and_agreement_for_each_trial_and_pooled(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    red_to_green_trial(job)  # 3 snapshots (seed, test, impl), 2 covered; 2 runs, both agree
    b = job.trial()  # 2 snapshots (seed, test), 1 covered; 1 run that does not agree
    test = b.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                         files={"stopwatch_test.go": GO_TEST})
    b.step().call("Bash", {"command": "go test ./..."}, result="ok\n")
    job.replayed(b, {test: "fail"})
    cross_check_job(job.dir, job.analysis)

    summary = summarize([job.dir], job.analysis)

    first, second = (t["agent_test_runs"] for t in summary["trials"])
    assert (first["coverage"], first["agreement"]) == (pytest.approx(2 / 3), 1.0)
    assert (second["coverage"], second["agreement"]) == (0.5, 0.0)
    assert summary["agent_test_runs"] == {
        "snapshots": 5, "covered_snapshots": 3, "coverage": pytest.approx(3 / 5),
        "compared_runs": 3, "agreeing_runs": 2, "agreement": pytest.approx(2 / 3),
    }


def test_cost_gives_each_model_tier_its_cost_tokens_duration_and_turns_per_trial(tmp_path):
    cross = Job(tmp_path, "phase0-cross")
    for cost, tokens, seconds in ((0.5, (1000, 200, 300), 60), (0.7, (3000, 400, 500), 120)):
        b = cross.trial(cost=cost, tokens=tokens, seconds=seconds)
        b.step().call("Read", {"file_path": "/app/stopwatch.go"})
        b.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                      files={"stopwatch_test.go": GO_TEST})
        b.build()
    sonnet = cross.trial(model="anthropic/claude-sonnet-5-5", cost=2.0, seconds=30)
    sonnet.step().call("Read", {"file_path": "/app/stopwatch.go"})
    sonnet.build()

    tiers = summarize([cross.dir], cross.analysis)["cost"]

    assert tiers["anthropic/claude-haiku-5-5"] == {
        "local": False, "trials": 2,
        "total_cost_usd": pytest.approx(1.2),
        "per_trial": {
            "cost_usd": pytest.approx(0.6), "input_tokens": 2000, "cache_tokens": 300,
            "output_tokens": 400, "duration_sec": 90, "turns": 2,
        },
    }
    assert tiers["anthropic/claude-sonnet-5-5"]["per_trial"]["turns"] == 1
    assert tiers["anthropic/claude-sonnet-5-5"]["total_cost_usd"] == pytest.approx(2.0)


def test_the_local_tier_money_cost_is_zero_and_its_tokens_are_unchanged(tmp_path):
    local = Job(tmp_path, "phase0-local")
    b = local.trial(model="laguna-s-2.1", local=True, cost=3.2, tokens=(5000, 4000, 900),
                    seconds=1800)
    b.step().call("Read", {"file_path": "/app/stopwatch.go"})
    b.build()

    summary = summarize([local.dir], local.analysis)

    tier = summary["cost"]["laguna-s-2.1"]
    assert tier["local"] is True
    assert tier["total_cost_usd"] == 0
    assert tier["per_trial"] == {
        "cost_usd": 0, "input_tokens": 5000, "cache_tokens": 4000,
        "output_tokens": 900, "duration_sec": 1800, "turns": 1,
    }
    assert summary["trials"][0]["cost"]["cost_usd"] == 0


def test_the_hosted_trials_cost_is_shown_in_pounds_against_the_cap(tmp_path):
    cross = Job(tmp_path, "phase0-cross")
    for cost in (5.0, 7.7):
        cross.trial(cost=cost).build()
    local = Job(tmp_path, "phase0-local")
    local.trial(model="laguna-s-2.1", local=True, cost=100.0).build()

    summary = summarize([cross.dir, local.dir], cross.analysis)

    hosted = summary["hosted_cost"]
    assert hosted["total_usd"] == pytest.approx(12.7)
    assert hosted["total_gbp"] == pytest.approx(12.7 / USD_PER_GBP)
    assert (hosted["cap_gbp"], hosted["usd_per_gbp"]) == (15, USD_PER_GBP)
    assert hosted["within_cap"] is (12.7 / USD_PER_GBP <= 15)
    text = render_markdown(summary)
    assert f"£{12.7 / USD_PER_GBP:.2f} of the £15 cap" in text
    assert f"1 GBP = {USD_PER_GBP} USD" in text


def local_trial(tmp_path, **kwargs):
    local = Job(tmp_path, "phase0-local")
    b = local.trial(model="laguna-s-2.1", local=True, seconds=1500, **kwargs)
    b.step().call("Read", {"file_path": "/app/stopwatch.go"})
    b.step("system")  # Claude Code's system message in the middle of the conversation
    b.step().call("Write", {"file_path": "/app/stopwatch_test.go"},
                  files={"stopwatch_test.go": GO_TEST})
    b.step().call("Bash", {"command": "go test ./..."}, result="ok\n")
    b.build()
    return local


def test_the_local_trial_gives_its_time_tool_calls_after_a_system_message_and_arguments(tmp_path):
    local = local_trial(tmp_path)

    summary = summarize([local.dir], local.analysis)

    (trial,) = summary["local_trials"]
    assert trial["duration_sec"] == 1500
    assert trial["tool_calls_after_system_message"] == 2
    assert trial["tool_arguments_present"] is True
    # ATIF gives no cached tokens here and never the background requests.
    assert trial["cached_tokens_per_turn"] is None
    text = render_markdown(summary)
    assert "Tool calls after a system message in the middle of the conversation: 2." in text
    assert "Prefix cache hits for each turn: record by hand from the server log." in text
    assert "Background requests: record by hand from the server log." in text


def test_the_local_trial_gives_cached_tokens_for_each_turn_when_atif_has_them(tmp_path):
    local = Job(tmp_path, "phase0-local")
    b = local.trial(model="laguna-s-2.1", local=True)
    for cached in (0, 900):
        b.step().call("Read", {"file_path": "/app/stopwatch.go"})
        b.steps[-1]["metrics"] = {"cached_tokens": cached}
    b.build()

    summary = summarize([local.dir], local.analysis)

    assert summary["local_trials"][0]["cached_tokens_per_turn"] == [0, 900]
    assert "Prefix cache hits for each turn: cached tokens 0, 900 (ATIF)." in render_markdown(summary)


def test_a_local_trial_with_no_system_message_says_to_record_it_by_hand(tmp_path):
    local = Job(tmp_path, "phase0-local")
    b = local.trial(model="laguna-s-2.1", local=True)
    b.step().call("Read", {}, result="ok")
    b.build()

    summary = summarize([local.dir], local.analysis)

    (trial,) = summary["local_trials"]
    assert trial["tool_calls_after_system_message"] is None
    assert trial["tool_arguments_present"] is False
    assert ("Tool calls after a system message in the middle of the conversation: "
            "none in the trajectory; record by hand from the server log.") in render_markdown(summary)


def files_under(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


def test_the_summary_of_several_jobs_is_markdown_and_json_written_only_under_analysis(tmp_path):
    cross = Job(tmp_path, "phase0-cross")
    red_to_green_trial(cross)
    cross_check_job(cross.dir, cross.analysis)
    local = Job(tmp_path, "phase0-local")
    b = local.trial(model="laguna-s-2.1", local=True, cost=3.2, tokens=(5000, 4000, 900))
    b.step().call("Read", {"file_path": "/app/stopwatch.go"})
    b.build()
    results_before = files_under(tmp_path / "results")
    analysis_before = files_under(cross.analysis)

    markdown, data = write_summary([cross.dir, local.dir], cross.analysis)

    assert files_under(tmp_path / "results") == results_before
    assert sorted(set(files_under(cross.analysis)) - set(analysis_before)) == [
        "phase0-summary.json", "phase0-summary.md",
    ]
    assert (markdown, data) == (cross.analysis / "phase0-summary.md",
                                cross.analysis / "phase0-summary.json")
    written = json.loads(data.read_text(encoding="utf-8"))
    assert [t["job"] for t in written["trials"]] == ["phase0-cross", "phase0-local"]
    assert written["cost"]["laguna-s-2.1"]["total_cost_usd"] == 0
    text = markdown.read_text(encoding="utf-8")
    for value in (cross.dir.name, b.dir.name, "red-to-green", "test-first",
                  "laguna-s-2.1", "anthropic/claude-haiku-5-5", "Coverage", "Agreement"):
        assert value in text


def test_a_job_whose_trials_ran_different_claude_code_versions_stops_the_summary(tmp_path):
    job = Job(tmp_path, "phase0-cross")
    job.trial(version="2.1.0").build()
    job.trial(version="2.1.1").build()

    with pytest.raises(MixedClaudeCodeVersions):
        summarize([job.dir], job.analysis)
