"""The rung-2 `wordy` task packs, TypeScript and Go (issue #72; spec #67).

The fast tests read the packs' files. The slow tests build each pack image
and run its `tests/test.sh` with no network, and run each pack through
Harbor's oracle and do-nothing (`nop`) agents.
"""

import json
import re
import subprocess
import tomllib
import uuid
from pathlib import Path

import pytest

from analyze.languages import TEST, classify
from tests.test_go_task_pack import REWARD_FIELDS

REPO_ROOT = Path(__file__).resolve().parent.parent
LANGUAGES = ("typescript", "go")
SOURCE_DIR = "exercises/practice/wordy/"
# The reference cases: 27 `it(` blocks in TypeScript, 27 subtests in Go.
REFERENCE_COUNT = 27
STUB = {"typescript": "wordy.ts", "go": "wordy.go"}
GOLD = {"typescript": "proof.ci.ts", "go": "example.go"}
SEED_FILES = {
    "typescript": sorted(["wordy.ts", "package.json", "yarn.lock", ".yarnrc.yml", "tsconfig.json",
                          "jest.config.cjs", "babel.config.cjs", "eslint.config.mjs"]),
    "go": ["go.mod", "wordy.go"],
}
SOURCE_REPO = {"typescript": "https://github.com/exercism/typescript",
               "go": "https://github.com/exercism/go"}
FOOTER = {
    language: f"Implement the solution in `{STUB[language]}`. Keep the exported names and "
              "signatures as they are. Tests that you cannot see will check your solution.\n"
    for language in LANGUAGES
}
# The exported signatures of the source stubs at the pinned commits. The
# TypeScript source was `export const answer = () => {`: it took no parameter,
# so the reference tests did not type-check against it (recorded as a
# mechanical change); the pack's stub gains the one parameter they pass.
SOURCE_SIGNATURES = {
    "typescript": ["export const answer = (question: unknown): unknown => {"],
    "go": ["func Answer(question string) (int, bool) {"],
}


def pack(language: str) -> Path:
    return REPO_ROOT / "tasks" / language / "wordy"


def seed(language: str) -> Path:
    return pack(language) / "environment" / "seed"


def task_toml(language: str) -> dict:
    return tomllib.loads((pack(language) / "task.toml").read_text(encoding="utf-8"))


def instruction(language: str) -> str:
    return (pack(language) / "instruction.md").read_text(encoding="utf-8")


def interface_section(language: str) -> str:
    text = instruction(language)
    _, heading, rest = text.partition("\n## Interface\n")
    assert heading, "instruction.md has no Interface section"
    section, footer, _ = rest.partition("Implement the solution in")
    assert footer, "the Interface section must come before the footer"
    return section


def reference_tests(language: str) -> list[Path]:
    return sorted(p for p in (pack(language) / "tests").rglob("*")
                  if p.is_file() and classify(language, p.name) == TEST)


languages = pytest.mark.parametrize("language", LANGUAGES)


# --- The packs' files ---------------------------------------------------------


@languages
def test_seed_repository_holds_only_the_stub_and_the_toolchain_files(language):
    files = sorted(p.relative_to(seed(language)).as_posix()
                   for p in seed(language).rglob("*") if p.is_file())
    assert files == SEED_FILES[language]


@languages
def test_seed_repository_names_no_source(language):
    for path in seed(language).rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "exercism" not in text, path.name
            assert "please implement" not in text, path.name
            assert "remove this line" not in text, path.name


@languages
def test_instruction_is_the_source_instructions_then_the_interface_then_the_footer(language):
    text = instruction(language)
    assert text.startswith(
        "# Instructions\n\nParse and evaluate simple math word problems returning the answer as an integer.\n")
    assert text.endswith(FOOTER[language])
    source_end = text.index('- Word problems with invalid syntax ("What is 1 plus plus 2?")\n')
    assert source_end < text.index("\n## Interface\n") < text.index(FOOTER[language])


def test_typescript_instruction_names_no_test_command():
    for command in ("yarn", "npm", "jest", "npx"):
        assert command not in instruction("typescript").lower(), command


def test_go_instruction_says_test_only_in_the_footer():
    assert "test" not in instruction("go").split("Implement the solution in")[0].lower()


def test_typescript_interface_names_exactly_the_reference_error_messages():
    text = (pack("typescript") / "tests" / "assay-reference.wordy.test.ts").read_text(encoding="utf-8")
    messages = set(re.findall(r"toThrow\(\s*new Error\(\s*'([^']+)'\s*\)\s*\)", text))
    assert messages == {"Unknown operation", "Syntax error"}
    section = interface_section("typescript")
    assert set(re.findall(r'`"([^"`]+)"`', section)) >= messages
    assert "`answer(question)`" in section and "number" in section


def test_go_interface_states_the_answer_and_ok_results():
    section = interface_section("go")
    assert "`Answer(question string) (int, bool)`" in section
    assert "`true`" in section and "`false`" in section


@languages
def test_stub_keeps_the_source_signatures(language):
    text = (seed(language) / STUB[language]).read_text(encoding="utf-8")
    if language == "typescript":
        signatures = [line.strip() for line in text.splitlines() if line.startswith("export ")]
    else:
        assert text.startswith("package wordy\n")
        assert (seed("go") / "go.mod").read_text(encoding="utf-8").startswith("module wordy\n")
        signatures = [line.strip() for line in text.splitlines() if line.startswith("func ")]
    assert signatures == SOURCE_SIGNATURES[language]
    assert re.search(r"not implemented", text, re.IGNORECASE)


def test_typescript_reference_tests_carry_the_prefix_and_no_xit():
    assert [p.name for p in reference_tests("typescript")] == ["assay-reference.wordy.test.ts"]
    text = reference_tests("typescript")[0].read_text(encoding="utf-8")
    assert not re.search(r"\bx(it|describe)\(", text)
    assert len(re.findall(r"^\s*it\(", text, re.MULTILINE)) == REFERENCE_COUNT


def test_go_reference_tests_carry_the_prefix():
    assert [p.name for p in reference_tests("go")] == [
        "assay_reference_cases_test.go", "assay_reference_wordy_test.go"]


@languages
def test_metadata_records_the_provenance_and_the_mechanical_changes(language):
    config = task_toml(language)
    meta = config["metadata"]
    assert meta["language"] == language
    assert meta["source_repo"] == SOURCE_REPO[language]
    model = tomllib.loads((REPO_ROOT / "tasks" / language / "split-second-stopwatch" / "task.toml")
                          .read_text(encoding="utf-8"))
    assert meta["source_commit"] == model["metadata"]["source_commit"]
    assert meta["base_image"] == model["metadata"]["base_image"]
    dockerfile = (pack(language) / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM (\S+)", dockerfile, re.M).group(1) == meta["base_image"]
    assert all(p.startswith(SOURCE_DIR) for p in meta["copied_paths"])
    assert SOURCE_DIR + ".meta/" + GOLD[language] in meta["copied_paths"]
    assert SOURCE_DIR + ".docs/instructions.md" in meta["copied_paths"]
    assert sorted(meta["seed_files"]) == SEED_FILES[language]
    changes = " ".join(meta["mechanical_changes"])
    assert "Interface section" in changes and "footer" in changes and STUB[language] in changes
    if language == "typescript":
        assert "xit" in changes and "assay-reference." in changes and "question: unknown" in changes
        for edited in ("package.json", "tsconfig.json", "babel.config.cjs", "eslint.config.mjs",
                       "yarn.lock"):
            assert edited in changes, edited
    else:
        assert "not implemented" in changes and "assay_reference_" in changes
    for key, value in model.items():
        if key != "metadata":
            assert config[key] == value, key


@languages
def test_pack_files_have_lf_line_endings(language):
    for path in pack(language).rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


# --- Slow: the pack images and tests/test.sh ----------------------------------

# Calls the solution with a wrong argument type, so it does not compile.
AGENT_TEST_NOT_COMPILING = {
    "typescript": ("wordy.test.ts", """\
import { expect, it } from '@jest/globals'
import { answer } from './wordy.ts'

it('adds', () => {
  const sum: string = answer(5)
  expect(sum).toEqual(2)
})
"""),
    "go": ("wordy_test.go", """\
package wordy

import "testing"

func TestAdds(t *testing.T) {
	if got, _ := Answer(5); got != 2 {
		t.Fatal(got)
	}
}
"""),
}


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kwargs)


@pytest.fixture(scope="module", params=LANGUAGES)
def image(request):
    language = request.param
    tag = f"assay-test-{language}-wordy:{uuid.uuid4().hex[:8]}"
    build = _docker("build", "-q", "-t", tag, str(pack(language) / "environment"), timeout=1200)
    assert build.returncode == 0, build.stderr
    yield language, tag
    _docker("image", "rm", "-f", tag)


def verify(image, tmp_path: Path, files: dict[str, str]) -> dict:
    """Write `files` over /app in the pack image, run tests/test.sh, read reward.json."""
    language, tag = image
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    for name, content in files.items():
        (overlay / name).write_text(content, encoding="utf-8", newline="\n")
    result = _docker(
        "run", "--rm", "--network", "none",
        "-v", f"{pack(language) / 'tests'}:/tests:ro", "-v", f"{overlay}:/overlay:ro", tag,
        "bash", "-c", "cp -r /overlay/. /app/ && bash /tests/test.sh >/dev/null 2>&1;"
                      " cat /logs/verifier/reward.json",
        timeout=600)
    assert result.returncode == 0, result.stderr
    reward = json.loads(result.stdout)
    assert set(reward) == REWARD_FIELDS
    return reward


def gold(language: str) -> str:
    return (pack(language) / "solution" / GOLD[language]).read_text(encoding="utf-8")


@pytest.mark.slow
def test_gold_solution_passes_every_reference_case(image, tmp_path):
    language, _ = image
    reward = verify(image, tmp_path, {STUB[language]: gold(language)})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == REFERENCE_COUNT


@pytest.mark.slow
def test_untouched_stub_gives_reward_0_and_the_reference_tests_compile(image, tmp_path):
    reward = verify(image, tmp_path, {})
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_agent_test_that_does_not_compile_leaves_the_outcome_pass_unaffected(image, tmp_path):
    language, _ = image
    name, content = AGENT_TEST_NOT_COMPILING[language]
    reward = verify(image, tmp_path, {STUB[language]: gold(language), name: content})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == REFERENCE_COUNT
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1


# --- Slow: Harbor ---------------------------------------------------------------


def harbor_reward(language: str, agent: str, tmp_path: Path) -> dict:
    job = f"{language}-wordy-{agent}"
    result = subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(pack(language)), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rewards = list((tmp_path / job).glob("*/verifier/reward.json"))
    assert len(rewards) == 1, result.stdout
    reward = json.loads(rewards[0].read_text(encoding="utf-8"))
    assert set(reward) == REWARD_FIELDS
    return reward


@pytest.mark.slow
@languages
def test_harbor_oracle_agent_gets_reward_1(language, tmp_path):
    reward = harbor_reward(language, "oracle", tmp_path)
    assert reward["reward"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == REFERENCE_COUNT


@pytest.mark.slow
@languages
def test_harbor_do_nothing_agent_gets_reward_0(language, tmp_path):
    reward = harbor_reward(language, "nop", tmp_path)
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["agent_tests_total"] == 0
