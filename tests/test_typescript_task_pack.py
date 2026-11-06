"""The TypeScript task pack `tasks/typescript/split-second-stopwatch/`: what
is specific to it, chiefly how its verifier counts the agent's tests.
tests/test_task_packs.py gives it the checks that every pack shares.

The fast tests read the pack's files. The slow tests (seam 5) need Docker:
they run `tests/test.sh` on prepared repositories in the task image with no
network, as replay does.
"""

import re

import pytest

from analyze.languages import TEST, classify
from tests.task_packs import REPO_ROOT, packs, run_in_image, verify

PACK = packs("split-second-stopwatch")["typescript"]
STUB = PACK.stub
REFERENCE_TEST = "assay-reference.split-second-stopwatch.test.ts"
REFERENCE_TEST_COUNT = PACK.reference_count


# --- The pack's files -------------------------------------------------------


def test_seed_lock_file_is_not_empty_and_there_is_no_claude_dir():
    assert not (PACK.seed / ".claude").exists()
    assert (PACK.seed / "yarn.lock").stat().st_size > 0


def _reference_error_messages() -> set[str]:
    text = (PACK.path / "tests" / REFERENCE_TEST).read_text(encoding="utf-8")
    return set(re.findall(r"toThrow\(\s*'([^']+)'\s*\)", text))


def test_instruction_interface_states_the_getter_and_advance_time_formats():
    section = PACK.interface_section()
    for name in ("currentLap", "total", "previousLaps", "state", "advanceTime"):
        assert re.search(rf"`{name}[`(]", section), name
    assert '`"HH:MM:SS"`' in section
    for state in ("ready", "running", "stopped"):
        assert f'`"{state}"`' in section, state


def test_instruction_interface_names_exactly_the_reference_error_messages():
    messages = _reference_error_messages()
    assert len(messages) == 4
    stated = set(re.findall(r'`"(cannot [^"`]+)"`', PACK.interface_section()))
    assert stated == messages


# --- Seam 5: test.sh in the task image (Docker) ------------------------------

PASSING_AGENT_TESTS = """\
import { describe, expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from './split-second-stopwatch.ts'

describe('agent', () => {
  it('starts ready', () => {
    expect(new SplitSecondStopwatch().state).toBe('ready')
  })
  it('is wrong on purpose', () => {
    expect(new SplitSecondStopwatch().state).toBe('running')
  })
  it.skip('is skipped', () => {})
})
"""

NESTED_SPEC = """\
import { expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from '../split-second-stopwatch.ts'

it('has no laps', () => {
  expect(new SplitSecondStopwatch().previousLaps).toEqual([])
})
"""

# Runs under babel-jest, but does not type-check.
NON_COMPILING_AGENT_TEST = """\
import { expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from './split-second-stopwatch.ts'

it('starts ready', () => {
  const laps: number = new SplitSecondStopwatch().previousLaps
  expect(laps).toEqual([])
})
"""


@pytest.fixture
def image(pack_images):
    return pack_images(PACK)


def _verify(image: str, tmp_path, files: dict[str, str] | None = None) -> dict:
    return verify(PACK, image, tmp_path, files)


def _run_in_image(image: str, script: str, files: dict[str, str] | None = None, tmp_path=None):
    return run_in_image(PACK, image, script, files, tmp_path)


@pytest.mark.slow
def test_agent_pass_counts_the_prd_test_file_class_only(image, tmp_path):
    # `__tests__/*.ts` and `*.test.js` match Jest's default patterns but not the
    # PRD's TypeScript test-file class (`*.test.ts`, `*.spec.ts`), so the
    # agent pass must not count them.
    files = {
        STUB: PACK.gold(),
        "split-second-stopwatch.test.ts": PASSING_AGENT_TESTS,
        "nested/laps.spec.ts": NESTED_SPEC,
        "__tests__/extra.ts": NESTED_SPEC,
        "other.test.js": "it('x', () => {})\n",
    }
    # The analyzer's table is the source of the class; test.sh must agree with it.
    assert [f for f in files if classify("typescript", f) == TEST] == [
        "split-second-stopwatch.test.ts", "nested/laps.spec.ts"]
    reward = _verify(image, tmp_path, files)
    assert reward == {
        "reward": 1, "reference_compiles": 1,
        "reference_passed": REFERENCE_TEST_COUNT, "reference_total": REFERENCE_TEST_COUNT,
        # A skipped test counts in the total but not as passed.
        "agent_tests_compile": 1, "agent_tests_passed": 2, "agent_tests_total": 4,
    }


# Type-checks, but throws while Jest loads the suite, so it has no test.
AGENT_TEST_THAT_FAILS_TO_LOAD = """\
import { it } from '@jest/globals'

throw new Error('broken suite')

it('never registered', () => {})
"""


@pytest.mark.slow
def test_agent_tests_that_do_not_compile_count_their_files_and_pass_none(image, tmp_path):
    # Replay reads agent_tests_total 0 as `no-tests`, so a red compile must count.
    reward = _verify(image, tmp_path, {
        STUB: PACK.gold(),
        "split-second-stopwatch.test.ts": NON_COMPILING_AGENT_TEST,
        "nested/broken.spec.ts": NON_COMPILING_AGENT_TEST.replace("'./", "'../"),
    })
    assert reward["reward"] == 1
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 2


@pytest.mark.slow
def test_agent_suite_that_fails_to_load_does_not_compile(image, tmp_path):
    reward = _verify(image, tmp_path, {
        STUB: PACK.gold(),
        "split-second-stopwatch.test.ts": AGENT_TEST_THAT_FAILS_TO_LOAD,
    })
    assert reward["reward"] == 1
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1


@pytest.mark.slow
def test_changed_stub_signature_fails_the_reference_compile(image, tmp_path):
    changed = PACK.gold().replace("advanceTime(duration: string)", "advanceTime(duration: number)")
    assert changed != PACK.gold()
    reward = _verify(image, tmp_path, {STUB: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0


@pytest.mark.slow
def test_a_type_error_in_a_file_the_reference_tests_do_not_import_leaves_the_reward(image, tmp_path):
    reward = _verify(image, tmp_path, {
        STUB: PACK.gold(),
        "scratch.ts": "export const broken: number = 'x'\n",
    })
    assert reward["reference_compiles"] == 1
    assert reward["reward"] == 1


@pytest.mark.slow
def test_no_agent_tests_gives_zero_agent_tests_total_and_compiles(image, tmp_path):
    reward = _verify(image, tmp_path, {STUB: PACK.gold()})
    assert reward["agent_tests_total"] == 0
    assert reward["agent_tests_compile"] == 1
    assert reward["reward"] == 1


@pytest.mark.slow
def test_no_agent_tests_and_code_that_does_not_build_gives_zero_compile(image, tmp_path):
    reward = _verify(image, tmp_path, {STUB: PACK.gold() + "\nconst broken: number = 'x'\n"})
    assert reward["agent_tests_total"] == 0
    assert reward["agent_tests_compile"] == 0
    assert reward["reference_compiles"] == 0


@pytest.mark.slow
def test_seed_stub_runs_every_reference_test(image, tmp_path):
    reward = _verify(image, tmp_path)
    assert reward["reference_total"] == REFERENCE_TEST_COUNT
    assert reward["reference_passed"] < REFERENCE_TEST_COUNT


@pytest.mark.slow
def test_yarn_cache_holds_no_exercism_package(image):
    result = _run_in_image(image, "ls /root/.yarn/berry/cache | wc -l; ls /root/.yarn/berry/cache | grep -i exercism; true")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert int(lines[0]) > 0, "the image's Yarn cache is empty or moved"
    assert lines[1:] == []


# The final split-second-stopwatch.ts of the phase0-smoke trial `miXZGpR`, run
# on the pack before the Exercism scrub. It scored 7 of 29 reference tests there.
SMOKE_TRIAL_IMPLEMENTATION = (
    REPO_ROOT / "tests" / "fixtures" / "typescript" / "phase0-smoke-miXZGpR.split-second-stopwatch.ts")


@pytest.mark.slow
def test_smoke_trial_implementation_still_scores_seven_of_twenty_nine(image, tmp_path):
    reward = _verify(image, tmp_path, {STUB: SMOKE_TRIAL_IMPLEMENTATION.read_text(encoding="utf-8")})
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == 7
    assert reward["reference_total"] == REFERENCE_TEST_COUNT
    assert reward["reward"] == 0


@pytest.mark.slow
def test_verifier_leaves_the_repository_unchanged(image, tmp_path):
    result = _run_in_image(
        image,
        "bash /tests/test.sh >/dev/null 2>&1; git -C /app status --porcelain; ls /app",
        {"split-second-stopwatch.test.ts": PASSING_AGENT_TESTS}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "?? split-second-stopwatch.test.ts"
    assert REFERENCE_TEST not in result.stdout


ONE_PASSING_AGENT_TEST = """\
import { expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from './split-second-stopwatch.ts'

it('starts ready', () => {
  expect(new SplitSecondStopwatch().state).toBe('ready')
})
"""


@pytest.mark.slow
@pytest.mark.parametrize("command", ["corepack yarn test", "npm test"])
def test_package_test_script_runs_the_agent_tests(image, tmp_path, command):
    # `yarn test` / `npm test` is the agent's most natural test command.
    test_file = "split-second-stopwatch.test.ts"
    passing = _run_in_image(image, f"cd /app && {command}",
                            {STUB: PACK.gold(), test_file: ONE_PASSING_AGENT_TEST},
                            tmp_path / "pass")
    assert passing.returncode == 0, passing.stdout + passing.stderr
    assert "1 passed" in passing.stdout + passing.stderr

    failing = _run_in_image(image, f"cd /app && {command}",
                            {STUB: PACK.gold(),
                             test_file: ONE_PASSING_AGENT_TEST.replace("'ready'", "'running'")},
                            tmp_path / "fail")
    assert failing.returncode != 0
    assert "1 failed" in failing.stdout + failing.stderr
