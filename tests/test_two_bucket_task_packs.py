"""The two-bucket task packs, rung 5 of the difficulty ladder (issue #75):
`tasks/typescript/two-bucket/` (a class) and `tasks/go/two-bucket/` (one
function).

Fast tests read the packs' files. Slow tests build each pack image and run
`tests/test.sh` on prepared repositories with no network, or run the pack
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
from tests.test_typescript_task_pack import REWARD_KEYS

REPO_ROOT = Path(__file__).resolve().parent.parent
TS_PACK = REPO_ROOT / "tasks" / "typescript" / "two-bucket"
GO_PACK = REPO_ROOT / "tasks" / "go" / "two-bucket"
TS_STUB = "two-bucket.ts"
GO_STUB = "two_bucket.go"
TS_REFERENCE_TEST = "assay-reference.two-bucket.test.ts"
TS_REFERENCE_TEST_COUNT = 11
GO_REFERENCE_TEST_COUNT = 15  # 11 TestSolve cases + 4 TestErrors cases

INSTRUCTIONS_START = (
    "# Instructions\n\nGiven two buckets of different size and which bucket to fill first")


def _footer(stub: str) -> str:
    return (f"Implement the solution in `{stub}`. Keep the exported names and signatures "
            "as they are. Tests that you cannot see will check your solution.\n")


def _toml(pack: Path) -> dict:
    return tomllib.loads((pack / "task.toml").read_text(encoding="utf-8"))


def _seed_files(pack: Path) -> list[str]:
    seed = pack / "environment" / "seed"
    return sorted(p.relative_to(seed).as_posix() for p in seed.rglob("*") if p.is_file())


def _interface_section(pack: Path, stub: str) -> str:
    """The instruction's Interface section: after the source prose, before the footer."""
    text = (pack / "instruction.md").read_text(encoding="utf-8")
    prose, heading, rest = text.partition("\n## Interface\n")
    assert heading, "instruction.md has no '## Interface' section"
    section, footer, _ = rest.partition(f"Implement the solution in `{stub}`.")
    assert footer, "the Interface section must come before the footer"
    return section


# --- Both packs: the files -------------------------------------------------


@pytest.mark.parametrize("pack, stub", [(TS_PACK, TS_STUB), (GO_PACK, GO_STUB)])
def test_instruction_is_the_source_instructions_then_interface_then_footer(pack, stub):
    text = (pack / "instruction.md").read_text(encoding="utf-8")
    assert text.startswith(INSTRUCTIONS_START)
    assert text.endswith(_footer(stub))
    # The source prose ends with its link reference, then the Interface section.
    prose = text.split("\n## Interface\n")[0]
    assert prose.rstrip().endswith("[fullstack]: https://www.fullstackacademy.com/")


@pytest.mark.parametrize("pack", [TS_PACK, GO_PACK])
def test_seed_repository_names_no_source(pack):
    for path in (pack / "environment" / "seed").rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "exercism" not in text, path
            assert "please implement" not in text, path
            assert "remove this line" not in text, path


@pytest.mark.parametrize("pack", [TS_PACK, GO_PACK])
def test_task_toml_sets_the_prd_limits_and_the_red_compile_rule(pack):
    config = _toml(pack)
    assert config["agent"]["timeout_sec"] == 1800
    assert config["verifier"]["timeout_sec"] == 600
    assert config["environment"]["cpus"] == 2
    assert config["environment"]["memory_mb"] == 4096
    assert config["metadata"]["red_compile_rule"] == (
        "agent test files exist and do not compile: agent_tests_passed = 0, "
        "agent_tests_total = max(counted tests, agent test files)")


@pytest.mark.parametrize("pack, image_pattern", [
    (TS_PACK, r"node:\d+[\d.]*-bookworm@sha256:[0-9a-f]{64}"),
    (GO_PACK, r"golang:[\d.]+-bookworm@sha256:[0-9a-f]{64}"),
])
def test_image_is_pinned_by_digest_and_recorded(pack, image_pattern):
    dockerfile = (pack / "environment" / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE).group(1)
    assert re.fullmatch(image_pattern, base)
    assert _toml(pack)["metadata"]["base_image"] == base
    # The toolchain version of the existing rung-1 pack.
    rung_one = (pack.parent / "split-second-stopwatch" / "environment" / "Dockerfile")
    assert re.search(r"^FROM\s+(\S+)", rung_one.read_text(encoding="utf-8"), re.M).group(1) == base


@pytest.mark.parametrize("pack", [TS_PACK, GO_PACK])
def test_pack_files_have_lf_line_endings(pack):
    for path in pack.rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


# --- TypeScript: a class ---------------------------------------------------


def test_ts_seed_repository_holds_the_stub_and_the_toolchain_files_only():
    assert _seed_files(TS_PACK) == sorted([
        TS_STUB, "package.json", "yarn.lock", ".yarnrc.yml", "tsconfig.json",
        "jest.config.cjs", "babel.config.cjs", "eslint.config.mjs",
    ])
    package = json.loads((TS_PACK / "environment" / "seed" / "package.json").read_text("utf-8"))
    assert package["name"] == "two-bucket"


def test_ts_reference_tests_carry_the_prefix_and_skip_nothing():
    tests = [p.name for p in (TS_PACK / "tests").iterdir() if classify("typescript", p.name) == TEST]
    assert tests == [TS_REFERENCE_TEST]
    text = (TS_PACK / "tests" / TS_REFERENCE_TEST).read_text(encoding="utf-8")
    assert not re.search(r"\bxit\(", text)
    assert not re.search(r"\bxdescribe\(", text)
    assert len(re.findall(r"^\s*it\(", text, re.MULTILINE)) == TS_REFERENCE_TEST_COUNT


# The exported names and signatures of the source stub (exercism/typescript
# a24e6ae, exercises/practice/two-bucket/two-bucket.ts), except the
# constructor: the source's takes no parameter, so the reference tests, which
# pass four, did not type-check against it.
TS_SOURCE_SIGNATURES = [
    "export class TwoBucket {",
    # The source: `constructor() {`.
    "constructor(buckOne: unknown, buckTwo: unknown, goal: unknown, starterBuck: unknown) {",
    "moves() {",
    "get goalBucket() {",
    "get otherBucket() {",
]


def test_ts_stub_keeps_the_source_signatures_and_takes_the_four_arguments():
    text = (TS_PACK / "environment" / "seed" / TS_STUB).read_text(encoding="utf-8")
    signatures = [line.strip() for line in text.splitlines()
                  if re.match(r"\s*(export |constructor\(|moves\(|get )", line)]
    assert signatures == TS_SOURCE_SIGNATURES
    assert "'Not implemented'" in text


def test_ts_interface_states_the_class_api():
    section = _interface_section(TS_PACK, TS_STUB)
    assert "new TwoBucket(" in section
    for name in ("moves()", "goalBucket", "otherBucket"):
        assert f"`{name}" in section, name
    for bucket in ('`"one"`', '`"two"`'):
        assert bucket in section, bucket
    assert "throw" in section


def test_ts_instruction_does_not_name_a_test_command():
    text = (TS_PACK / "instruction.md").read_text(encoding="utf-8").lower()
    for command in ("yarn", "npm", "jest", "npx"):
        assert command not in text, command


def test_ts_metadata_records_the_provenance_and_each_mechanical_change():
    meta = _toml(TS_PACK)["metadata"]
    assert meta["source_repo"] == "https://github.com/exercism/typescript"
    assert meta["source_commit"] == _toml(TS_PACK.parent / "split-second-stopwatch")["metadata"]["source_commit"]
    exercise = "exercises/practice/two-bucket/"
    assert set(meta["copied_paths"]) >= {
        exercise + TS_STUB, exercise + "two-bucket.test.ts",
        exercise + ".meta/proof.ci.ts", exercise + ".docs/instructions.md",
    }
    assert all(p.startswith(exercise) for p in meta["copied_paths"])
    assert len(meta["copied_to"]) == len(meta["copied_paths"])
    assert sorted(meta["seed_files"]) == _seed_files(TS_PACK)
    changes = " ".join(meta["mechanical_changes"])
    for expected in ("xit(", "xdescribe(", "assay-reference.", "Interface section",
                     "package.json", "tsconfig.json", "babel.config.cjs", "eslint.config.mjs",
                     "yarn.lock", TS_STUB, "@babel/preset-env", "typescript-eslint",
                     "constructor", "proof.ci.ts", "public moves"):
        assert expected in changes, expected


# --- Go: one function ------------------------------------------------------


def test_go_seed_repository_holds_the_stub_and_go_mod_only():
    assert _seed_files(GO_PACK) == ["go.mod", GO_STUB]
    go_mod = (GO_PACK / "environment" / "seed" / "go.mod").read_text(encoding="utf-8")
    assert go_mod == "module twobucket\n\ngo 1.27\n"


def test_go_stub_keeps_the_source_signature():
    stub = (GO_PACK / "environment" / "seed" / GO_STUB).read_text(encoding="utf-8")
    assert stub.startswith("package twobucket\n")
    assert re.findall(r"^(func .*?)\s*\{", stub, re.M) == [
        "func Solve(sizeBucketOne, sizeBucketTwo, goalAmount int, startBucket string) "
        "(string, int, int, error)",
    ]
    assert 'panic("not implemented")' in stub


def test_go_reference_tests_are_the_two_renamed_source_files():
    names = sorted(p.name for p in (GO_PACK / "tests" / "reference").iterdir())
    assert names == ["assay_reference_cases_test.go", "assay_reference_two_bucket_test.go"]


def test_go_interface_states_the_function_api_and_no_test_word():
    text = (GO_PACK / "instruction.md").read_text(encoding="utf-8")
    assert "test" not in text.split("Implement the solution in")[0].lower()
    section = _interface_section(GO_PACK, GO_STUB)
    assert "Solve(" in section
    for bucket in ('`"one"`', '`"two"`'):
        assert bucket in section, bucket
    assert "error" in section


def test_go_metadata_records_the_provenance_and_each_mechanical_change():
    meta = _toml(GO_PACK)["metadata"]
    assert meta["source_repo"] == "https://github.com/exercism/go"
    assert meta["source_commit"] == _toml(GO_PACK.parent / "split-second-stopwatch")["metadata"]["source_commit"]
    assert meta["source_dir"] == "exercises/practice/two-bucket"
    assert meta["seed_files"] == ["go.mod", GO_STUB]
    assert len(meta["pack_paths"]) == len(meta["copied_paths"])
    assert any(p.endswith(".meta/example.go") for p in meta["copied_paths"])
    assert any(p.endswith("cases_test.go") for p in meta["copied_paths"])
    changes = " ".join(meta["mechanical_changes"])
    for expected in ("Interface section", GO_STUB, "not implemented", "instructions.append.md"):
        assert expected in changes, expected


# --- Slow: the pack images and tests/test.sh (Docker) ----------------------

# Each agent test below compiles under the language's runner but not under the
# type checker / compiler the verifier uses: TS `moves()` gives a number, Go
# calls a function that does not exist.
TS_NON_COMPILING_AGENT_TEST = """\
import { expect, it } from '@jest/globals'
import { TwoBucket } from './two-bucket.ts'

it('counts the moves', () => {
  const moves: string = new TwoBucket(3, 5, 1, 'one').moves()
  expect(moves).toBe(4)
})
"""

GO_NON_COMPILING_AGENT_TEST = """package twobucket

import "testing"

func TestCountsTheMoves(t *testing.T) {
	undefinedHelper()
}
"""

PACKS = {
    # language: (pack, stub, gold solution file, reference count, agent test name, agent test)
    "typescript": (TS_PACK, TS_STUB, "proof.ci.ts", TS_REFERENCE_TEST_COUNT,
                   "two-bucket.test.ts", TS_NON_COMPILING_AGENT_TEST),
    "go": (GO_PACK, GO_STUB, "example.go", GO_REFERENCE_TEST_COUNT,
           "two_bucket_test.go", GO_NON_COMPILING_AGENT_TEST),
}


def _docker(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


@pytest.fixture(scope="module", params=list(PACKS))
def pack_image(request):
    """(language, image tag) for each pack, built once per module."""
    pack = PACKS[request.param][0]
    tag = f"assay-test-{request.param}-two-bucket:{uuid.uuid4().hex[:8]}"
    build = _docker("build", "-q", "-t", tag, str(pack / "environment"), timeout=1200)
    assert build.returncode == 0, build.stderr
    yield request.param, tag
    _docker("image", "rm", "-f", tag)


def _verify(language: str, image: str, tmp_path: Path, files: dict[str, str]) -> dict:
    """Write `files` over the seed repository in `/app`, run tests/test.sh with
    no network, and return its reward.json."""
    pack = PACKS[language][0]
    prep = tmp_path / "prep"
    prep.mkdir()
    for name, content in files.items():
        (prep / name).write_bytes(content.encode("utf-8"))
    out = tmp_path / "verifier"
    out.mkdir()
    result = _docker("run", "--rm", "--network", "none",
                     "-v", f"{pack / 'tests'}:/tests:ro", "-v", f"{prep}:/prep:ro",
                     "-v", f"{out}:/logs/verifier",
                     image, "bash", "-c", "cp -a /prep/. /app/ && bash /tests/test.sh")
    reward = out / "reward.json"
    assert reward.exists(), result.stdout + result.stderr
    values = json.loads(reward.read_text(encoding="utf-8"))
    assert set(values) == REWARD_KEYS
    assert all(type(v) in (int, float) for v in values.values())
    return values


def _gold(language: str) -> str:
    pack, _, gold, *_ = PACKS[language]
    return (pack / "solution" / gold).read_text(encoding="utf-8")


@pytest.mark.slow
def test_image_holds_only_the_seed_commit(pack_image):
    language, image = pack_image
    pack = PACKS[language][0]
    result = _docker("run", "--rm", "--network", "none", image, "bash", "-c",
                     "set -e; cd /app; test ! -e ~/.claude/skills; test ! -e .claude;"
                     " git log --format=%s; git status --porcelain | wc -l; git ls-files")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.split()
    assert lines[:2] == ["seed", "0"]
    assert sorted(lines[2:]) == _seed_files(pack)


@pytest.mark.slow
def test_gold_solution_gives_reward_1(pack_image, tmp_path):
    language, image = pack_image
    _, stub, _, count, _, _ = PACKS[language]
    reward = _verify(language, image, tmp_path, {stub: _gold(language)})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == count
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_untouched_stub_gives_reward_0_and_the_reference_tests_compile(pack_image, tmp_path):
    language, image = pack_image
    reward = _verify(language, image, tmp_path, {})
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["agent_tests_total"] == 0
    if language == "typescript":
        # A Go stub panics, which ends the run after the first case.
        assert reward["reference_total"] == TS_REFERENCE_TEST_COUNT
        assert reward["reference_passed"] < TS_REFERENCE_TEST_COUNT


@pytest.mark.slow
def test_agent_test_that_does_not_compile_leaves_the_outcome_pass_unaffected(pack_image, tmp_path):
    language, image = pack_image
    _, stub, _, count, test_name, broken = PACKS[language]
    reward = _verify(language, image, tmp_path, {stub: _gold(language), test_name: broken})
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == count
    # The red-compile rule: no test passes, and each agent test file counts.
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 1


# --- Slow: Harbor ----------------------------------------------------------


def _harbor_reward(language: str, agent: str, tmp_path: Path) -> dict:
    job = f"{language}-two-bucket-{agent}"
    result = subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(PACKS[language][0]), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (trial,) = [p for p in (tmp_path / job).iterdir() if p.is_dir()]
    rewards = json.loads((trial / "result.json").read_text(encoding="utf-8"))["verifier_result"]["rewards"]
    assert set(rewards) == REWARD_KEYS
    return rewards


@pytest.mark.slow
@pytest.mark.parametrize("language", list(PACKS))
def test_harbor_oracle_agent_gets_reward_1(language, tmp_path):
    rewards = _harbor_reward(language, "oracle", tmp_path)
    assert rewards["reward"] == 1
    assert rewards["reference_passed"] == rewards["reference_total"] == PACKS[language][3]


@pytest.mark.slow
@pytest.mark.parametrize("language", list(PACKS))
def test_harbor_do_nothing_agent_gets_reward_0(language, tmp_path):
    rewards = _harbor_reward(language, "nop", tmp_path)
    assert rewards["reward"] == 0
    assert rewards["reference_compiles"] == 1
    assert rewards["agent_tests_total"] == 0
