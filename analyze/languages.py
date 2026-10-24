"""Language rules are data: one table keyed by task-pack language.

The key is the <language> folder of tasks/<language>/<slug>. The task packs'
test.sh removes the same test-file class in the outcome pass (its one
TEST_FILE_PATTERNS line); tests/test_test_file_patterns.py keeps the two in step
(PRD section 5, "Test-first order" and "The cross-check").
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
    # Commands that make a Bash call a test run (for the agent-run cross-check),
    # matched word for word against the start of each simple command.
    test_runs: tuple[str, ...]
    # A test run is partial (selects a subset of the tests) when an argument
    # after the pattern is one of these flags (as --flag, --flag value or
    # --flag=value), or, with positional_selects, any argument that is not a flag.
    selecting_flags: tuple[str, ...]
    positional_selects: bool
    # Flags that take their value as the next argument, so that value is not
    # read as a positional argument.
    value_flags: tuple[str, ...]
    # The test framework's summary in a test run's output, as regular
    # expressions (searched line by line, re.MULTILINE). The run is red when
    # a red pattern matches; otherwise green when a green pattern matches;
    # otherwise the output has no summary.
    red_summaries: tuple[str, ...]
    green_summaries: tuple[str, ...]
    # Commands that run a script; running a file the agent wrote is an ad-hoc
    # run (not a test run, so not in the cross-check).
    script_runners: tuple[str, ...]


LANGUAGES: dict[str, LanguageRules] = {
    "typescript": LanguageRules(
        test_files=("*.test.ts", "*.spec.ts"),
        implementation_files=("*.ts",),
        not_implementation=("*.config.*",),
        # The task pack runs jest through Yarn (PnP); test:implementation is
        # its package.json script that runs jest.
        test_runs=(
            "jest", "npx jest", "npm test", "npm run test", "yarn test", "pnpm test",
            "yarn jest", "corepack yarn jest", "corepack yarn test",
            "yarn test:implementation", "corepack yarn test:implementation",
            "npm run test:implementation",
        ),
        selecting_flags=(
            "-t", "--testNamePattern", "--testPathPattern", "--testPathPatterns",
            "--findRelatedTests", "-o", "--onlyChanged", "-f", "--onlyFailures",
            "--changedSince", "--lastCommit", "--selectProjects",
        ),
        positional_selects=True,  # jest <file or pattern>
        value_flags=(
            "-c", "--config", "--testTimeout", "-w", "--maxWorkers", "--reporters",
            "--outputFile", "--rootDir", "--roots", "--testMatch", "--testRegex",
            "--coverageDirectory", "--cacheDirectory", "--seed", "--shard",
        ),
        red_summaries=(
            r"^Tests:.*\b\d+ failed\b",
            r"^Test Suites:.*\b\d+ failed\b",
            r"Test suite failed to run",
        ),
        green_summaries=(r"^Tests:.*\b\d+ passed\b",),
        script_runners=("tsx", "npx tsx", "ts-node", "npx ts-node", "node"),
    ),
    "go": LanguageRules(
        test_files=("*_test.go",),
        implementation_files=("*.go",),
        not_implementation=(),
        test_runs=("go test",),
        selecting_flags=("-run", "--run", "-skip", "--skip"),
        positional_selects=False,  # go test <packages> runs all tests of each package
        value_flags=(),
        # go test prints one line per package: "ok", "FAIL" or "?" (no test
        # files). Any FAIL line (--- FAIL for a test, FAIL for a package) or
        # build failure ([build failed], or a "# <package>" compile-error
        # header) is red first, so green means every package line that ran
        # tests is ok.
        red_summaries=(
            r"^\s*--- FAIL", r"^FAIL\b", r"\[build failed\]", r"^# \S+",
        ),
        green_summaries=(r"^ok\b",),
        script_runners=("go run",),
    ),
}


def is_test_file(language: str, path: str) -> bool:
    """Whether a file's name matches the language's test-file class, wherever the file is."""
    name = PurePosixPath(path).name
    return any(fnmatchcase(name, p) for p in LANGUAGES[language].test_files)


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
