"""Each task pack's test.sh removes and runs the same test-file class that the
analyzer classifies (analyze/languages.py), so the two cannot drift."""

import shlex
from pathlib import Path

import pytest

from analyze.languages import LANGUAGES

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER = "TEST_FILE_PATTERNS="


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_the_pack_test_sh_has_one_pattern_line_equal_to_the_analyzer_class(language):
    rules = LANGUAGES[language]
    packs = sorted((REPO_ROOT / "tasks" / language).glob("*/tests/test.sh"))
    assert packs
    for test_sh in packs:
        code = [line for line in test_sh.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")]
        (line,) = [l for l in code if l.startswith(MARKER)]
        patterns = shlex.split(line.removeprefix(MARKER).strip().strip("()"))
        assert tuple(patterns) == rules.test_files, test_sh
        # No other line of code names a pattern, so this line is the only one to change.
        others = [l for l in code if l is not line and any(p in l for p in rules.test_files)]
        assert others == [], test_sh
