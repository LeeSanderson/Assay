"""The rung-3 `poker` task packs, TypeScript and Go (issue #73; PRD section 15,
"The TDD pack recipe"): what is specific to them. tests/test_task_packs.py
gives them the checks that every pack shares."""

import pytest

from tests.task_packs import packs, verify

TS, GO = packs("poker")["typescript"], packs("poker")["go"]


def test_the_source_instructions_are_the_short_poker_text():
    for pack in (TS, GO):
        assert pack.instruction().startswith(
            "# Instructions\n\nPick the best hand(s) from a list of poker hands.\n\n"
            "See [Wikipedia][poker-hands] for an overview of poker hands.\n\n"
            "[poker-hands]: https://en.wikipedia.org/wiki/List_of_poker_hands\n"
            "\n## Interface\n"), pack


def test_verifier_is_the_model_packs_but_for_its_name():
    for pack in (TS, GO):
        script = (pack.path / "tests" / "test.sh").read_text(encoding="utf-8")
        model_script = (pack.model / "tests" / "test.sh").read_text(encoding="utf-8")
        assert "poker" in script.splitlines()[1]
        assert script.replace("poker", "split-second-stopwatch") == model_script


def test_typescript_interface_states_the_card_format_and_the_tie_order():
    section = TS.interface_section()
    assert "`bestHands(hands)`" in section
    for rank in ("`2`", "`10`", "`J`", "`Q`", "`K`", "`A`"):
        assert rank in section, rank
    for suit in ("`S`", "`H`", "`D`", "`C`"):
        assert suit in section, suit
    assert "same order" in section


def test_go_interface_states_the_card_format_the_tie_order_and_the_error():
    section = GO.interface_section()
    assert "`BestHand(hands []string) ([]string, error)`" in section
    for suit in ("♤", "♡", "♢", "♧"):
        assert suit in section, suit
    assert "same order" in section
    assert "error" in section


def test_go_metadata_records_the_renames_and_the_appended_instructions():
    meta = GO.task_toml()["metadata"]
    assert meta["source_dir"] == "exercises/practice/poker"
    assert len(meta["copied_paths"]) == len(meta["pack_paths"])
    assert "instructions.append.md" in GO.changes()


# --- Slow: the pack images and tests/test.sh ---------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("pack, old, new", [
    (TS, "bestHands(hands: string[])", "bestHands(hands: number[])"),
    (GO, "func BestHand(hands []string)", "func BestHand(hands []string, _ int)"),
], ids=str)
def test_changed_stub_signature_fails_the_reference_compile(pack, old, new, pack_images,
                                                            tmp_path):
    changed = pack.gold().replace(old, new)
    assert changed != pack.gold()
    reward = verify(pack, pack_images(pack), tmp_path, {pack.stub: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0


@pytest.mark.slow
@pytest.mark.parametrize("pack", [TS, GO], ids=str)
def test_untouched_stub_passes_no_reference_test(pack, pack_images, tmp_path):
    # A Go stub panics, which ends the reference run after its first case.
    reward = verify(pack, pack_images(pack), tmp_path)
    assert reward["reference_passed"] == 0
