"""The rung-6 task packs: `tasks/typescript/alphametics/` and
`tasks/go/alphametics/` (issue #76; PRD Part II, "The difficulty ladder").
What is specific to them, chiefly the Go reference cases that the pack drops
so that both languages hold the same eight cases; tests/test_task_packs.py
gives them the checks that every pack shares."""

import re

import pytest

from tests.task_packs import packs, verify

TS, GO = packs("alphametics")["typescript"], packs("alphametics")["go"]
GO_CASES = GO.path / "tests" / "reference" / "assay_reference_cases_test.go"


def _ts_reference_descriptions() -> list[str]:
    text = (TS.path / "tests" / "assay-reference.alphametics.test.ts").read_text(encoding="utf-8")
    return re.findall(r"^\s*it\('([^']+)'", text, re.MULTILINE)


def _go_reference_descriptions() -> list[str]:
    text = GO_CASES.read_text(encoding="utf-8")
    return re.findall(r'^\s*description:\s*"([^"]+)"', text, re.MULTILINE)


def test_both_languages_hold_the_same_eight_reference_cases():
    assert len(_ts_reference_descriptions()) == 8 == TS.reference_count == GO.reference_count
    assert _go_reference_descriptions() == _ts_reference_descriptions()


def test_go_pack_drops_the_199_addend_case_and_records_it():
    assert "199 addends" not in GO_CASES.read_text(encoding="utf-8")
    assert "ten letters and 199 addends" in GO.changes()


def test_go_pack_drops_the_two_digits_final_carry_case_and_records_it():
    assert "two digits final carry" not in _go_reference_descriptions()
    assert "two digits final carry" in GO.changes()


def test_interface_states_the_solution_map_and_the_no_solution_result():
    assert "`solve(" in TS.interface_section() and "`undefined`" in TS.interface_section()
    assert "`Solve(" in GO.interface_section() and "error" in GO.interface_section()


def test_typescript_lock_file_names_the_alphametics_workspace():
    lock = (TS.seed / "yarn.lock").read_text(encoding="utf-8")
    assert '"alphametics@workspace:."' in lock
    assert "split-second-stopwatch" not in lock


def test_go_metadata_records_the_appended_instructions():
    assert "instructions.append.md" in GO.changes()


@pytest.mark.slow
@pytest.mark.parametrize("pack, old, new", [
    (TS, "solve(puzzle: string)", "solve(puzzle: number)"),
    (GO, "Solve(puzzle string)", "Solve(puzzle string, _ int)"),
], ids=str)
def test_changed_stub_signature_fails_the_reference_compile(pack, old, new, pack_images,
                                                            tmp_path):
    changed = pack.gold().replace(old, new)
    assert changed != pack.gold()
    reward = verify(pack, pack_images(pack), tmp_path, {pack.stub: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0
