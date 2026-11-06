"""The rung-6 task packs: `tasks/typescript/alphametics/` and
`tasks/go/alphametics/` (issue #76; PRD Part II, "The difficulty ladder").

The fast tests read the packs' files. The slow tests need Docker: they run
each pack's `tests/test.sh` in its image with no network, and run the packs
through Harbor with the `oracle` and do-nothing (`nop`) agents.
"""

import json
import re
import subprocess
import tomllib
import uuid
from pathlib import Path

import pytest

from analyze.languages import TEST, classify
from tests.test_typescript_task_pack import REWARD_KEYS, _docker

REPO_ROOT = Path(__file__).resolve().parent.parent
TS_PACK = REPO_ROOT / "tasks" / "typescript" / "alphametics"
GO_PACK = REPO_ROOT / "tasks" / "go" / "alphametics"
PACKS = {"typescript": TS_PACK, "go": GO_PACK}
STUBS = {"typescript": "alphametics.ts", "go": "alphametics.go"}
TS_REFERENCE_TEST = "assay-reference.alphametics.test.ts"
GO_REFERENCE_CASES = "assay_reference_cases_test.go"
# Both languages hold the same eight reference cases (TypeScript's whole suite).
REFERENCE_CASE_COUNT = 8
SOURCE_INSTRUCTIONS_START = "# Instructions\n\nGiven an alphametics puzzle, find the correct solution.\n"


def _seed(language: str) -> Path:
    return PACKS[language] / "environment" / "seed"


def _seed_files(language: str) -> list[str]:
    seed = _seed(language)
    return sorted(p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file())


def _task_toml(language: str) -> dict:
    return tomllib.loads((PACKS[language] / "task.toml").read_text(encoding="utf-8"))


def _changes(language: str) -> str:
    return " ".join(_task_toml(language)["metadata"]["mechanical_changes"])


def _instruction(language: str) -> str:
    return (PACKS[language] / "instruction.md").read_text(encoding="utf-8")


def _footer(language: str) -> str:
    return (f"Implement the solution in `{STUBS[language]}`. Keep the exported names "
            "and signatures as they are. Tests that you cannot see will check your solution.\n")


def _interface_section(language: str) -> str:
    text = _instruction(language)
    prose, heading, rest = text.partition("\n## Interface\n")
    assert heading, "instruction.md has no '## Interface' section"
    section, footer, _ = rest.partition("Implement the solution in")
    assert footer, "the Interface section must come before the footer"
    return section


def _ts_reference_descriptions() -> list[str]:
    text = (TS_PACK / "tests" / TS_REFERENCE_TEST).read_text(encoding="utf-8")
    return re.findall(r"^\s*it\('([^']+)'", text, re.MULTILINE)


def _go_reference_descriptions() -> list[str]:
    text = (GO_PACK / "tests" / "reference" / GO_REFERENCE_CASES).read_text(encoding="utf-8")
    return re.findall(r'^\s*description:\s*"([^"]+)"', text, re.MULTILINE)


# --- Both packs ---------------------------------------------------------------


@pytest.mark.parametrize("language", PACKS)
def test_instruction_is_the_source_instructions_then_the_interface_then_the_footer(language):
    text = _instruction(language)
    assert text.startswith(SOURCE_INSTRUCTIONS_START)
    assert text.endswith(_footer(language))
    assert text.index("\n## Interface\n") < text.index("Implement the solution in")


@pytest.mark.parametrize("language", PACKS)
def test_interface_states_the_solution_map_and_the_no_solution_result(language):
    section = _interface_section(language)
    name = {"typescript": "solve", "go": "Solve"}[language]
    assert f"`{name}(" in section
    no_solution = {"typescript": "`undefined`", "go": "error"}[language]
    assert no_solution in section


@pytest.mark.parametrize("language", PACKS)
def test_task_toml_sets_the_prd_limits(language):
    config = _task_toml(language)
    assert config["agent"]["timeout_sec"] == 1800
    assert config["verifier"]["timeout_sec"] == 600
    assert config["environment"]["cpus"] == 2
    assert config["environment"]["memory_mb"] == 4096
    assert config["environment"].get("network_mode", "public") == "public"


@pytest.mark.parametrize("language", PACKS)
def test_metadata_image_digest_is_the_dockerfile_base_image_of_the_model_pack(language):
    def base(pack: Path) -> str:
        dockerfile = (pack / "environment" / "Dockerfile").read_text(encoding="utf-8")
        return re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE).group(1)

    model = REPO_ROOT / "tasks" / language / "split-second-stopwatch"
    assert base(PACKS[language]) == base(model)
    assert re.search(r"@sha256:[0-9a-f]{64}$", base(PACKS[language]))
    assert _task_toml(language)["metadata"]["base_image"] == base(PACKS[language])


@pytest.mark.parametrize("language", PACKS)
def test_metadata_records_the_provenance_and_the_seed(language):
    meta = _task_toml(language)["metadata"]
    track = {"typescript": "typescript", "go": "go"}[language]
    assert meta["source_repo"] == f"https://github.com/exercism/{track}"
    model = tomllib.loads((REPO_ROOT / "tasks" / language / "split-second-stopwatch" / "task.toml")
                          .read_text(encoding="utf-8"))["metadata"]
    assert meta["source_commit"] == model["source_commit"]
    assert all(p.startswith("exercises/practice/alphametics/") for p in meta["copied_paths"])
    assert sorted(meta["seed_files"]) == _seed_files(language)
    assert meta["red_compile_rule"] == model["red_compile_rule"]
    assert "Interface section" in _changes(language)


@pytest.mark.parametrize("language", PACKS)
def test_seed_names_no_source(language):
    for path in _seed(language).rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "exercism" not in text, path.name
            assert "please implement" not in text, path.name
            assert "remove this line" not in text, path.name


@pytest.mark.parametrize("language", PACKS)
def test_pack_files_have_lf_line_endings(language):
    for path in PACKS[language].rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


def test_both_languages_hold_the_same_reference_cases():
    assert len(_ts_reference_descriptions()) == REFERENCE_CASE_COUNT
    assert _go_reference_descriptions() == _ts_reference_descriptions()


# --- TypeScript -----------------------------------------------------------------


def test_typescript_reference_tests_carry_the_prefix_and_no_xit():
    tests = [p.name for p in (TS_PACK / "tests").iterdir() if classify("typescript", p.name) == TEST]
    assert tests == [TS_REFERENCE_TEST]
    text = (TS_PACK / "tests" / TS_REFERENCE_TEST).read_text(encoding="utf-8")
    assert not re.search(r"\bx(it|describe)\(", text)


def test_typescript_seed_holds_the_stub_and_the_toolchain_only():
    assert _seed_files("typescript") == sorted([
        "alphametics.ts", "package.json", "yarn.lock", ".yarnrc.yml", "tsconfig.json",
        "jest.config.cjs", "babel.config.cjs", "eslint.config.mjs",
    ])
    package = json.loads((_seed("typescript") / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == "alphametics"
    lock = (_seed("typescript") / "yarn.lock").read_text(encoding="utf-8")
    assert '"alphametics@workspace:."' in lock
    assert "split-second-stopwatch" not in lock


def test_typescript_toolchain_files_are_the_model_pack_files():
    model = REPO_ROOT / "tasks" / "typescript" / "split-second-stopwatch" / "environment" / "seed"
    for name in (".yarnrc.yml", "tsconfig.json", "jest.config.cjs", "babel.config.cjs",
                 "eslint.config.mjs"):
        assert (_seed("typescript") / name).read_bytes() == (model / name).read_bytes(), name


def test_typescript_stub_keeps_the_source_signature():
    # Exercism a24e6ae, exercises/practice/alphametics/alphametics.ts.
    text = (_seed("typescript") / "alphametics.ts").read_text(encoding="utf-8")
    assert re.findall(r"^export .*$", text, re.MULTILINE) == [
        "export function solve(puzzle: unknown): unknown {"]
    assert "'Not implemented'" in text


def test_typescript_instruction_names_no_test_command():
    text = _instruction("typescript").lower()
    for command in ("yarn", "npm", "jest", "npx"):
        assert command not in text, command


def test_typescript_metadata_records_the_mechanical_changes():
    changes = _changes("typescript")
    for edited in ("xit", "assay-reference.", "package.json", "yarn.lock", "tsconfig.json",
                   "babel.config.cjs", "eslint.config.mjs", "alphametics.ts",
                   "@babel/preset-env", "typescript-eslint"):
        assert edited in changes, edited


# --- Go ---------------------------------------------------------------------------


def test_go_pack_has_no_199_addend_case():
    text = (GO_PACK / "tests" / "reference" / GO_REFERENCE_CASES).read_text(encoding="utf-8")
    assert "199 addends" not in text
    assert "ten letters and 199 addends" in _changes("go")


def test_go_pack_records_the_final_carry_decision():
    assert "two digits final carry" not in _go_reference_descriptions()
    assert "two digits final carry" in _changes("go")


def test_go_seed_holds_the_stub_and_go_mod_only():
    assert _seed_files("go") == ["alphametics.go", "go.mod"]
    assert _task_toml("go")["metadata"]["seed_files"] == ["go.mod", "alphametics.go"]
    assert (_seed("go") / "go.mod").read_text(encoding="utf-8") == "module alphametics\n\ngo 1.27\n"


def test_go_stub_keeps_the_source_signature():
    # Exercism 74f09b2, exercises/practice/alphametics/alphametics.go.
    stub = (_seed("go") / "alphametics.go").read_text(encoding="utf-8")
    assert stub.startswith("package alphametics\n")
    assert re.findall(r"^(func .*?)\s*\{", stub, re.M) == [
        "func Solve(puzzle string) (map[string]int, error)"]
    assert 'panic("not implemented")' in stub


def test_go_instruction_says_test_nowhere_before_the_footer():
    assert "test" not in _instruction("go").split("Implement the solution in")[0].lower()


def test_go_metadata_records_the_mechanical_changes():
    meta = _task_toml("go")["metadata"]
    assert any(p.endswith(".meta/example.go") for p in meta["copied_paths"])
    assert any(p.endswith("cases_test.go") for p in meta["copied_paths"])
    changes = _changes("go")
    assert "alphametics.go" in changes and "not implemented" in changes
    assert "instructions.append.md" in changes


# --- Slow: the pack images and tests/test.sh ----------------------------------------


def _gold(language: str) -> str:
    name = {"typescript": "proof.ci.ts", "go": "example.go"}[language]
    return (PACKS[language] / "solution" / name).read_text(encoding="utf-8")


# Each type-checks or builds on its own, but does not compile against the code.
NON_COMPILING_AGENT_TESTS = {
    "typescript": ("alphametics.test.ts", """\
import { expect, it } from '@jest/globals'
import { solve } from './alphametics.ts'

it('solves', () => {
  const answer: number = solve('I + BB == ILL')
  expect(answer).toBeDefined()
})
"""),
    "go": ("solve_test.go", """\
package alphametics

import "testing"

func TestSolve(t *testing.T) {
	undefinedHelper()
}
"""),
}


@pytest.fixture(scope="module", params=list(PACKS))
def image(request):
    language = request.param
    tag = f"assay-test-{language}-alphametics:{uuid.uuid4().hex[:8]}"
    build = _docker("build", "-q", "-t", tag, str(PACKS[language] / "environment"), timeout=1200)
    assert build.returncode == 0, build.stderr
    yield language, tag
    _docker("image", "rm", "-f", tag)


def _verify(image, tmp_path: Path, files: dict[str, str] | None = None) -> dict:
    """Put `files` over /app, run the pack's tests/test.sh with no network,
    and return reward.json."""
    language, tag = image
    mounts = ["-v", f"{PACKS[language] / 'tests'}:/tests:ro"]
    prelude = ""
    if files:
        overlay = tmp_path / "overlay"
        for rel, content in files.items():
            target = overlay / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        mounts += ["-v", f"{overlay}:/overlay:ro"]
        prelude = "cp -r /overlay/. /app/ && "
    result = _docker("run", "--rm", "--network", "none", *mounts, tag, "bash", "-c",
                     prelude + "bash /tests/test.sh >/dev/null 2>&1; cat /logs/verifier/reward.json",
                     timeout=900)
    assert result.returncode == 0, result.stderr
    reward = json.loads(result.stdout)
    assert set(reward) == REWARD_KEYS
    assert all(type(v) in (int, float) for v in reward.values())
    return reward


@pytest.mark.slow
def test_gold_solution_passes_every_reference_case(image, tmp_path):
    language, _ = image
    reward = _verify(image, tmp_path, {STUBS[language]: _gold(language)})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == REFERENCE_CASE_COUNT
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_untouched_stub_gives_reward_0_and_the_reference_tests_compile(image, tmp_path):
    reward = _verify(image, tmp_path)
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_agent_test_that_does_not_compile_leaves_the_outcome_pass_unaffected(image, tmp_path):
    language, _ = image
    name, content = NON_COMPILING_AGENT_TESTS[language]
    reward = _verify(image, tmp_path, {STUBS[language]: _gold(language), name: content})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == REFERENCE_CASE_COUNT
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1


@pytest.mark.slow
def test_changed_stub_signature_fails_the_reference_compile(image, tmp_path):
    language, _ = image
    old, new = {
        "typescript": ("solve(puzzle: string)", "solve(puzzle: number)"),
        "go": ("Solve(puzzle string)", "Solve(puzzle string, _ int)"),
    }[language]
    changed = _gold(language).replace(old, new)
    assert changed != _gold(language)
    reward = _verify(image, tmp_path, {STUBS[language]: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0


# --- Slow: Harbor ---------------------------------------------------------------------


def _harbor_reward(language: str, agent: str, tmp_path: Path) -> dict:
    job = f"{language}-alphametics-{agent}"
    result = subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(PACKS[language]), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=1800,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (trial,) = [p for p in (tmp_path / job).iterdir() if p.is_dir()]
    rewards = json.loads((trial / "result.json").read_text(encoding="utf-8"))["verifier_result"]["rewards"]
    assert set(rewards) == REWARD_KEYS
    return rewards


@pytest.mark.slow
@pytest.mark.parametrize("language", PACKS)
def test_harbor_oracle_agent_gets_full_reward(language, tmp_path):
    rewards = _harbor_reward(language, "oracle", tmp_path)
    assert rewards["reward"] == 1
    assert rewards["reference_passed"] == rewards["reference_total"] == REFERENCE_CASE_COUNT


@pytest.mark.slow
@pytest.mark.parametrize("language", PACKS)
def test_harbor_do_nothing_agent_gets_zero_reward(language, tmp_path):
    rewards = _harbor_reward(language, "nop", tmp_path)
    assert rewards["reward"] == 0
    assert rewards["agent_tests_total"] == 0
