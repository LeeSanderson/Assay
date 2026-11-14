"""The committed task packs, as `Pack` values, and the helpers that the pack
tests share: building a pack's image, running its `tests/test.sh` on a
prepared repository, and running it through Harbor.

tests/test_task_packs.py gives every pack in PACKS the same checks; each
rung's own module states only what is specific to its packs. PACKS holds the
Exercism packs of the difficulty ladder and the purpose-written packs of the
codebase ladder (CODEBASE_PACKS; ADR 0006), whose two languages the parity
helpers below compare.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

from analyze.languages import LANGUAGES

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_SLUG = "split-second-stopwatch"  # rung 1: the pack the others follow
REWARD_KEYS = {
    "reward", "reference_compiles", "reference_passed", "reference_total",
    "agent_tests_compile", "agent_tests_passed", "agent_tests_total",
    "seed_suite_passed", "seed_suite_total",  # the codebase ladder's; 0 with no seed suite
}
TS_TOOLCHAIN = ("package.json", "yarn.lock", ".yarnrc.yml", "tsconfig.json", "jest.config.cjs",
                "babel.config.cjs", "eslint.config.mjs")
BASE_IMAGE = {"typescript": r"node:\d+[\d.]*-bookworm@sha256:[0-9a-f]{64}",
              "go": r"golang:[\d.]+-bookworm@sha256:[0-9a-f]{64}"}
SOURCE_REPO = {"typescript": "https://github.com/exercism/typescript",
               "go": "https://github.com/exercism/go"}
# The footer of every purpose-written pack (PRD section 20, "The pack recipe").
CODEBASE_FOOTER = ("Add this feature to the repository. Keep the existing behavior, and the "
                   "existing exported names and signatures, as they are. Tests that you cannot "
                   "see will check your solution.\n")
# The two dials of the codebase ladder (PRD section 20, "The rungs").
SEED_SIZES = ("stub", "small", "medium")
# The size ranges of a codebase seed (PRD section 20, "The domain"): lines of
# production code (non-blank), production files and seed-suite tests, each
# (least, most).
SEED_SIZE_RANGES = {
    "small": {"lines": (600, 1000), "files": (6, 10), "tests": (40, 80)},
    "medium": {"lines": (4000, 6000), "files": (30, 50), "tests": (200, 400)},
}
FEATURE_SIZES = ("one function", "M", "X")


# --- The two languages of the task packs ---------------------------------------

# A TypeScript export, and a Go type, constant or variable and a Go function, at
# the start of a line: the exported declarations of a source file.
TS_EXPORT = re.compile(r"^export (class|interface|type|function|const|enum) (\w+)", re.MULTILINE)
GO_DECLARATION = re.compile(r"^(?:type|var|const) ([A-Z]\w*)[\s\[]", re.MULTILINE)
GO_FUNC = re.compile(r"^func ([A-Z]\w*)[\[(]", re.MULTILINE)
_GO_METHOD = re.compile(r"^func \(\w+ \*?(\w+)\) ([A-Z]\w*)\(")
# A member of a TypeScript class, interface or object constant, at the first
# indent (two spaces; a deeper line is in a method body); a Go field, or a
# method of an interface, at one tab.
_TS_MEMBER = re.compile(r"  (?:public |readonly |static )*(\w+)\??[:(<]")
_GO_MEMBER = re.compile(r"\t([A-Z]\w*)[\s(]")


def _ts_exported_names(text: str) -> set[str]:
    names: set[str] = set()
    block = ""  # the class, interface or object constant whose body the line is in
    for line in text.splitlines():
        if line.startswith("}"):
            block = ""
        elif m := TS_EXPORT.match(line):
            names.add(m.group(2))
            # A function's body holds no members.
            opens = line.rstrip().endswith("{") and m.group(1) != "function"
            block = m.group(2) if opens else ""
        elif block and (m := _TS_MEMBER.match(line)):
            if m.group(1) != "constructor" and not line.lstrip().startswith("private"):
                names.add(f"{block}.{m.group(1)}")
    return names


def _go_exported_names(text: str) -> set[str]:
    names: set[str] = set()
    block = ""  # the type (or variable) whose body the line is in
    for line in text.splitlines():
        if line.startswith("}"):
            block = ""
        elif m := GO_DECLARATION.match(line):
            names.add(m.group(1))
            block = m.group(1) if line.rstrip().endswith("{") else ""
        elif m := _GO_METHOD.match(line):
            names.add(f"{m.group(1)}.{m.group(2)}")
        elif m := GO_FUNC.match(line):
            names.add(m.group(1))
        elif block and (m := _GO_MEMBER.match(line)):
            names.add(f"{block}.{m.group(1)}")
    return names


# A test case of a purpose-written pack is an `it` or `describe` in TypeScript
# and a `t.Run` in Go: the Go tests nest t.Run as the TypeScript tests nest
# describe and it, with the same names (PRD section 20, check 4).
_TS_CASE = re.compile(r"\b(?:describe|it)\(\s*'([^']*)'")
_GO_CASE = re.compile(r"\bt\.Run\(\s*\"([^\"]*)\"")


def _ts_leaf_cases(text: str) -> int:
    """A TypeScript test file's `it` cases."""
    return len(re.findall(r"\bit\(\s*'", text))


_GO_TEST_FUNC = re.compile(r"^func Test\w*\(", re.MULTILINE)


def _go_leaf_cases(text: str) -> int:
    """A Go test file's top-level tests and `t.Run` cases whose function
    holds no `t.Run` (a `describe` group is a t.Run that holds others), as
    go test reports them."""
    leaves = 0
    for match in (*_GO_TEST_FUNC.finditer(text), *_GO_CASE.finditer(text)):
        start = text.index("{", match.end())
        depth, end = 0, start
        for end in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            if depth == 0:
                break
        leaves += not _GO_CASE.search(text[start:end])
    return leaves


def _ts_signatures(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()
            if re.match(r"\s*(export |public |constructor\(|get |\w+\([^)]*\)\s*\{$)", line)]


def _go_signatures(text: str) -> list[str]:
    return re.findall(r"^(func .*?)\s*\{", text, re.MULTILINE)


def _ts_not_compiling(slug: str, stem: str, package: str) -> tuple[str, str]:
    return f"{slug}.test.ts", (
        "import { expect, it } from '@jest/globals'\n\n"
        "it('does not type-check', () => {\n"
        "  const count: number = 'one'\n"
        "  expect(count).toBe('one')\n"
        "})\n")


def _go_not_compiling(slug: str, stem: str, package: str) -> tuple[str, str]:
    return f"{stem}_test.go", (
        f"package {package}\n\nimport \"testing\"\n\n"
        "func TestAgentDoesNotCompile(t *testing.T) {\n\tundefinedHelper()\n}\n")


@dataclass(frozen=True)
class PackLanguage:
    """How the task packs of one language lay out and read their files."""

    source_suffix: str
    test_suffix: str
    word_separator: str  # between the words of a file name that comes from a slug
    toolchain: tuple[str, ...]  # the seed's toolchain files
    gold: str  # the gold solution of an Exercism pack, in solution/
    reference_folder: str  # the folder of the reference tests, in tests/
    case: re.Pattern[str]  # a test case, with its name
    leaf_cases: Callable[[str], int]  # a test file's cases that the verifier counts
    exported_names: Callable[[str], set[str]]  # as written, before _exported_names
    signatures: Callable[[str], list[str]]  # the declarations of a stub
    # (slug, stem of the feature file, Go package) -> (name, content) of an
    # agent test file that the test runner runs but the verifier cannot compile.
    not_compiling: Callable[[str, str, str], tuple[str, str]]

    def file_name(self, base: str) -> str:
        """The source file for a base name, such as a slug."""
        return base.replace("-", self.word_separator) + self.source_suffix


PACK_LANGUAGES: dict[str, PackLanguage] = {
    "typescript": PackLanguage(
        ".ts", ".test.ts", "-", TS_TOOLCHAIN, "proof.ci.ts", "", _TS_CASE, _ts_leaf_cases,
        _ts_exported_names, _ts_signatures, _ts_not_compiling),
    "go": PackLanguage(
        ".go", "_test.go", "_", ("go.mod",), "example.go", "reference", _GO_CASE,
        _go_leaf_cases, _go_exported_names, _go_signatures, _go_not_compiling),
}
# How the seed holds the feature of a pack (Pack.feature_in_seed).
FeatureInSeed = Literal["stub", "absent"]


@dataclass(frozen=True)
class Pack:
    """One task pack: tasks/<language>/<slug>."""

    language: str
    slug: str
    reference_count: int  # the reference cases that the gold solution passes
    signatures: tuple[str, ...]  # the exported signatures of the source stub
    opening: str  # the first line of the source instructions
    root: Path = REPO_ROOT / "tasks"  # the test-fixture packs are in tests/fixtures/packs
    # A purpose-written pack of the codebase ladder (ADR 0006) names the file
    # of its feature (without the extension) and its Go module; an Exercism
    # pack takes both from its slug.
    feature: str = ""
    module: str = ""
    # How the seed holds the feature: as a stub that keeps its signatures, or
    # not at all (rungs D and E), when the feature adds its file and the
    # feature tests do not compile on the seed.
    feature_in_seed: FeatureInSeed = "stub"

    @property
    def purpose_written(self) -> bool:
        return bool(self.feature)

    @property
    def has_stub(self) -> bool:
        return self.feature_in_seed == "stub"

    @property
    def lang(self) -> PackLanguage:
        return PACK_LANGUAGES[self.language]

    def __str__(self) -> str:
        return f"{self.language}-{self.slug}"

    @property
    def path(self) -> Path:
        return self.root / self.language / self.slug

    @property
    def seed(self) -> Path:
        return self.path / "environment" / "seed"

    @property
    def model(self) -> Path:
        """The rung-1 pack of the same language."""
        return REPO_ROOT / "tasks" / self.language / MODEL_SLUG

    @property
    def feature_file(self) -> str:
        """The file of the feature: the stub, or the file that the feature adds."""
        return self.lang.file_name(self.feature or self.slug)

    @property
    def stub(self) -> str:
        assert self.has_stub, f"{self} has no stub"
        return self.feature_file

    @property
    def go_package(self) -> str:
        return self.module or self.slug.replace("-", "")

    @property
    def footer(self) -> str:
        if self.purpose_written:
            return CODEBASE_FOOTER
        return (f"Implement the solution in `{self.stub}`. Keep the exported names and "
                "signatures as they are. Tests that you cannot see will check your solution.\n")

    @property
    def exercise(self) -> str:
        """The source folder in the Exercism track."""
        return f"exercises/practice/{self.slug}/"

    def task_toml(self) -> dict:
        return tomllib.loads((self.path / "task.toml").read_text(encoding="utf-8"))

    def model_task_toml(self) -> dict:
        return tomllib.loads((self.model / "task.toml").read_text(encoding="utf-8"))

    def changes(self) -> str:
        """The pack's mechanical changes, as one string."""
        return " ".join(self.task_toml()["metadata"]["mechanical_changes"])

    def instruction(self) -> str:
        return (self.path / "instruction.md").read_text(encoding="utf-8")

    def specification(self) -> str:
        """The instruction before its Interface section."""
        return self.instruction().partition("\n## Interface\n")[0]

    def interface_section(self) -> str:
        """The instruction's Interface section: after the source instructions,
        before the footer."""
        _, heading, rest = self.instruction().partition("\n## Interface\n")
        assert heading, "instruction.md has no '## Interface' section"
        section, footer, _ = rest.partition(self.footer)
        assert footer, "the Interface section must come before the footer"
        return section

    def seed_files(self) -> list[str]:
        return sorted(p.relative_to(self.seed).as_posix()
                      for p in self.seed.rglob("*") if p.is_file())

    def seed_test_files(self) -> list[str]:
        """The seed suite: the seed files in the language's test-file class."""
        patterns = LANGUAGES[self.language].test_files
        return [f for f in self.seed_files()
                if any(fnmatch(f.rsplit("/", 1)[-1], p) for p in patterns)]

    def production_files(self) -> list[str]:
        """The seed's production code: its files but the tests and the toolchain."""
        tests = set(self.seed_test_files())
        return [f for f in self.seed_files() if f not in tests and f not in self.lang.toolchain]

    def production_lines(self) -> int:
        """The non-blank lines of the seed's production code."""
        return sum(1 for f in self.production_files()
                   for line in (self.seed / f).read_text(encoding="utf-8").splitlines()
                   if line.strip())

    @property
    def seed_suite(self) -> Path:
        """The withheld copy of the seed suite, which the verifier restores
        (PRD section 20, "The pack recipe"). Absent when the suite is empty."""
        return self.path / "tests" / "seed-suite"

    def seed_suite_copy(self) -> list[str]:
        return sorted(p.relative_to(self.seed_suite).as_posix()
                      for p in self.seed_suite.rglob("*") if p.is_file())

    def stub_text(self) -> str:
        return (self.seed / self.stub).read_text(encoding="utf-8")

    def gold(self) -> str:
        """The gold solution of an Exercism pack's stub."""
        return (self.path / "solution" / self.lang.gold).read_text(encoding="utf-8")

    def gold_files(self) -> dict[str, str]:
        """The gold solution, as the files (relative to /app) that it writes.
        A purpose-written pack's solution/ holds them at their seed paths,
        beside solve.sh."""
        if not self.purpose_written:
            return {self.stub: self.gold()}
        solution = self.path / "solution"
        return {p.relative_to(solution).as_posix(): p.read_text(encoding="utf-8")
                for p in sorted(solution.rglob("*")) if p.is_file() and p.name != "solve.sh"}

    @property
    def reference_folder(self) -> Path:
        return self.path / "tests" / self.lang.reference_folder

    def reference_test_texts(self) -> list[str]:
        return [(self.reference_folder / name).read_text(encoding="utf-8")
                for name in self.reference_tests()]

    def reference_tests(self) -> list[str]:
        """The names of the reference test files."""
        return sorted(p.name for p in self.reference_folder.iterdir()
                      if p.name.endswith(self.lang.test_suffix))

    def agent_test_not_compiling(self) -> tuple[str, str]:
        """(name, content) of an agent test file that runs under the
        language's test runner, but does not compile under the verifier."""
        stem = self.feature_file.removesuffix(self.lang.source_suffix)
        return self.lang.not_compiling(self.slug, stem, self.go_package)


# --- The codebase ladder: parity between the two languages of a rung ----------

def case_names(language: str, texts: list[str]) -> list[str]:
    """The test-case names in the given test files, in order."""
    return [name for text in texts for name in PACK_LANGUAGES[language].case.findall(text)]


def reference_case_names(pack: Pack) -> list[str]:
    return case_names(pack.language, pack.reference_test_texts())


def seed_suite_case_names(pack: Pack) -> list[str]:
    return case_names(pack.language, [(pack.seed / name).read_text(encoding="utf-8")
                                      for name in pack.seed_test_files()])


def seed_suite_tests(pack: Pack) -> int:
    """The tests of the seed suite, as the verifier counts them: its leaf
    cases (seed_suite_total of the gold solution)."""
    return sum(pack.lang.leaf_cases((pack.seed / name).read_text(encoding="utf-8"))
               for name in pack.seed_test_files())


def _design_file(language: str, name: str) -> str:
    """A seed file's path with the language taken out: `a/b-c.test.ts` and
    `a/b_c_test.go` are both `a/b_c test`."""
    lang = PACK_LANGUAGES[language]
    name = name.removesuffix(lang.source_suffix)
    test = lang.test_suffix.removesuffix(lang.source_suffix)
    if name.endswith(test):
        name = name.removesuffix(test) + " test"
    return name.replace("-", "_")


def _exported_names(language: str, text: str) -> set[str]:
    """The exported types, functions, constants, methods and fields of a
    source file, lower-cased and without underscores, so that `unitPrice` and
    `UnitPrice`, and `STANDARD_TAX_RATE` and `StandardTaxRate`, match. A Go
    `New<Type>` function is the constructor of the TypeScript class <Type>,
    and a TypeScript `new<Type>` function the Go `New<Type>`, so both are left
    out."""
    names = PACK_LANGUAGES[language].exported_names(text)
    types = {n for n in names if "." not in n}
    return {n.lower().replace("_", "") for n in names
            if not (n[:3].lower() == "new" and n[3:] in types)}


# The exported names that only one language can have (the medium codebase;
# docs/codebase-ladder/medium-codebase.md, "The Go port"). seed_design leaves
# them out.
LANGUAGE_ONLY_NAMES = {
    "typescript": set(),
    "go": {
        # ShopError implements Go's error interface with fields; the
        # TypeScript class inherits its message from Error.
        "shoperror.code", "shoperror.message", "shoperror.error",
        # Go has one name space for types and functions, so the function of
        # each figure of domain/report is named <Figure>Of.
        "salessummaryof", "dailysalesof", "weekdaysalesof", "promotionusageof",
        "customersalesof", "productsalesof", "shippingcostsof",
        # The TypeScript Shop is the inferred return type of createShop; the
        # Go Shop struct names its fields.
        *(f"shop.{field}" for field in (
            "clock", "ids", "payments", "outbox", "events", "catalogue", "inventory",
            "promotions", "customers", "accounts", "checkout", "orders", "shipping",
            "invoicing", "purchasing", "reports")),
    },
}


def seed_design(pack: Pack) -> dict:
    """The seed's design with the language taken out: its files (but the
    toolchain files) and the exported names of its source files."""
    files = [f for f in pack.seed_files() if f not in pack.lang.toolchain]
    tests = set(pack.seed_test_files())
    names: set[str] = set()
    for f in files:
        if f not in tests:
            names |= _exported_names(pack.language, (pack.seed / f).read_text(encoding="utf-8"))
    return {"files": sorted(_design_file(pack.language, f) for f in files),
            "exported": sorted(names - LANGUAGE_ONLY_NAMES[pack.language])}


def base_image(pack_path: Path) -> str:
    dockerfile = (pack_path / "environment" / "Dockerfile").read_text(encoding="utf-8")
    return re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE).group(1)


def _both(slug: str, opening: str, counts: tuple[int, int],
          ts_signatures: tuple[str, ...], go_signatures: tuple[str, ...]) -> list[Pack]:
    return [Pack("typescript", slug, counts[0], ts_signatures, opening),
            Pack("go", slug, counts[1], go_signatures, opening)]


# The exported signatures are those of the source stubs (exercism/typescript
# a24e6ae, exercism/go 74f09b2), except where a pack records a mechanical
# change: the TypeScript wordy and two-bucket stubs gain the parameters that
# the reference tests pass.
PACKS: list[Pack] = [
    *_both("split-second-stopwatch",
           "Your task is to build a stopwatch to keep precise track of lap times.", (29, 29),
           ("export class SplitSecondStopwatch {", "constructor() {",
            "public get state(): unknown {", "public get currentLap(): unknown {",
            "public get total(): unknown {", "public get previousLaps(): unknown[] {",
            "public start(): unknown {", "public stop(): unknown {", "public lap(): unknown {",
            "public reset(): unknown {", "public advanceTime(duration: unknown): unknown {"),
           ("func (sss *SplitSecondStopwatch) Start() error",
            "func (sss *SplitSecondStopwatch) Stop() error",
            "func (sss *SplitSecondStopwatch) Reset() error",
            "func (sss *SplitSecondStopwatch) Lap() error",
            "func (sss *SplitSecondStopwatch) AdvanceTime(by string)",
            "func (sss *SplitSecondStopwatch) State() string",
            "func (sss *SplitSecondStopwatch) CurrentLap() string",
            "func (sss *SplitSecondStopwatch) Total() string",
            "func (sss *SplitSecondStopwatch) PreviousLaps() []string",
            "func NewSplitSecondStopwatch() *SplitSecondStopwatch")),
    *_both("wordy",
           "Parse and evaluate simple math word problems returning the answer as an integer.",
           (27, 27),
           ("export const answer = (question: unknown): unknown => {",),
           ("func Answer(question string) (int, bool)",)),
    *_both("poker", "Pick the best hand(s) from a list of poker hands.",
           (37, 47),  # Go: 37 valid hands and 10 invalid hands
           ("export function bestHands(hands: string[]): string[] {",),
           ("func BestHand(hands []string) ([]string, error)",)),
    *_both("bowling", "Score a bowling game.", (31, 31),
           ("export class Bowling {", "public roll(pins: unknown): unknown {",
            "public score(): unknown {"),
           ("func NewGame() *Game", "func (g *Game) Roll(pins int) error",
            "func (g *Game) Score() (int, error)")),
    *_both("two-bucket",
           "Given two buckets of different size and which bucket to fill first, determine how "
           "many actions are required to measure an exact number of liters by strategically "
           "transferring fluid between the buckets.",
           (11, 15),  # Go: 11 Solve cases and 4 error cases
           ("export class TwoBucket {",
            "constructor(buckOne: unknown, buckTwo: unknown, goal: unknown, "
            "starterBuck: unknown) {",
            "moves() {", "get goalBucket() {", "get otherBucket() {"),
           ("func Solve(sizeBucketOne, sizeBucketTwo, goalAmount int, startBucket string) "
            "(string, int, int, error)",)),
    *_both("alphametics", "Given an alphametics puzzle, find the correct solution.", (8, 8),
           ("export function solve(puzzle: unknown): unknown {",),
           ("func Solve(puzzle string) (map[string]int, error)",)),
]


# The purpose-written packs of the codebase ladder (PRD section 20; ADR 0006).
# The signatures are those of the stub, which the pack authors.
# Rungs B and C share the stub of the promotions engine: on rung C it sits in
# the small codebase, beside the checkout that it connects to.
_PROMOTIONS = "Build the promotions engine of a shop."
_PROMOTIONS_IN_CODEBASE = ("Build the promotions engine of the shop in this repository, and "
                           "connect it to the checkout.")
_RETURNS = "Add partial returns and refunds to the shop in this repository."
_PROMOTIONS_TS = (
    "export type PromotionKind = 'percentage' | 'fixed' | 'buy-x-get-y' | 'bundle'",
    "export interface Line {", "export interface Promotion {", "export interface Coupon {",
    "export interface Discount {", "export interface Quote {",
    "export class PromotionEngine {",
    "public addPromotion(promotion: Promotion): void {",
    "public addCoupon(coupon: Coupon): void {",
    "public quote(lines: Line[], coupons: string[], today: string): Quote {",
    "public redeem(lines: Line[], coupons: string[], today: string): Quote {")
_PROMOTIONS_GO = (
    "func NewPromotionEngine() *PromotionEngine",
    "func (e *PromotionEngine) AddPromotion(promotion Promotion) error",
    "func (e *PromotionEngine) AddCoupon(coupon Coupon) error",
    "func (e *PromotionEngine) Quote(lines []Line, coupons []string, today string) "
    "(Quote, error)",
    "func (e *PromotionEngine) Redeem(lines []Line, coupons []string, today string) "
    "(Quote, error)")


def _codebase_rung(slug: str, feature_tests: int, opening: str, feature: str,
                   signatures: tuple[tuple[str, ...], tuple[str, ...]] = ((), ()),
                   feature_in_seed: FeatureInSeed = "stub") -> list[Pack]:
    """The two purpose-written packs of one rung, in the Go module `shop`.
    `signatures` are the TypeScript stub's, then the Go stub's."""
    return [Pack(language, slug, feature_tests, sigs, opening, feature=feature, module="shop",
                 feature_in_seed=feature_in_seed)
            for language, sigs in zip(("typescript", "go"), signatures)]


CODEBASE_PACKS: list[Pack] = [
    *_codebase_rung("shop-promotions-stub", 48, _PROMOTIONS, "promotions",
                    (_PROMOTIONS_TS, _PROMOTIONS_GO)),
    # Rung C: rung B's 48 feature tests and 13 of the checkout integration.
    *_codebase_rung("shop-promotions-small", 61, _PROMOTIONS_IN_CODEBASE, "promotions",
                    (_PROMOTIONS_TS, _PROMOTIONS_GO)),
    # Rung D: partial returns and refunds (X), whose file `returns` the feature
    # adds to rung C's seed with rung C's gold solution. Rung E reuses its
    # feature tests.
    *_codebase_rung("shop-returns-small", 38, _RETURNS, "returns", feature_in_seed="absent"),
    # Rung E: X again, with rung D's specification, Interface section and
    # feature tests, in the medium codebase (issues #85 and #86).
    # tests/test_medium_codebase.py checks the seed.
    *_codebase_rung("shop-returns-medium", 38, _RETURNS, "returns", feature_in_seed="absent"),
]
PACKS += CODEBASE_PACKS
EXERCISM_PACKS = [p for p in PACKS if not p.purpose_written]
PACKS_WITH_A_STUB = [p for p in PACKS if p.has_stub]
# The slugs of the purpose-written rungs, sorted by name; the codebase-ladder
# summary (experiments/codebase-ladder/summary.py, RUNGS) holds their ladder order.
CODEBASE_SLUGS = sorted({p.slug for p in CODEBASE_PACKS})
# The test-fixture packs of the verifier (issue #80; tests/test_seed_suite_verifier.py):
# `tally`, a tiny codebase with a seed suite and 3 feature tests.
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "packs"
FIXTURE_PACKS = [Pack(language, "tally", 3, (), "", root=FIXTURES)
                 for language in ("typescript", "go")]


def packs(slug: str) -> dict[str, Pack]:
    """The two packs of one rung, by language."""
    return {p.language: p for p in PACKS if p.slug == slug}


def stub_signatures(pack: Pack) -> list[str]:
    """The declarations of the pack's seed stub, in order."""
    return pack.lang.signatures(pack.stub_text())


# --- Docker and Harbor ----------------------------------------------------------


def docker(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def build_image(pack: Pack) -> str:
    tag = f"assay-test-{pack}:{uuid.uuid4().hex[:8]}"
    build = docker("build", "-q", "-t", tag, str(pack.path / "environment"), timeout=1200)
    assert build.returncode == 0, build.stderr
    return tag


def run_in_image(pack: Pack, image: str, script: str, files: dict[str, str] | None = None,
                 tmp_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run a bash script in a fresh container of the pack image, with no
    network and the pack's `tests/` at /tests, as Harbor uploads it. `files`
    (paths relative to /app) are written over /app first."""
    mounts = ["-v", f"{pack.path / 'tests'}:/tests:ro"]
    prelude = ""
    if files:
        overlay = tmp_path / "overlay"
        for rel, content in files.items():
            target = overlay / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        mounts += ["-v", f"{overlay}:/overlay:ro"]
        prelude = "cp -r /overlay/. /app/ && "
    return docker("run", "--rm", "--network", "none", *mounts, image, "bash", "-c",
                  prelude + script)


def checked_rewards(rewards: dict) -> dict:
    assert set(rewards) == REWARD_KEYS
    assert all(type(v) in (int, float) for v in rewards.values())
    return rewards


def verify(pack: Pack, image: str, tmp_path: Path, files: dict[str, str] | None = None,
           delete: tuple[str, ...] = ()) -> dict:
    """Write `files` over the seed repository in /app and delete the `delete`
    paths from it, run the pack's tests/test.sh with no network, and return
    its reward.json."""
    removal = "".join(f"rm /app/{path} && " for path in delete)
    result = run_in_image(
        pack, image,
        removal + "bash /tests/test.sh >/dev/null 2>&1; cat /logs/verifier/reward.json",
        files, tmp_path)
    assert result.returncode == 0, result.stderr
    return checked_rewards(json.loads(result.stdout))


def harbor_rewards(pack: Pack, agent: str, tmp_path: Path) -> dict:
    """Run the pack through Harbor with `agent` and return the trial's rewards."""
    job = f"{pack}-{agent}"
    result = subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(pack.path), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800)
    assert result.returncode == 0, result.stdout + result.stderr
    (trial,) = [p for p in (tmp_path / job).iterdir() if p.is_dir()]
    trial_result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    return checked_rewards(trial_result["verifier_result"]["rewards"])
