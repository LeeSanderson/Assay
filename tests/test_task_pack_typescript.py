"""The TypeScript task pack `tasks/typescript/split-second-stopwatch/`.

The fast tests read the pack's files. The slow tests (seam 5) need Docker:
they run `tests/test.sh` on prepared repositories in the task image with no
network, as replay does, and they run the pack through Harbor with the
`oracle` and do-nothing (`nop`) agents.
"""

import json
import re
import subprocess
import tomllib
import uuid
from pathlib import Path

import pytest

from analyze.languages import TEST, classify

REPO_ROOT = Path(__file__).resolve().parent.parent
PACK = REPO_ROOT / "tasks" / "typescript" / "split-second-stopwatch"
SEED = PACK / "environment" / "seed"
STUB = "split-second-stopwatch.ts"
REFERENCE_TEST = "assay-reference.split-second-stopwatch.test.ts"
REWARD_KEYS = {
    "reward", "reference_compiles", "reference_passed", "reference_total",
    "agent_tests_compile", "agent_tests_passed", "agent_tests_total",
}
REFERENCE_TEST_COUNT = 29


def _metadata() -> dict:
    return tomllib.loads((PACK / "task.toml").read_text(encoding="utf-8"))["metadata"]


def _seed_files() -> list[str]:
    return sorted(p.relative_to(SEED).as_posix() for p in SEED.rglob("*") if p.is_file())


# --- The pack's files -------------------------------------------------------


def test_reference_tests_carry_the_prefix_and_no_xit():
    tests = [p.name for p in (PACK / "tests").iterdir() if classify("typescript", p.name) == TEST]
    assert tests == [REFERENCE_TEST]
    text = (PACK / "tests" / REFERENCE_TEST).read_text(encoding="utf-8")
    assert not re.search(r"\bxit\(", text)
    assert len(re.findall(r"^\s*it\(", text, re.MULTILINE)) == REFERENCE_TEST_COUNT


def test_seed_repository_holds_the_prd_files_and_no_test_or_claude_dir():
    assert _seed_files() == sorted([
        STUB, "package.json", "yarn.lock", ".yarnrc.yml", "tsconfig.json",
        "jest.config.cjs", "babel.config.cjs", "eslint.config.mjs",
    ])
    assert not (SEED / ".claude").exists()
    assert (SEED / "yarn.lock").stat().st_size > 0


def test_prompt_is_the_exercism_instructions_plus_the_footer():
    text = (PACK / "instruction.md").read_text(encoding="utf-8")
    assert text.startswith("# Instructions\n\nYour task is to build a stopwatch")
    assert text.endswith(
        "Implement the solution in `split-second-stopwatch.ts`. Keep the exported "
        "names and signatures as they are. Tests that you cannot see will check "
        "your solution.\n"
    )


def test_task_toml_sets_the_prd_limits():
    config = tomllib.loads((PACK / "task.toml").read_text(encoding="utf-8"))
    assert config["agent"]["timeout_sec"] == 1800
    assert config["verifier"]["timeout_sec"] == 600
    assert config["environment"]["cpus"] == 2
    assert config["environment"]["memory_mb"] == 4096
    assert config["environment"].get("network_mode", "public") == "public"


def test_metadata_records_the_provenance():
    meta = _metadata()
    assert meta["source_repo"] == "https://github.com/exercism/typescript"
    assert re.fullmatch(r"[0-9a-f]{40}", meta["source_commit"])
    exercise = "exercises/practice/split-second-stopwatch/"
    assert set(meta["copied_paths"]) >= {
        exercise + STUB,
        exercise + "split-second-stopwatch.test.ts",
        exercise + ".meta/proof.ci.ts",
        exercise + ".docs/instructions.md",
    }
    assert all(p.startswith(exercise) for p in meta["copied_paths"])
    assert any("xit" in change for change in meta["mechanical_changes"])
    assert any("assay-reference." in change for change in meta["mechanical_changes"])
    assert sorted(meta["seed_files"]) == _seed_files()


def test_metadata_image_digest_is_the_dockerfile_base_image():
    dockerfile = (PACK / "environment" / "Dockerfile").read_text(encoding="utf-8")
    base = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE).group(1)
    assert re.fullmatch(r"node:\d+[\d.]*-bookworm@sha256:[0-9a-f]{64}", base)
    assert _metadata()["base_image"] == base


def test_pack_files_have_lf_line_endings():
    for path in PACK.rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path


# --- Seam 5: test.sh in the task image (Docker) ------------------------------

PASSING_AGENT_TESTS = """\
import { describe, expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from './split-second-stopwatch.ts'

describe('agent', () => {
  it('starts ready', () => {
    expect(new SplitSecondStopwatch().state).toBe('ready')
  })
  it('is wrong on purpose', () => {
    expect(new SplitSecondStopwatch().state).toBe('running')
  })
  it.skip('is skipped', () => {})
})
"""

NESTED_SPEC = """\
import { expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from '../split-second-stopwatch.ts'

it('has no laps', () => {
  expect(new SplitSecondStopwatch().previousLaps).toEqual([])
})
"""

# Runs under babel-jest, but does not type-check.
NON_COMPILING_AGENT_TEST = """\
import { expect, it } from '@jest/globals'
import { SplitSecondStopwatch } from './split-second-stopwatch.ts'

it('starts ready', () => {
  const laps: number = new SplitSecondStopwatch().previousLaps
  expect(laps).toEqual([])
})
"""


def _proof() -> str:
    return (PACK / "solution" / "proof.ci.ts").read_text(encoding="utf-8")


def _docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)


@pytest.fixture(scope="module")
def image():
    tag = f"assay-test-ts-sss:{uuid.uuid4().hex[:8]}"
    build = _docker("build", "-q", "-t", tag, str(PACK / "environment"), timeout=1200)
    assert build.returncode == 0, build.stderr
    yield tag
    _docker("image", "rm", "-f", tag)


def _run_in_image(image: str, script: str, files: dict[str, str] | None = None,
                  tmp_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run a bash script in a fresh container with no network.

    `files` are written over `/app` first (paths relative to `/app`); the pack's
    `tests/` folder is mounted at `/tests`, as Harbor uploads it.
    """
    mounts = ["-v", f"{PACK / 'tests'}:/tests:ro"]
    prelude = ""
    if files:
        overlay = tmp_path / "overlay"
        for rel, content in files.items():
            target = overlay / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        mounts += ["-v", f"{overlay}:/overlay:ro"]
        prelude = "cp -r /overlay/. /app/ && "
    return _docker("run", "--rm", "--network", "none", *mounts, image,
                   "bash", "-c", prelude + script, timeout=600)


def _verify(image: str, tmp_path: Path, files: dict[str, str] | None = None) -> dict:
    result = _run_in_image(
        image, "bash /tests/test.sh >/dev/null 2>&1; cat /logs/verifier/reward.json",
        files, tmp_path)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.slow
def test_reward_json_holds_the_seven_numeric_fields(image, tmp_path):
    reward = _verify(image, tmp_path, {STUB: _proof()})
    assert set(reward) == REWARD_KEYS
    assert all(type(v) in (int, float) for v in reward.values())


@pytest.mark.slow
def test_agent_pass_counts_the_prd_test_file_class_only(image, tmp_path):
    # `__tests__/*.ts` and `*.test.js` match Jest's default patterns but not the
    # PRD's TypeScript test-file class (`*.test.ts`, `*.spec.ts`), so the
    # agent pass must not count them.
    files = {
        STUB: _proof(),
        "split-second-stopwatch.test.ts": PASSING_AGENT_TESTS,
        "nested/laps.spec.ts": NESTED_SPEC,
        "__tests__/extra.ts": NESTED_SPEC,
        "other.test.js": "it('x', () => {})\n",
    }
    # The analyzer's table is the source of the class; test.sh must agree with it.
    assert [f for f in files if classify("typescript", f) == TEST] == [
        "split-second-stopwatch.test.ts", "nested/laps.spec.ts"]
    reward = _verify(image, tmp_path, files)
    assert reward == {
        "reward": 1, "reference_compiles": 1,
        "reference_passed": REFERENCE_TEST_COUNT, "reference_total": REFERENCE_TEST_COUNT,
        # A skipped test counts in the total but not as passed.
        "agent_tests_compile": 1, "agent_tests_passed": 2, "agent_tests_total": 4,
    }


@pytest.mark.slow
def test_non_compiling_agent_tests_leave_the_outcome_pass_unaffected(image, tmp_path):
    reward = _verify(image, tmp_path, {
        STUB: _proof(),
        "split-second-stopwatch.test.ts": NON_COMPILING_AGENT_TEST,
        "nested/broken.spec.ts": NON_COMPILING_AGENT_TEST.replace("'./", "'../"),
    })
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == REFERENCE_TEST_COUNT
    assert reward["agent_tests_compile"] == 0


@pytest.mark.slow
def test_changed_stub_signature_fails_the_reference_compile(image, tmp_path):
    changed = _proof().replace("advanceTime(duration: string)", "advanceTime(duration: number)")
    assert changed != _proof()
    reward = _verify(image, tmp_path, {STUB: changed})
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0


@pytest.mark.slow
def test_no_agent_tests_gives_zero_agent_tests_total(image, tmp_path):
    reward = _verify(image, tmp_path, {STUB: _proof()})
    assert reward["agent_tests_total"] == 0
    assert reward["agent_tests_compile"] == 1
    assert reward["reward"] == 1


@pytest.mark.slow
def test_no_agent_tests_and_code_that_does_not_build_gives_zero_compile(image, tmp_path):
    reward = _verify(image, tmp_path, {STUB: _proof() + "\nconst broken: number = 'x'\n"})
    assert reward["agent_tests_total"] == 0
    assert reward["agent_tests_compile"] == 0
    assert reward["reference_compiles"] == 0


@pytest.mark.slow
def test_seed_stub_gives_zero_reward(image, tmp_path):
    reward = _verify(image, tmp_path)
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["reference_total"] == REFERENCE_TEST_COUNT
    assert reward["reference_passed"] < REFERENCE_TEST_COUNT


@pytest.mark.slow
def test_verifier_leaves_the_repository_unchanged(image, tmp_path):
    result = _run_in_image(
        image,
        "bash /tests/test.sh >/dev/null 2>&1; git -C /app status --porcelain; ls /app",
        {"split-second-stopwatch.test.ts": PASSING_AGENT_TESTS}, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "?? split-second-stopwatch.test.ts"
    assert REFERENCE_TEST not in result.stdout


@pytest.mark.slow
def test_image_holds_seed_commit_and_no_claude_config(image, tmp_path):
    result = _run_in_image(image, " ; ".join([
        "cd /app",
        "git log --format=%s",
        "git ls-files",
        "git status --porcelain | wc -l",
        "test -e ~/.claude/skills && echo HAS_SKILLS",
        "test -e /app/.claude && echo HAS_CLAUDE",
        "true",
    ]))
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "seed"
    tracked = lines[1:-1]
    assert sorted(tracked) == _seed_files()
    assert lines[-1] == "0"
    assert "HAS_SKILLS" not in result.stdout and "HAS_CLAUDE" not in result.stdout


# --- Seam 5: Harbor --------------------------------------------------------


def _harbor_reward(agent: str, tmp_path: Path) -> dict:
    job = f"ts-sss-{agent}"
    result = subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(PACK), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1800,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rewards = list((tmp_path / job).glob("*/verifier/reward.json"))
    assert len(rewards) == 1, result.stdout
    return json.loads(rewards[0].read_text(encoding="utf-8"))


@pytest.mark.slow
def test_harbor_oracle_agent_gets_full_reward(tmp_path):
    reward = _harbor_reward("oracle", tmp_path)
    assert set(reward) == REWARD_KEYS
    assert reward["reward"] == 1
    assert reward["reference_passed"] == REFERENCE_TEST_COUNT


@pytest.mark.slow
def test_harbor_do_nothing_agent_gets_zero_reward(tmp_path):
    reward = _harbor_reward("nop", tmp_path)
    assert set(reward) == REWARD_KEYS
    assert reward["reward"] == 0
    assert reward["agent_tests_total"] == 0
