"""The rung-3 `poker` task packs, TypeScript and Go (issue #73; PRD section 15,
"The TDD pack recipe").

The fast tests read the packs' files. The slow tests need Docker: they run
each pack's `tests/test.sh` on prepared repositories in the pack image with no
network, and they run each pack through Harbor with the `oracle` and
do-nothing (`nop`) agents.
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
TS_PACK = REPO_ROOT / "tasks" / "typescript" / "poker"
GO_PACK = REPO_ROOT / "tasks" / "go" / "poker"
TS_STUB = "poker.ts"
GO_STUB = "poker.go"
TS_REFERENCE_TEST = "assay-reference.poker.test.ts"
TS_REFERENCE_COUNT = 37
GO_REFERENCE_COUNT = 47  # 37 valid hands + 10 invalid hands

SOURCE_INSTRUCTIONS = (
    "# Instructions\n\nPick the best hand(s) from a list of poker hands.\n\n"
    "See [Wikipedia][poker-hands] for an overview of poker hands.\n\n"
    "[poker-hands]: https://en.wikipedia.org/wiki/List_of_poker_hands\n"
)


def footer(stub: str) -> str:
    return (f"Implement the solution in `{stub}`. Keep the exported names and signatures "
            "as they are. Tests that you cannot see will check your solution.\n")


def _config(pack: Path) -> dict:
    return tomllib.loads((pack / "task.toml").read_text(encoding="utf-8"))


def _seed_files(pack: Path) -> list[str]:
    seed = pack / "environment" / "seed"
    return sorted(p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file())


def _instruction(pack: Path) -> str:
    return (pack / "instruction.md").read_text(encoding="utf-8")


def _interface_section(pack: Path, stub: str) -> str:
    """From the `## Interface` heading up to the footer."""
    text = _instruction(pack)
    heading = re.search(r"^## Interface$", text, re.MULTILINE)
    assert heading, "instruction.md has no '## Interface' section"
    end = text.index(footer(stub))
    assert heading.start() < end
    return text[heading.start():end]


def _base_image(pack: Path) -> str:
    dockerfile = (pack / "environment" / "Dockerfile").read_text(encoding="utf-8")
    return re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE).group(1)


PACKS = [pytest.param(TS_PACK, TS_STUB, id="typescript"), pytest.param(GO_PACK, GO_STUB, id="go")]


# --- Both packs ---------------------------------------------------------------


@pytest.mark.parametrize("pack, stub", PACKS)
def test_instruction_is_the_source_instructions_then_the_interface_then_the_footer(pack, stub):
    text = _instruction(pack)
    assert text.startswith(SOURCE_INSTRUCTIONS + "\n## Interface\n")
    assert text.endswith("\n\n" + footer(stub))
    assert _interface_section(pack, stub)


@pytest.mark.parametrize("pack, stub", PACKS)
def test_seed_repository_names_no_source(pack, stub):
    for path in (pack / "environment" / "seed").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "exercism" not in text, path
            assert "please implement" not in text, path
            assert "remove this line" not in text, path


@pytest.mark.parametrize("pack, stub", PACKS)
def test_task_toml_sets_the_prd_limits_and_records_the_interface_section(pack, stub):
    config = _config(pack)
    assert config["agent"]["timeout_sec"] == 1800
    assert config["verifier"]["timeout_sec"] == 600
    assert config["environment"]["cpus"] == 2
    assert config["environment"]["memory_mb"] == 4096
    changes = " ".join(config["metadata"]["mechanical_changes"])
    assert "Interface section" in changes
    assert stub in changes


@pytest.mark.parametrize("pack, stub", PACKS)
def test_base_image_is_the_model_pack_digest(pack, stub):
    # The same toolchain as rung 1, pinned by the same digest.
    model = pack.parent / "split-second-stopwatch"
    assert _base_image(pack) == _base_image(model)
    assert re.search(r"@sha256:[0-9a-f]{64}$", _base_image(pack))
    assert _config(pack)["metadata"]["base_image"] == _base_image(pack)


@pytest.mark.parametrize("pack, stub", PACKS)
def test_metadata_records_the_source_at_the_model_pack_commit(pack, stub):
    meta = _config(pack)["metadata"]
    model = _config(pack.parent / "split-second-stopwatch")["metadata"]
    assert meta["source_repo"] == model["source_repo"]
    assert meta["source_commit"] == model["source_commit"]
    assert sorted(meta["seed_files"]) == _seed_files(pack)
    assert all(p.startswith("exercises/practice/poker/") for p in meta["copied_paths"])


@pytest.mark.parametrize("pack, stub", PACKS)
def test_verifier_keeps_the_red_compile_rule_and_names_its_pack(pack, stub):
    model = pack.parent / "split-second-stopwatch"
    assert _config(pack)["metadata"]["red_compile_rule"] == \
        _config(model)["metadata"]["red_compile_rule"]
    script = (pack / "tests" / "test.sh").read_text(encoding="utf-8")
    model_script = (model / "tests" / "test.sh").read_text(encoding="utf-8")
    assert "poker" in script.splitlines()[1]
    # Apart from the pack's name, the verifier is the model pack's.
    assert script.replace("poker", "split-second-stopwatch") == model_script


@pytest.mark.parametrize("pack, stub", PACKS)
def test_pack_files_have_lf_line_endings(pack, stub):
    for path in pack.rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


# --- TypeScript ---------------------------------------------------------------


def test_typescript_seed_holds_the_stub_and_the_toolchain_files_only():
    assert _seed_files(TS_PACK) == sorted([
        TS_STUB, "package.json", "yarn.lock", ".yarnrc.yml", "tsconfig.json",
        "jest.config.cjs", "babel.config.cjs", "eslint.config.mjs",
    ])
    package = json.loads((TS_PACK / "environment" / "seed" / "package.json").read_text("utf-8"))
    assert package["name"] == "poker"


def test_typescript_toolchain_files_are_the_model_packs():
    model = TS_PACK.parent / "split-second-stopwatch" / "environment" / "seed"
    seed = TS_PACK / "environment" / "seed"
    for name in (".yarnrc.yml", "tsconfig.json", "jest.config.cjs", "babel.config.cjs",
                 "eslint.config.mjs"):
        assert (seed / name).read_bytes() == (model / name).read_bytes(), name


def test_typescript_reference_tests_carry_the_prefix_and_no_xit():
    tests = [p.name for p in (TS_PACK / "tests").iterdir()
             if classify("typescript", p.name) == TEST]
    assert tests == [TS_REFERENCE_TEST]
    text = (TS_PACK / "tests" / TS_REFERENCE_TEST).read_text(encoding="utf-8")
    assert not re.search(r"\bx(it|describe)\(", text)
    assert len(re.findall(r"^\s*it\(", text, re.MULTILINE)) == TS_REFERENCE_COUNT


def test_typescript_instruction_names_no_test_command():
    for command in ("yarn", "npm", "jest", "npx"):
        assert command not in _instruction(TS_PACK).lower(), command


def test_typescript_interface_states_the_card_format_and_the_tie_order():
    section = _interface_section(TS_PACK, TS_STUB)
    assert "`bestHands(hands)`" in section
    for rank in ("`2`", "`10`", "`J`", "`Q`", "`K`", "`A`"):
        assert rank in section, rank
    for suit in ("`S`", "`H`", "`D`", "`C`"):
        assert suit in section, suit
    assert "same order" in section


def test_typescript_stub_keeps_the_source_signature():
    text = (TS_PACK / "environment" / "seed" / TS_STUB).read_text(encoding="utf-8")
    # Exercism a24e6ae, exercises/practice/poker/poker.ts.
    assert re.findall(r"^export .*$", text, re.MULTILINE) == [
        "export function bestHands(hands: string[]): string[] {"]
    assert "'Not implemented'" in text


def test_typescript_metadata_records_the_scrub_and_the_copies():
    meta = _config(TS_PACK)["metadata"]
    exercise = "exercises/practice/poker/"
    assert set(meta["copied_paths"]) >= {
        exercise + TS_STUB, exercise + "poker.test.ts", exercise + ".meta/proof.ci.ts",
        exercise + ".docs/instructions.md"}
    assert len(meta["copied_paths"]) == len(meta["copied_to"])
    changes = " ".join(meta["mechanical_changes"])
    for edited in ("xit", "assay-reference.", "package.json", "tsconfig.json",
                   "babel.config.cjs", "eslint.config.mjs", "yarn.lock",
                   "@babel/preset-env", "typescript-eslint"):
        assert edited in changes, edited


# --- Go -----------------------------------------------------------------------


def test_go_seed_holds_the_stub_and_go_mod_only():
    assert _seed_files(GO_PACK) == ["go.mod", GO_STUB]
    assert (GO_PACK / "environment" / "seed" / "go.mod").read_text("utf-8") == \
        "module poker\n\ngo 1.27\n"


def test_go_instruction_says_test_only_in_the_footer():
    # The agent is not told how its work is checked before the footer.
    assert "test" not in _instruction(GO_PACK).split("Implement the solution in")[0].lower()


def test_go_interface_states_the_card_format_the_tie_order_and_the_error():
    section = _interface_section(GO_PACK, GO_STUB)
    assert "`BestHand(hands []string) ([]string, error)`" in section
    for suit in ("♤", "♡", "♢", "♧"):
        assert suit in section, suit
    assert "same order" in section
    assert "error" in section


def test_go_stub_keeps_the_source_signature():
    text = (GO_PACK / "environment" / "seed" / GO_STUB).read_text(encoding="utf-8")
    assert text.startswith("package poker\n")
    # Exercism 74f09b2, exercises/practice/poker/poker.go.
    assert re.findall(r"^(func .*?)\s*\{", text, re.MULTILINE) == [
        "func BestHand(hands []string) ([]string, error)"]
    assert 'panic("not implemented")' in text


def test_go_metadata_records_the_copies_and_renames():
    meta = _config(GO_PACK)["metadata"]
    assert meta["source_dir"] == "exercises/practice/poker"
    assert len(meta["copied_paths"]) == len(meta["pack_paths"])
    assert any(p.endswith(".meta/example.go") for p in meta["copied_paths"])
    assert any(p.endswith("cases_test.go") for p in meta["copied_paths"])
    assert sorted(p.name for p in (GO_PACK / "tests" / "reference").iterdir()) == [
        "assay_reference_cases_test.go", "assay_reference_poker_test.go"]
    changes = " ".join(meta["mechanical_changes"])
    assert "not implemented" in changes
    assert "instructions.append.md" in changes


# --- Slow: the pack images and tests/test.sh ---------------------------------


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kwargs)


def _build(pack: Path, name: str):
    tag = f"assay-test-{name}-poker:{uuid.uuid4().hex[:8]}"
    build = _docker("build", "-q", "-t", tag, str(pack / "environment"), timeout=1200)
    assert build.returncode == 0, build.stderr
    return tag


@pytest.fixture(scope="module")
def ts_image():
    tag = _build(TS_PACK, "ts")
    yield tag
    _docker("image", "rm", "-f", tag)


@pytest.fixture(scope="module")
def go_image():
    tag = _build(GO_PACK, "go")
    yield tag
    _docker("image", "rm", "-f", tag)


def _run_in_image(image: str, pack: Path, script: str, files: dict[str, str],
                  tmp_path: Path) -> subprocess.CompletedProcess:
    """Run a bash script with no network, after writing `files` over /app."""
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    for rel, content in files.items():
        target = overlay / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return _docker("run", "--rm", "--network", "none",
                   "-v", f"{pack / 'tests'}:/tests:ro", "-v", f"{overlay}:/overlay:ro",
                   image, "bash", "-c", "cp -r /overlay/. /app/ && " + script, timeout=600)


def _verify(image: str, pack: Path, tmp_path: Path, files: dict[str, str]) -> dict:
    result = _run_in_image(
        image, pack, "bash /tests/test.sh >/dev/null 2>&1; cat /logs/verifier/reward.json",
        files, tmp_path)
    assert result.returncode == 0, result.stderr
    reward = json.loads(result.stdout)
    assert set(reward) == REWARD_KEYS
    assert all(type(v) in (int, float) for v in reward.values())
    return reward


def _ts_proof() -> str:
    return (TS_PACK / "solution" / "proof.ci.ts").read_text(encoding="utf-8")


def _go_gold() -> str:
    return (GO_PACK / "solution" / "example.go").read_text(encoding="utf-8")


TS_NON_COMPILING_AGENT_TEST = """\
import { expect, it } from '@jest/globals'
import { bestHands } from './poker.ts'

it('one hand wins', () => {
  const best: number = bestHands(['4S 5S 7H 8D JC'])
  expect(best).toEqual(['4S 5S 7H 8D JC'])
})
"""

GO_NON_COMPILING_AGENT_TEST = """package poker

import "testing"

func TestOneHandWins(t *testing.T) {
	undefinedHelper()
}
"""


@pytest.mark.slow
def test_typescript_gold_solution_passes_every_reference_test(ts_image, tmp_path):
    reward = _verify(ts_image, TS_PACK, tmp_path, {TS_STUB: _ts_proof()})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == TS_REFERENCE_COUNT
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_typescript_seed_stub_gives_reward_0_and_the_reference_tests_compile(ts_image, tmp_path):
    reward = _verify(ts_image, TS_PACK, tmp_path, {})
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["reference_total"] == TS_REFERENCE_COUNT
    assert reward["reference_passed"] == 0


@pytest.mark.slow
def test_typescript_agent_test_that_does_not_compile_leaves_the_outcome_pass(ts_image, tmp_path):
    reward = _verify(ts_image, TS_PACK, tmp_path, {
        TS_STUB: _ts_proof(), "poker.test.ts": TS_NON_COMPILING_AGENT_TEST})
    assert reward["reward"] == 1
    assert reward["reference_passed"] == TS_REFERENCE_COUNT
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1


@pytest.mark.slow
def test_typescript_changed_stub_signature_fails_the_reference_compile(ts_image, tmp_path):
    changed = _ts_proof().replace("bestHands(hands: string[])", "bestHands(hands: number[])")
    assert changed != _ts_proof()
    reward = _verify(ts_image, TS_PACK, tmp_path, {TS_STUB: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0


@pytest.mark.slow
def test_typescript_image_holds_the_seed_commit_only(ts_image, tmp_path):
    result = _run_in_image(ts_image, TS_PACK, "cd /app; git log --format=%s; git ls-files;"
                           " git status --porcelain | wc -l", {}, tmp_path)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "seed"
    assert sorted(lines[1:-1]) == _seed_files(TS_PACK)
    assert lines[-1] == "0"


@pytest.mark.slow
def test_go_gold_solution_passes_every_reference_test(go_image, tmp_path):
    reward = _verify(go_image, GO_PACK, tmp_path, {GO_STUB: _go_gold()})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == GO_REFERENCE_COUNT
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_go_seed_stub_gives_reward_0_and_the_reference_tests_compile(go_image, tmp_path):
    # The stub panics, which ends the reference run after its first case.
    reward = _verify(go_image, GO_PACK, tmp_path, {})
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == 0


@pytest.mark.slow
def test_go_agent_test_that_does_not_compile_leaves_the_outcome_pass(go_image, tmp_path):
    reward = _verify(go_image, GO_PACK, tmp_path, {
        GO_STUB: _go_gold(), "poker_test.go": GO_NON_COMPILING_AGENT_TEST})
    assert reward["reward"] == 1
    assert reward["reference_passed"] == GO_REFERENCE_COUNT
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1


@pytest.mark.slow
def test_go_changed_stub_signature_fails_the_reference_compile(go_image, tmp_path):
    changed = _go_gold().replace("func BestHand(hands []string)",
                                 "func BestHand(hands []string, _ int)")
    assert changed != _go_gold()
    reward = _verify(go_image, GO_PACK, tmp_path, {GO_STUB: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0


@pytest.mark.slow
def test_go_image_holds_the_seed_commit_only(go_image, tmp_path):
    result = _run_in_image(go_image, GO_PACK, "cd /app; git log --format=%s;"
                           " git status --porcelain; ls -A", {}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["seed", ".git", "go.mod", GO_STUB]


# --- Slow: Harbor -------------------------------------------------------------


def _harbor_reward(pack: Path, agent: str, tmp_path: Path) -> dict:
    job = f"{pack.parent.name}-poker-{agent}"
    result = subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(pack), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rewards = list((tmp_path / job).glob("*/verifier/reward.json"))
    assert len(rewards) == 1, result.stdout
    return json.loads(rewards[0].read_text(encoding="utf-8"))


HARBOR_PACKS = [pytest.param(TS_PACK, TS_REFERENCE_COUNT, id="typescript"),
                pytest.param(GO_PACK, GO_REFERENCE_COUNT, id="go")]


@pytest.mark.slow
@pytest.mark.parametrize("pack, count", HARBOR_PACKS)
def test_harbor_oracle_gives_reward_1(pack, count, tmp_path):
    reward = _harbor_reward(pack, "oracle", tmp_path)
    assert set(reward) == REWARD_KEYS
    assert reward["reward"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == count


@pytest.mark.slow
@pytest.mark.parametrize("pack, count", HARBOR_PACKS)
def test_harbor_do_nothing_agent_gives_reward_0(pack, count, tmp_path):
    reward = _harbor_reward(pack, "nop", tmp_path)
    assert set(reward) == REWARD_KEYS
    assert reward["reward"] == 0
    assert reward["agent_tests_total"] == 0
