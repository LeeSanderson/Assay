"""The committed task packs, as `Pack` values, and the helpers that the pack
tests share: building a pack's image, running its `tests/test.sh` on a
prepared repository, and running it through Harbor.

tests/test_task_packs.py gives every pack in PACKS the same checks; each
rung's own module states only what is specific to its packs.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_SLUG = "split-second-stopwatch"  # rung 1: the pack the others follow
REWARD_KEYS = {
    "reward", "reference_compiles", "reference_passed", "reference_total",
    "agent_tests_compile", "agent_tests_passed", "agent_tests_total",
}
TS_TOOLCHAIN = ("package.json", "yarn.lock", ".yarnrc.yml", "tsconfig.json", "jest.config.cjs",
                "babel.config.cjs", "eslint.config.mjs")
BASE_IMAGE = {"typescript": r"node:\d+[\d.]*-bookworm@sha256:[0-9a-f]{64}",
              "go": r"golang:[\d.]+-bookworm@sha256:[0-9a-f]{64}"}
SOURCE_REPO = {"typescript": "https://github.com/exercism/typescript",
               "go": "https://github.com/exercism/go"}


@dataclass(frozen=True)
class Pack:
    """One task pack: tasks/<language>/<slug>."""

    language: str
    slug: str
    reference_count: int  # the reference cases that the gold solution passes
    signatures: tuple[str, ...]  # the exported signatures of the source stub
    opening: str  # the first line of the source instructions

    def __str__(self) -> str:
        return f"{self.language}-{self.slug}"

    @property
    def path(self) -> Path:
        return REPO_ROOT / "tasks" / self.language / self.slug

    @property
    def seed(self) -> Path:
        return self.path / "environment" / "seed"

    @property
    def model(self) -> Path:
        """The rung-1 pack of the same language."""
        return REPO_ROOT / "tasks" / self.language / MODEL_SLUG

    @property
    def stub(self) -> str:
        return f"{self.slug}.ts" if self.language == "typescript" \
            else f"{self.slug.replace('-', '_')}.go"

    @property
    def go_package(self) -> str:
        return self.slug.replace("-", "")

    @property
    def footer(self) -> str:
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

    def stub_text(self) -> str:
        return (self.seed / self.stub).read_text(encoding="utf-8")

    def gold(self) -> str:
        name = "proof.ci.ts" if self.language == "typescript" else "example.go"
        return (self.path / "solution" / name).read_text(encoding="utf-8")

    def reference_tests(self) -> list[str]:
        """The names of the reference test files."""
        if self.language == "typescript":
            return sorted(p.name for p in (self.path / "tests").iterdir()
                          if p.name.endswith(".test.ts"))
        return sorted(p.name for p in (self.path / "tests" / "reference").iterdir())

    def agent_test_not_compiling(self) -> tuple[str, str]:
        """(name, content) of an agent test file that runs under the
        language's test runner, but does not compile under the verifier."""
        if self.language == "typescript":
            return f"{self.slug}.test.ts", (
                "import { expect, it } from '@jest/globals'\n\n"
                "it('does not type-check', () => {\n"
                "  const count: number = 'one'\n"
                "  expect(count).toBe('one')\n"
                "})\n")
        return f"{self.stub[:-3]}_test.go", (
            f"package {self.go_package}\n\nimport \"testing\"\n\n"
            "func TestAgentDoesNotCompile(t *testing.T) {\n\tundefinedHelper()\n}\n")


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


def packs(slug: str) -> dict[str, Pack]:
    """The two packs of one rung, by language."""
    return {p.language: p for p in PACKS if p.slug == slug}


def stub_signatures(pack: Pack) -> list[str]:
    """The declarations of the pack's seed stub, in order."""
    text = pack.stub_text()
    if pack.language == "go":
        return re.findall(r"^(func .*?)\s*\{", text, re.MULTILINE)
    return [line.strip() for line in text.splitlines()
            if re.match(r"\s*(export |public |constructor\(|get |\w+\([^)]*\)\s*\{$)", line)]


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


def verify(pack: Pack, image: str, tmp_path: Path, files: dict[str, str] | None = None) -> dict:
    """Write `files` over the seed repository in /app, run the pack's
    tests/test.sh with no network, and return its reward.json."""
    result = run_in_image(
        pack, image, "bash /tests/test.sh >/dev/null 2>&1; cat /logs/verifier/reward.json",
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
