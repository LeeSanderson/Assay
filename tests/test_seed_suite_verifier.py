"""The verifier honours a seed suite (issue #80; PRD section 20, "The pack
recipe"): on a codebase seed, the agent tests are the test files that the
agent added or changed, and the outcome pass restores the seed suite and runs
it beside the feature tests.

The proof is a small test-fixture pack in each language, `tally`, in
tests/fixtures/packs/<language>/tally. Its seed is a tiny working codebase with
a seed suite of 5 tests in two folders (3 at the top, 2 in a subfolder), and a
stub for the feature, `top`, which 3 feature tests check. Its tests/test.sh is
the model pack's with the slug swapped (tests/test_task_packs.py checks it), so
this module tests the verifier that every pack runs.

Fast tests read the fixture's files. Slow tests build the fixture's image and
run its tests/test.sh, then replay and the trajectory, on prepared trials.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from analyze.agent_runs import agent_runs
from analyze.replay import read_replay, replay_job
from analyze.trajectory import analyze_trial
from analyze.trial import read_trial
from tests.task_packs import FIXTURE_PACKS, PACKS, REPO_ROOT, Pack, verify
from tests.trial_builder import TrialBuilder

TS, GO = FIXTURE_PACKS
SLUG = TS.slug
FEATURE_TESTS = TS.reference_count
SEED_SUITE_TESTS = 5
each_fixture = pytest.mark.parametrize("pack", FIXTURE_PACKS, ids=str)

GOLD = {"typescript": "solution/tally.ts", "go": "solution/tally.go"}
# A seed test in the top folder, and the stub that its feature lives in.
SEED_TEST = {"typescript": "tally.test.ts", "go": "tally_test.go"}
STUB = {"typescript": "tally.ts", "go": "tally.go"}

# One new agent test that passes on the seed and one that fails until `top`
# exists: 2 agent tests, 1 passing on the seed.
AGENT_TEST = {
    "typescript": ("top.test.ts", """\
import { expect, it } from '@jest/globals'
import { Tally } from './tally.ts'

it('starts empty', () => {
  expect(new Tally().names()).toEqual([])
})

it('gives the top name', () => {
  const tally = new Tally()
  tally.add('apple')
  expect(tally.top(1)).toEqual(['apple'])
})
"""),
    "go": ("top_test.go", """\
package tally

import "testing"

func TestAgentStartsEmpty(t *testing.T) {
	if len(New().Names()) != 0 {
		t.Fatal("not empty")
	}
}

func TestAgentGivesTheTopName(t *testing.T) {
	tally := New()
	tally.Add("apple", 1)
	if got, err := tally.Top(1); err != nil || len(got) != 1 || got[0] != "apple" {
		t.Fatalf("Top(1) = %v, %v", got, err)
	}
}
"""),
}

# A seed test in a subfolder, weakened so that it passes against a broken
# normalise that only the seed suite checks: the feature tests still pass.
NAMES_TEST = {"typescript": "text/names.test.ts", "go": "names/names_test.go"}
NAMES = {"typescript": "text/names.ts", "go": "names/names.go"}
WEAKENED = {
    "typescript": ("expect(normalise('  apple ')).toBe('apple')",
                   "expect(normalise('  apple ')).toBe('  apple ')"),
    "go": ('Normalise("  apple "); got != "apple"', 'Normalise("  apple "); got != "  apple "'),
}
BROKEN_NORMALISE = {
    "typescript": ("name.trim().toLowerCase()", "name.toLowerCase()"),
    "go": ("strings.ToLower(strings.TrimSpace(name))", "strings.ToLower(name)"),
}

# A whole seed test file rewritten so that it does not compile.
NOT_COMPILING = {
    "typescript": """\
import { expect, it } from '@jest/globals'

it('does not type-check', () => {
  const count: number = 'one'
  expect(count).toBe('one')
})
""",
    "go": "package tally\n\nimport \"testing\"\n\n"
          "func TestAgentDoesNotCompile(t *testing.T) {\n\tundefinedHelper()\n}\n",
}


def gold(pack: Pack) -> str:
    return (pack.path / GOLD[pack.language]).read_text(encoding="utf-8")


def seed_text(pack: Pack, name: str) -> str:
    return (pack.seed / name).read_text(encoding="utf-8")


def changed(text: str, old_new: tuple[str, str]) -> str:
    old, new = old_new
    assert old in text
    return text.replace(old, new)


# --- Fast: the fixture's files ----------------------------------------------------


@each_fixture
def test_fixture_seed_suite_copy_is_the_seed_test_files_in_two_folders(pack):
    assert pack.seed_suite_copy() == pack.seed_test_files()
    assert len({Path(f).parent for f in pack.seed_test_files()}) == 2
    for name in pack.seed_test_files():
        assert (pack.seed_suite / name).read_bytes() == (pack.seed / name).read_bytes(), name


@pytest.mark.parametrize(
    "pack", [p for p in PACKS if p.task_toml()["metadata"].get("seed_size", "stub") == "stub"],
    ids=str)
def test_every_pack_on_a_stub_has_an_empty_seed_suite_and_no_seed_test_file(pack):
    # An Exercism pack, or a purpose-written pack on a stub, has no seed
    # suite, so it holds no copy of one. tests/test_task_packs.py checks the
    # copy of a codebase seed's suite.
    assert pack.seed_test_files() == []
    assert not pack.seed_suite.exists()


@each_fixture
def test_fixture_files_have_lf_line_endings(pack):
    for path in pack.path.rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


# --- Slow: tests/test.sh in the fixture's image -----------------------------------


@pytest.fixture
def image(pack, pack_images):
    return pack_images(pack)


@pytest.mark.slow
@each_fixture
def test_unchanged_seed_gives_no_tests_the_full_seed_suite_and_reward_0(pack, image, tmp_path):
    reward = verify(pack, image, tmp_path)
    assert reward["agent_tests_total"] == 0  # replay's no-tests, not green
    assert reward["seed_suite_passed"] == reward["seed_suite_total"] == SEED_SUITE_TESTS
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == 0
    assert reward["reference_total"] == FEATURE_TESTS
    assert reward["reward"] == 0


@pytest.mark.slow
@each_fixture
def test_gold_passes_the_feature_tests_and_the_seed_suite_compiled_together(pack, image,
                                                                            tmp_path):
    reward = verify(pack, image, tmp_path, {STUB[pack.language]: gold(pack)})
    assert reward["reward"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == FEATURE_TESTS
    assert reward["seed_suite_passed"] == reward["seed_suite_total"] == SEED_SUITE_TESTS
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
@each_fixture
def test_an_added_test_file_counts_as_agent_tests_and_not_in_the_seed_suite(pack, image,
                                                                            tmp_path):
    name, content = AGENT_TEST[pack.language]
    reward = verify(pack, image, tmp_path, {name: content})
    assert reward["agent_tests_compile"] == 1
    assert reward["agent_tests_passed"] == 1
    assert reward["agent_tests_total"] == 2
    assert reward["seed_suite_passed"] == reward["seed_suite_total"] == SEED_SUITE_TESTS
    assert reward["reference_total"] == FEATURE_TESTS


@pytest.mark.slow
@each_fixture
def test_a_seed_test_weakened_to_pass_against_broken_code_gives_reward_0(pack, image, tmp_path):
    lang = pack.language
    broken = changed(seed_text(pack, NAMES[lang]), BROKEN_NORMALISE[lang])
    weakened = changed(seed_text(pack, NAMES_TEST[lang]), WEAKENED[lang])
    reward = verify(pack, image, tmp_path, {STUB[lang]: gold(pack), NAMES[lang]: broken,
                                            NAMES_TEST[lang]: weakened})
    assert reward["reward"] == 0
    assert reward["reference_passed"] == reward["reference_total"] == FEATURE_TESTS
    # The restored seed test catches the broken normalise.
    assert reward["seed_suite_passed"] == SEED_SUITE_TESTS - 1
    assert reward["seed_suite_total"] == SEED_SUITE_TESTS
    # The edited file is the only agent test file, and both its tests pass.
    assert reward["agent_tests_compile"] == 1
    assert reward["agent_tests_passed"] == reward["agent_tests_total"] == 2


@pytest.mark.slow
@each_fixture
def test_a_deleted_seed_test_file_still_runs_in_the_outcome(pack, image, tmp_path):
    lang = pack.language
    broken = changed(seed_text(pack, NAMES[lang]), BROKEN_NORMALISE[lang])
    reward = verify(pack, image, tmp_path, {STUB[lang]: gold(pack), NAMES[lang]: broken},
                    delete=(NAMES_TEST[lang],))
    assert reward["reward"] == 0
    assert reward["reference_passed"] == reward["reference_total"] == FEATURE_TESTS
    assert reward["seed_suite_passed"] == SEED_SUITE_TESTS - 1
    assert reward["seed_suite_total"] == SEED_SUITE_TESTS
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
@each_fixture
def test_an_agent_test_that_does_not_compile_is_red_compile_and_the_seed_suite_still_runs(
    pack, image, tmp_path
):
    # The agent rewrites a seed test file so that it does not compile: it is an
    # agent test, removed before the outcome run, and its seed form restored.
    lang = pack.language
    reward = verify(pack, image, tmp_path,
                    {STUB[lang]: gold(pack), SEED_TEST[lang]: NOT_COMPILING[lang]})
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["seed_suite_passed"] == reward["seed_suite_total"] == SEED_SUITE_TESTS
    assert reward["reward"] == 1


# --- Slow: replay and the trajectory on fixture snapshots --------------------------


def _app_files(image: str) -> dict[str, bytes]:
    """The image's /app as the trace hook's seed fire records it: no .git/, no node_modules/."""
    done = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image,
         "tar", "-C", "/app", "--exclude=./.git", "-cf", "-", "."],
        capture_output=True, check=True, timeout=300,
    )
    files = {}
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        for member in tar.getmembers():
            name = member.name.removeprefix("./")
            if member.isfile() and "node_modules" not in name.split("/"):
                files[name] = tar.extractfile(member).read()
    return files


TEST_COMMAND = {"typescript": "corepack yarn jest", "go": "go test ./..."}


@pytest.mark.slow
@each_fixture
def test_replay_of_a_red_then_green_trial_gives_no_tests_for_the_seed_and_red_to_green(
    pack, tmp_path
):
    from assay.containers import DockerContainers

    lang = pack.language
    runner = DockerContainers()
    image = runner.pack_image(pack.path)
    job = tmp_path / "results" / "job"
    trial = TrialBuilder(job, language=lang, name=f"{SLUG}__{lang}")
    trial.lock["task"]["path"] = str(pack.path.relative_to(REPO_ROOT))
    trial.seed(_app_files(image))
    name, content = AGENT_TEST[lang]
    red_write = trial.step().call("Write", {"file_path": f"/app/{name}"}, files={name: content})
    red = trial.step().call("Bash", {"command": TEST_COMMAND[lang]},
                            result="Exit code 1\nFAIL gives the top name", is_error=True)
    green_write = trial.step().call("Write", {"file_path": f"/app/{STUB[lang]}"},
                                    files={STUB[lang]: gold(pack)})
    green = trial.step().call("Bash", {"command": TEST_COMMAND[lang]}, result="ok\n")
    trial.reward = {
        "reward": 1, "reference_compiles": 1, "reference_passed": FEATURE_TESTS,
        "reference_total": FEATURE_TESTS, "agent_tests_compile": 1, "agent_tests_passed": 2,
        "agent_tests_total": 2, "seed_suite_passed": SEED_SUITE_TESTS,
        "seed_suite_total": SEED_SUITE_TESTS,
    }
    built = trial.build()

    verdicts = replay_job(job, tmp_path / "analysis", runner, tasks_root=REPO_ROOT)

    assert verdicts[built.name].causes == []
    replay = read_replay(tmp_path / "analysis" / "job" / built.name)
    assert [(line["tool_use_id"], line["test_state"]) for line in replay] == [
        (None, "no-tests"), (red_write, "fail"), (green_write, "pass")]
    record = read_trial(built)
    out = analyze_trial(record, replay, agent_runs(record, replay))
    assert out["red_to_green_order"] == {
        "verdict": "red-to-green", "first_seen_red": red, "first_seen_green": green,
    }
    assert replay[0]["seed_suite_passed"] == replay[0]["seed_suite_total"] == SEED_SUITE_TESTS
