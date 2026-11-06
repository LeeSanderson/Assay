"""The two-bucket task packs, rung 5 of the difficulty ladder (issue #75):
`tasks/typescript/two-bucket/` (a class) and `tasks/go/two-bucket/` (one
function). What is specific to them; tests/test_task_packs.py gives them the
checks that every pack shares."""

import pytest

from tests.task_packs import packs, verify

TS, GO = packs("two-bucket")["typescript"], packs("two-bucket")["go"]


def test_source_instructions_end_with_their_link_reference():
    for pack in (TS, GO):
        prose = pack.instruction().split("\n## Interface\n")[0]
        assert prose.rstrip().endswith("[fullstack]: https://www.fullstackacademy.com/"), pack


def test_typescript_interface_states_the_class_api():
    section = TS.interface_section()
    assert "new TwoBucket(" in section
    for name in ("moves()", "goalBucket", "otherBucket"):
        assert f"`{name}" in section, name
    for bucket in ('`"one"`', '`"two"`'):
        assert bucket in section, bucket
    assert "throw" in section


def test_typescript_metadata_records_the_constructor_and_the_public_moves():
    # The source constructor took no parameter, and the gold solution's
    # moves() was private, so neither type-checked against the reference tests.
    changes = TS.changes()
    assert "constructor" in changes and "proof.ci.ts" in changes and "public moves" in changes


def test_go_interface_states_the_function_api():
    section = GO.interface_section()
    assert "Solve(" in section
    for bucket in ('`"one"`', '`"two"`'):
        assert bucket in section, bucket
    assert "error" in section


def test_go_metadata_records_the_appended_instructions():
    meta = GO.task_toml()["metadata"]
    assert meta["source_dir"] == "exercises/practice/two-bucket"
    assert len(meta["pack_paths"]) == len(meta["copied_paths"])
    assert "instructions.append.md" in GO.changes()


@pytest.mark.slow
def test_typescript_untouched_stub_fails_some_of_the_reference_tests(pack_images, tmp_path):
    # A Go stub panics, which ends the run after the first case.
    reward = verify(TS, pack_images(TS), tmp_path)
    assert reward["reference_total"] == TS.reference_count
    assert reward["reference_passed"] < TS.reference_count
