"""The rung-2 `wordy` task packs, TypeScript and Go (issue #72; spec #67):
what is specific to them. tests/test_task_packs.py gives them the checks
that every pack shares."""

import re

from tests.task_packs import packs

TS, GO = packs("wordy")["typescript"], packs("wordy")["go"]


def test_source_instructions_end_before_the_interface():
    for pack in (TS, GO):
        prose = pack.instruction().split("\n## Interface\n")[0]
        assert prose.rstrip().endswith(
            '- Word problems with invalid syntax ("What is 1 plus plus 2?")'), pack


def test_typescript_interface_names_exactly_the_reference_error_messages():
    text = (TS.path / "tests" / "assay-reference.wordy.test.ts").read_text(encoding="utf-8")
    messages = set(re.findall(r"toThrow\(\s*new Error\(\s*'([^']+)'\s*\)\s*\)", text))
    assert messages == {"Unknown operation", "Syntax error"}
    section = TS.interface_section()
    assert set(re.findall(r'`"([^"`]+)"`', section)) >= messages
    assert "`answer(question)`" in section and "number" in section


def test_typescript_stub_takes_the_question_the_reference_tests_pass():
    # The source was `export const answer = () => {`: it took no parameter, so
    # the reference tests did not type-check against it.
    assert "question: unknown" in TS.changes()


def test_go_interface_states_the_answer_and_ok_results():
    section = GO.interface_section()
    assert "`Answer(question string) (int, bool)`" in section
    assert "`true`" in section and "`false`" in section
