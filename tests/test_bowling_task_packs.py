"""The rung 4 task packs, `tasks/typescript/bowling` and `tasks/go/bowling`
(issue #74; PRD §15 "The TDD pack recipe").

The fast tests read the packs' files. The slow tests build each pack image and
run `tests/test.sh` on prepared repositories with no network, as replay does,
and run each pack through Harbor with the `oracle` and do-nothing (`nop`)
agents.
"""

import json
import re
import subprocess
import tomllib
import uuid
from pathlib import Path

import pytest

from analyze.languages import TEST, classify
from tests.test_typescript_task_pack import REWARD_KEYS

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_TEST_COUNT = 31  # both tracks hold the same 31 cases

TS = REPO_ROOT / "tasks" / "typescript" / "bowling"
GO = REPO_ROOT / "tasks" / "go" / "bowling"
PACKS = {"typescript": TS, "go": GO}
STUBS = {"typescript": "bowling.ts", "go": "bowling.go"}
GOLD_FILES = {"typescript": "proof.ci.ts", "go": "example.go"}
SEED_FILES = {
    "typescript": sorted(["bowling.ts", "package.json", "yarn.lock", ".yarnrc.yml",
                          "tsconfig.json", "jest.config.cjs", "babel.config.cjs",
                          "eslint.config.mjs"]),
    "go": ["bowling.go", "go.mod"],
}
SOURCE_REPOS = {"typescript": "https://github.com/exercism/typescript",
                "go": "https://github.com/exercism/go"}
BASE_IMAGES = {"typescript": r"node:\d+[\d.]*-bookworm@sha256:[0-9a-f]{64}",
               "go": r"golang:[\d.]+-bookworm@sha256:[0-9a-f]{64}"}
FOOTERS = {
    language: f"Implement the solution in `{stub}`. Keep the exported names and "
              "signatures as they are. Tests that you cannot see will check your solution.\n"
    for language, stub in STUBS.items()
}
# The error messages that the TypeScript reference tests compare exactly.
TS_ERROR_MESSAGES = {
    "Negative roll is invalid",
    "Pin count exceeds pins on the lane",
    "Score cannot be taken until the end of the game",
    "Cannot roll after game is over",
}

languages = pytest.mark.parametrize("language", list(PACKS))


def _config(language: str) -> dict:
    return tomllib.loads((PACKS[language] / "task.toml").read_text(encoding="utf-8"))


def _seed(language: str) -> Path:
    return PACKS[language] / "environment" / "seed"


def _seed_files(language: str) -> list[str]:
    seed = _seed(language)
    return sorted(p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file())


def _instruction(language: str) -> str:
    return (PACKS[language] / "instruction.md").read_text(encoding="utf-8")


def _interface_section(language: str) -> str:
    text = _instruction(language)
    heading = re.search(r"^## Interface$", text, re.MULTILINE)
    assert heading, "instruction.md has no '## Interface' section"
    footer = text.index(FOOTERS[language].split(".")[0])
    assert heading.start() < footer
    return text[heading.start():footer]


def _gold(language: str) -> str:
    return (PACKS[language] / "solution" / GOLD_FILES[language]).read_text(encoding="utf-8")


# --- The packs' files -------------------------------------------------------


@languages
def test_seed_repository_holds_only_the_stub_and_the_toolchain_files(language):
    assert _seed_files(language) == SEED_FILES[language]
    assert sorted(_config(language)["metadata"]["seed_files"]) == SEED_FILES[language]
    assert not (_seed(language) / ".claude").exists()


@languages
def test_seed_repository_names_no_source(language):
    for path in _seed(language).rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "exercism" not in text, path
            assert "please implement" not in text, path
            assert "remove this line" not in text, path


@languages
def test_instruction_is_the_source_instructions_then_the_interface_then_the_footer(language):
    text = _instruction(language)
    assert text.startswith("# Instructions\n\nScore a bowling game.\n")
    assert text.endswith(FOOTERS[language])
    prose = text[:text.index("\n## Interface\n")]
    assert prose.rstrip().endswith("It returns the total score for that game.")
    assert _interface_section(language)


@languages
def test_instruction_names_no_test_command(language):
    text = _instruction(language).lower()
    for command in ("yarn", "npm", "jest", "npx", "go test"):
        assert command not in text, command


def test_go_instruction_does_not_say_test_before_the_footer():
    text = _instruction("go")
    assert "test" not in text[:text.index("Implement the solution in")].lower()


def test_typescript_interface_gives_each_reference_error_message_exactly():
    reference = (TS / "tests" / "assay-reference.bowling.test.ts").read_text(encoding="utf-8")
    messages = set(re.findall(r"toThrow\(\s*new Error\(\s*'([^']+)'\s*\)\s*\)", reference))
    assert messages == TS_ERROR_MESSAGES
    stated = set(re.findall(r'`"([^"`]+)"`', _interface_section("typescript")))
    assert stated >= messages


def test_typescript_interface_states_the_class_and_its_methods():
    section = _interface_section("typescript")
    for name in ("new Bowling()", "roll(pins", "score()"):
        assert name in section, name


def test_go_interface_states_the_constructor_and_the_error_returns():
    section = _interface_section("go")
    for name in ("NewGame()", "Roll(pins int) error", "Score() (int, error)"):
        assert name in section, name
    assert "non-nil error" in section


def test_typescript_reference_tests_carry_the_prefix_and_no_xit():
    tests = [p.name for p in (TS / "tests").iterdir() if classify("typescript", p.name) == TEST]
    assert tests == ["assay-reference.bowling.test.ts"]
    text = (TS / "tests" / tests[0]).read_text(encoding="utf-8")
    assert not re.search(r"\bx(it|describe)\(", text)
    assert len(re.findall(r"^\s*it\(", text, re.MULTILINE)) == REFERENCE_TEST_COUNT


def test_go_reference_tests_carry_the_prefix():
    names = sorted(p.name for p in (GO / "tests" / "reference").iterdir())
    assert names == ["assay_reference_bowling_test.go", "assay_reference_cases_test.go"]
    cases = (GO / "tests" / "reference" / "assay_reference_cases_test.go").read_text(encoding="utf-8")
    assert cases.count("description:") == REFERENCE_TEST_COUNT


# The exported names and signatures of the source stubs, at `source_commit`.
TS_SOURCE_SIGNATURES = [
    "export class Bowling {",
    "public roll(pins: unknown): unknown {",
    "public score(): unknown {",
]
GO_SOURCE_SIGNATURES = [
    "func NewGame() *Game",
    "func (g *Game) Roll(pins int) error",
    "func (g *Game) Score() (int, error)",
]


def test_typescript_stub_keeps_the_source_signatures():
    text = (_seed("typescript") / "bowling.ts").read_text(encoding="utf-8")
    signatures = [line.strip() for line in text.splitlines()
                  if re.match(r"\s*(export |public |constructor\()", line)]
    assert signatures == TS_SOURCE_SIGNATURES
    assert "'Not implemented'" in text


def test_go_stub_keeps_the_source_signatures_and_declares_game():
    stub = (_seed("go") / "bowling.go").read_text(encoding="utf-8")
    assert stub.startswith("package bowling\n")
    # The source stub leaves `Game` undefined, so it does not build; the pack
    # adds the empty type (a recorded mechanical change).
    assert "type Game struct{}" in stub
    assert re.findall(r"^(func .*?)\s*\{", stub, re.M) == GO_SOURCE_SIGNATURES
    assert 'panic("not implemented")' in stub
    assert (_seed("go") / "go.mod").read_text(encoding="utf-8") == "module bowling\n\ngo 1.27\n"


@languages
def test_metadata_records_the_provenance(language):
    meta = _config(language)["metadata"]
    assert meta["language"] == language
    assert meta["source_repo"] == SOURCE_REPOS[language]
    model = tomllib.loads((REPO_ROOT / "tasks" / language / "split-second-stopwatch"
                           / "task.toml").read_text(encoding="utf-8"))["metadata"]
    assert meta["source_commit"] == model["source_commit"]
    assert meta["red_compile_rule"] == model["red_compile_rule"]
    exercise = "exercises/practice/bowling/"
    assert all(p.startswith(exercise) for p in meta["copied_paths"])
    assert exercise + ".docs/instructions.md" in meta["copied_paths"]
    assert exercise + STUBS[language] in meta["copied_paths"]
    changes = " ".join(meta["mechanical_changes"])
    assert "Interface section" in changes
    assert STUBS[language] in changes
    if language == "typescript":
        assert exercise + "bowling.test.ts" in meta["copied_paths"]
        assert exercise + ".meta/proof.ci.ts" in meta["copied_paths"]
        assert len(meta["copied_to"]) == len(meta["copied_paths"])
        for edited in ("xit", "assay-reference.", "package.json", "tsconfig.json",
                       "babel.config.cjs", "eslint.config.mjs", "yarn.lock",
                       "@babel/preset-env", "typescript-eslint"):
            assert edited in changes, edited
    else:
        assert exercise + "cases_test.go" in meta["copied_paths"]
        assert exercise + ".meta/example.go" in meta["copied_paths"]
        assert len(meta["pack_paths"]) == len(meta["copied_paths"])
        assert "not implemented" in changes
        assert "type Game struct{}" in changes


@languages
def test_image_is_pinned_by_digest_at_the_existing_toolchain(language):
    dockerfile = (PACKS[language] / "environment" / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE).group(1)
    assert re.fullmatch(BASE_IMAGES[language], base)
    assert _config(language)["metadata"]["base_image"] == base
    model = (REPO_ROOT / "tasks" / language / "split-second-stopwatch" / "environment"
             / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM\s+(\S+)", model, re.MULTILINE).group(1) == base


@languages
def test_limits_follow_the_prd(language):
    config = _config(language)
    assert config["agent"]["timeout_sec"] == 1800
    assert config["verifier"]["timeout_sec"] == 600
    assert config["environment"]["cpus"] == 2
    assert config["environment"]["memory_mb"] == 4096


@languages
def test_pack_files_have_lf_line_endings(language):
    for path in PACKS[language].rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


# --- Slow: the pack images and tests/test.sh --------------------------------

AGENT_TESTS_NOT_COMPILING = {
    # Runs under babel-jest, but does not type-check: score() gives a number.
    "typescript": ("bowling.test.ts", """\
import { expect, it } from '@jest/globals'
import { Bowling } from './bowling.ts'

it('scores zero', () => {
  const total: string = new Bowling().score()
  expect(total).toBe('0')
})
"""),
    "go": ("bowling_test.go", """\
package bowling

import "testing"

func TestRoll(t *testing.T) {
	undefinedHelper()
}
"""),
}


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kwargs)


@pytest.fixture(scope="module", params=list(PACKS))
def pack_image(request):
    language = request.param
    tag = f"assay-test-{language}-bowling:{uuid.uuid4().hex[:8]}"
    build = _docker("build", "-q", "-t", tag, str(PACKS[language] / "environment"), timeout=1200)
    assert build.returncode == 0, build.stderr
    yield language, tag
    _docker("image", "rm", "-f", tag)


def _verify(language: str, image: str, tmp_path: Path, files: dict[str, str]) -> dict:
    """Write `files` over /app, run the pack's tests/test.sh, read reward.json."""
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    for rel, content in files.items():
        (overlay / rel).write_text(content, encoding="utf-8", newline="\n")
    result = _docker(
        "run", "--rm", "--network", "none",
        "-v", f"{PACKS[language] / 'tests'}:/tests:ro", "-v", f"{overlay}:/overlay:ro",
        image, "bash", "-c",
        "cp -r /overlay/. /app/ && bash /tests/test.sh >/dev/null 2>&1;"
        " cat /logs/verifier/reward.json",
        timeout=600)
    assert result.returncode == 0, result.stderr
    reward = json.loads(result.stdout)
    assert set(reward) == REWARD_KEYS
    assert all(type(v) in (int, float) for v in reward.values())
    return reward


@pytest.mark.slow
def test_image_holds_the_seed_commit_and_only_the_seed_files(pack_image):
    language, image = pack_image
    result = _docker("run", "--rm", "--network", "none", image, "bash", "-c",
                     "cd /app && git log --format=%s && git ls-files"
                     " && git status --porcelain | wc -l")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.split()
    assert lines[0] == "seed"
    assert sorted(lines[1:-1]) == SEED_FILES[language]
    assert lines[-1] == "0"


@pytest.mark.slow
def test_gold_solution_passes_every_reference_test(pack_image, tmp_path):
    language, image = pack_image
    reward = _verify(language, image, tmp_path, {STUBS[language]: _gold(language)})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == REFERENCE_TEST_COUNT
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_untouched_stub_gives_reward_0_and_the_reference_tests_compile(pack_image, tmp_path):
    language, image = pack_image
    reward = _verify(language, image, tmp_path, {})
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == 0
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_agent_test_that_does_not_compile_leaves_the_outcome_pass_unaffected(pack_image, tmp_path):
    language, image = pack_image
    name, content = AGENT_TESTS_NOT_COMPILING[language]
    reward = _verify(language, image, tmp_path, {STUBS[language]: _gold(language), name: content})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == REFERENCE_TEST_COUNT
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1  # the red-compile rule counts the file


def _harbor_rewards(language: str, agent: str, tmp_path: Path) -> dict:
    job = f"{language}-bowling-{agent}"
    result = subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(PACKS[language]), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (trial,) = [p for p in (tmp_path / job).iterdir() if p.is_dir()]
    trial_result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    return trial_result["verifier_result"]["rewards"]


@pytest.mark.slow
@languages
def test_harbor_oracle_gives_reward_1(language, tmp_path):
    rewards = _harbor_rewards(language, "oracle", tmp_path)
    assert set(rewards) == REWARD_KEYS
    assert rewards["reward"] == 1
    assert rewards["reference_passed"] == rewards["reference_total"] == REFERENCE_TEST_COUNT


@pytest.mark.slow
@languages
def test_harbor_do_nothing_agent_gives_reward_0(language, tmp_path):
    rewards = _harbor_rewards(language, "nop", tmp_path)
    assert set(rewards) == REWARD_KEYS
    assert rewards["reward"] == 0
    assert rewards["reference_compiles"] == 1
    assert rewards["agent_tests_total"] == 0
