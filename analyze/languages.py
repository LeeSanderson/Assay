"""Language rules are data: one table keyed by task-pack language.

The key is the <language> folder of tasks/<language>/<slug>. The task packs'
test.sh removes the same test-file class in the outcome pass, so keep the two
in step (PRD section 5, "Test-first order" and "The cross-check").
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

TEST = "test"
IMPLEMENTATION = "implementation"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class LanguageRules:
    # Glob patterns, matched against the file name (not the folder).
    test_files: tuple[str, ...]
    implementation_files: tuple[str, ...]
    not_implementation: tuple[str, ...]  # never an implementation file, e.g. config
    # Commands that make a Bash call a test run (for the agent-run cross-check).
    test_runs: tuple[str, ...]


LANGUAGES: dict[str, LanguageRules] = {
    "typescript": LanguageRules(
        test_files=("*.test.ts", "*.spec.ts"),
        implementation_files=("*.ts",),
        not_implementation=("*.config.*",),
        test_runs=("jest", "npx jest", "npm test", "npm run test", "yarn test", "pnpm test"),
    ),
    "go": LanguageRules(
        test_files=("*_test.go",),
        implementation_files=("*.go",),
        not_implementation=(),
        test_runs=("go test",),
    ),
}


def classify(language: str, path: str) -> str:
    """The class of a path in the seed repository: TEST, IMPLEMENTATION or NEUTRAL.

    A path outside the seed repository (absolute, or leaving it with ..) is NEUTRAL.
    """
    rules = LANGUAGES[language]
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        return NEUTRAL
    name = pure.name
    if any(fnmatchcase(name, p) for p in rules.test_files):
        return TEST
    if any(fnmatchcase(name, p) for p in rules.not_implementation):
        return NEUTRAL
    if any(fnmatchcase(name, p) for p in rules.implementation_files):
        return IMPLEMENTATION
    return NEUTRAL
