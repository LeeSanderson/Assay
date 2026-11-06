"""The Go `split-second-stopwatch` task pack (PRD §5 "Task packs"): what is
specific to it, chiefly how its verifier counts the agent's tests.
tests/test_task_packs.py gives it the checks that every pack shares.

Fast tests read the pack's files. Slow tests build the pack image and run
`tests/test.sh` on prepared repositories.
"""

import pytest

from tests.task_packs import packs, verify

PACK = packs("split-second-stopwatch")["go"]
STUB = PACK.stub


def test_stub_declares_the_stopwatch_type():
    assert "type SplitSecondStopwatch struct{}" in PACK.stub_text()


def test_source_instructions_hold_the_command_table():
    prose = PACK.instruction().split("\n## Interface\n")[0]
    assert "| Command | Begin state |" in prose


def test_interface_section_states_the_getter_and_advance_time_formats():
    section = PACK.interface_section()
    for name in ("CurrentLap", "Total", "PreviousLaps", "AdvanceTime", "State"):
        assert f"`{name}" in section, name
    assert '"HH:MM:SS"' in section
    assert '"00:00:00"' in section
    for state in ('"ready"', '"running"', '"stopped"'):
        assert state in section, state


def test_interface_section_gives_each_error_message_exactly():
    # The messages the reference tests compare with err.Error().
    section = PACK.interface_section()
    for message in (
        "cannot start an already running stopwatch",
        "cannot stop a stopwatch that is not running",
        "cannot lap a stopwatch that is not running",
        "cannot reset a stopwatch that is not stopped",
    ):
        assert f'"{message}"' in section, message


# --- Slow: the pack image and tests/test.sh -------------------------------

AGENT_TESTS_ONE_FAILING = """package splitsecondstopwatch

import "testing"

func TestNewIsReady(t *testing.T) {
	if got := NewSplitSecondStopwatch().State(); got != "ready" {
		t.Fatalf("got %q", got)
	}
}

func TestStates(t *testing.T) {
	t.Run("ready", func(t *testing.T) {})
	t.Run("wrong", func(t *testing.T) { t.Fatal("deliberately red") })
}
"""

# Redeclares a reference test's name and does not compile on its own.
AGENT_TESTS_NOT_COMPILING = """package splitsecondstopwatch

import "testing"

func TestTime(t *testing.T) {
	undefinedHelper()
}
"""


@pytest.fixture
def image(pack_images):
    return pack_images(PACK)


@pytest.mark.slow
def test_agent_tests_are_counted_by_leaf_test(image, tmp_path):
    reward = verify(PACK, image, tmp_path,
                    {STUB: PACK.gold(), "stopwatch_test.go": AGENT_TESTS_ONE_FAILING})
    assert reward["reward"] == 1
    assert reward["agent_tests_compile"] == 1
    assert reward["agent_tests_passed"] == 2
    assert reward["agent_tests_total"] == 3


@pytest.mark.slow
def test_agent_test_that_redeclares_a_reference_test_leaves_outcome_pass_unaffected(
    image, tmp_path
):
    reward = verify(PACK, image, tmp_path,
                    {STUB: PACK.gold(), "stopwatch_test.go": AGENT_TESTS_NOT_COMPILING})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == PACK.reference_count
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0


@pytest.mark.slow
def test_agent_test_that_does_not_compile_counts_its_files_so_replay_sees_red_compile(
    image, tmp_path
):
    # Replay reads agent_tests_total 0 as `no-tests`; a build failure emits no
    # test events, so the verifier counts the agent test files instead.
    reward = verify(PACK, image, tmp_path, {
        STUB: PACK.gold(),
        "stopwatch_test.go": AGENT_TESTS_NOT_COMPILING,
        "more_test.go": AGENT_TESTS_ONE_FAILING.replace("TestNewIsReady", "TestMore")
        .replace("TestStates", "TestMoreStates"),
    })
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 2


@pytest.mark.slow
def test_changed_stub_signature_gives_reference_compiles_0(image, tmp_path):
    # Still compiles on its own; only the reference tests' call breaks.
    changed = PACK.gold().replace("AdvanceTime(by string)", "AdvanceTime(by string, _ int)")
    assert changed != PACK.gold()
    reward = verify(PACK, image, tmp_path, {STUB: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0
