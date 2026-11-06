"""The rung-4 task packs, `tasks/typescript/bowling` and `tasks/go/bowling`
(issue #74; PRD §15 "The TDD pack recipe"): what is specific to them.
tests/test_task_packs.py gives them the checks that every pack shares."""

import re

import pytest

from tests.task_packs import packs, verify

TS, GO = packs("bowling")["typescript"], packs("bowling")["go"]
# The error messages that the TypeScript reference tests compare exactly.
TS_ERROR_MESSAGES = {
    "Negative roll is invalid",
    "Pin count exceeds pins on the lane",
    "Score cannot be taken until the end of the game",
    "Cannot roll after game is over",
}


def test_source_instructions_end_before_the_interface():
    for pack in (TS, GO):
        prose = pack.instruction().split("\n## Interface\n")[0]
        assert prose.rstrip().endswith("It returns the total score for that game."), pack


def test_typescript_interface_gives_each_reference_error_message_exactly():
    reference = (TS.path / "tests" / "assay-reference.bowling.test.ts").read_text(encoding="utf-8")
    messages = set(re.findall(r"toThrow\(\s*new Error\(\s*'([^']+)'\s*\)\s*\)", reference))
    assert messages == TS_ERROR_MESSAGES
    stated = set(re.findall(r'`"([^"`]+)"`', TS.interface_section()))
    assert stated >= messages


def test_typescript_interface_states_the_class_and_its_methods():
    section = TS.interface_section()
    for name in ("new Bowling()", "roll(pins", "score()"):
        assert name in section, name


def test_go_interface_states_the_constructor_and_the_error_returns():
    section = GO.interface_section()
    for name in ("NewGame()", "Roll(pins int) error", "Score() (int, error)"):
        assert name in section, name
    assert "non-nil error" in section


def test_go_reference_cases_are_the_same_31_cases():
    cases = (GO.path / "tests" / "reference" / "assay_reference_cases_test.go").read_text(
        encoding="utf-8")
    assert cases.count("description:") == GO.reference_count == TS.reference_count


def test_go_stub_declares_the_game_type_the_source_left_undefined():
    # The source stub leaves `Game` undefined, so it does not build.
    assert "type Game struct{}" in GO.stub_text()
    assert "type Game struct{}" in GO.changes()


@pytest.mark.slow
@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_untouched_stub_passes_no_reference_test(pack, pack_images, tmp_path):
    reward = verify(pack, pack_images(pack), tmp_path)
    assert reward["reference_passed"] == 0
